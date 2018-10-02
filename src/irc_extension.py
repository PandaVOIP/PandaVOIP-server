import socketserver
from irc.server import *

class CustomIRC(object):
    def __init__(self, request, client_address, server):
        self.request = request
        self.user = None
        self.host = client_address  # Client's hostname / ip.
        self.realname = None        # Client's real name
        self.nick = None            # Client's currently registered nickname
        self.send_queue = []        # Messages to send to client (strings)
        self.channels = dict()        # Channels the client is in
        self.buffer = None
    
    def irc_handle(self, data):
        while self.send_queue:
            msg = self.send_queue.pop(0)
            self._send(msg)  

        for line in data.decode('utf-8').splitlines():
            self._handle_line(line)                    
                     

    def _handle_line(self, line):
        try:
            log.debug('from %s: %s' % (self.client_ident(), line))
            command, sep, params = line.partition(' ')
            handler = getattr(self, 'handle_%s' % command.lower(), None)
            if not handler:
                _tmpl = 'No handler for command: %s. Full line: %s'
                log.info(_tmpl % (command, line))
                raise IRCError.from_name(
                    'unknowncommand',
                    '%s :Unknown command' % command)
            response = handler(params)
        except AttributeError as e:
            log.error(six.text_type(e))
            raise
        except IRCError as e:
            response = ':%s %s %s' % (self.server.servername, e.code, e.value)
            log.error(response)
        except Exception as e:
            response = ':%s ERROR %r' % (self.server.servername, e)
            log.error(response)
            raise

        if response:
            self._send(response)

        

    def _send(self, msg):
        print("sending", msg)
        try:
            self.request.send(msg.encode('utf-8') + b'\r\n')
        except socket.error as e:
            if e.errno == errno.EPIPE:
                raise self.Disconnect()
            else:
                raise

    def handle_nick(self, params):
        """
        Handle the initial setting of the user's nickname and nick changes.
        """
        nick = params
        print("nick")
        # Valid nickname?
        if re.search('[^a-zA-Z0-9\-\[\]\'`^{}_]', nick):
            raise IRCError.from_name('erroneusnickname', ':%s' % nick)

        if self.server.clients.get(nick, None) == self:
            # Already registered to user
            return

        if nick in self.server.clients:
            # Someone else is using the nick
            raise IRCError.from_name('nicknameinuse', 'NICK :%s' % (nick))

        if not self.nick:
            # New connection and nick is available; register and send welcome
            # and MOTD.
            self.nick = nick
            self.server.clients[nick] = self
            response = ':%s %s %s :%s' % (
                self.server.servername,
                events.codes['welcome'], self.nick, SRV_WELCOME)
            self._send(response)
            response = ':%s 376 %s :End of MOTD command.' % (
                self.server.servername, self.nick)
            self._send(response)
            return

        # Nick is available. Change the nick.
        message = ':%s NICK :%s' % (self.client_ident(), nick)
        print(message)
        self.server.clients.pop(self.nick)
        self.nick = nick
        self.server.clients[self.nick] = self

        # Send a notification of the nick change to all the clients in the
        # channels the client is in.
        for channel in self.channels.values():
            self._send_to_others(message, channel)

        # Send a notification of the nick change to the client itself
        return message

    def handle_user(self, params):
        """
        Handle the USER command which identifies the user to the server.
        """
        params = params.split(' ', 3)

        if len(params) != 4:
            raise IRCError.from_name(
                'needmoreparams',
                'USER :Not enough parameters')

        user, mode, unused, realname = params
        self.user = user
        self.mode = mode
        self.realname = realname
        return ''

    def handle_ping(self, params):
        """
        Handle client PING requests to keep the connection alive.
        """
        response = ':{self.server.servername} PONG :{self.server.servername}'
        return response.format(**locals())

    def handle_join(self, params):
        """
        Handle the JOINing of a user to a channel. Valid channel names start
        with a # and consist of a-z, A-Z, 0-9 and/or '_'.
        """
        channel_names = params.split(' ', 1)[0]  # Ignore keys
        for channel_name in channel_names.split(','):
            r_channel_name = channel_name.strip()

            # Valid channel name?
            if not re.match('^#([a-zA-Z0-9_])+$', r_channel_name):
                raise IRCError.from_name(
                    'nosuchchannel',
                    '%s :No such channel' % r_channel_name)

            # Add user to the channel (create new channel if not exists)
            channel = self.server.channels.setdefault(
                r_channel_name,
                IRCChannel(r_channel_name))
            channel.clients.add(self)

            # Add channel to user's channel list
            self.channels[channel.name] = channel

            # Send the topic
            response_join = ':%s TOPIC %s :%s' % (
                channel.topic_by,
                channel.name, channel.topic)
            self._send(response_join)

            # Send join message to everybody in the channel, including yourself
            # and send user list of the channel back to the user.
            response_join = ':%s JOIN :%s' % (
                self.client_ident(),
                r_channel_name)
            for client in channel.clients:
                client._send(response_join)

            nicks = [client.nick for client in channel.clients]
            _vals = (
                self.server.servername, self.nick, channel.name,
                ' '.join(nicks))
            response_userlist = ':%s 353 %s = %s :%s' % _vals
            self._send(response_userlist)

            _vals = self.server.servername, self.nick, channel.name
            response = ':%s 366 %s %s :End of /NAMES list' % _vals
            self._send(response)

    def handle_privmsg(self, params):
        """
        Handle sending a private message to a user or channel.
        """
        target, sep, msg = params.partition(' ')
        if not msg:
            raise IRCError.from_name(
                'needmoreparams',
                'PRIVMSG :Not enough parameters')

        message = ':%s PRIVMSG %s %s' % (self.client_ident(), target, msg)
        if target.startswith('#') or target.startswith('$'):
            # Message to channel. Check if the channel exists.
            channel = self.server.channels.get(target)
            if not channel:
                raise IRCError.from_name('nosuchnick', 'PRIVMSG :%s' % target)

            if channel.name not in self.channels:
                # The user isn't in the channel.
                raise IRCError.from_name(
                    'cannotsendtochan',
                    '%s :Cannot send to channel' % channel.name)

            self._send_to_others(message, channel)
        else:
            # Message to user
            client = self.server.clients.get(target, None)
            if not client:
                raise IRCError.from_name('nosuchnick', 'PRIVMSG :%s' % target)

            client._send(message)

    def _send_to_others(self, message, channel):
        """
        Send the message to all clients in the specified channel except for
        self.
        """
        other_clients = [
            client for client in channel.clients
            if not client == self]
        for client in other_clients:
            client._send(message)

    def handle_topic(self, params):
        """
        Handle a topic command.
        """
        channel_name, sep, topic = params.partition(' ')

        channel = self.server.channels.get(channel_name)
        if not channel:
            raise IRCError.from_name(
                'nosuchnick', 'PRIVMSG :%s' % channel_name)
        if channel.name not in self.channels:
            # The user isn't in the channel.
            raise IRCError.from_name(
                'cannotsendtochan',
                '%s :Cannot send to channel' % channel.name)

        if topic:
            channel.topic = topic.lstrip(':')
            channel.topic_by = self.nick
        message = ':%s TOPIC %s :%s' % (
            self.client_ident(), channel_name,
            channel.topic)
        return message

    def handle_part(self, params):
        """
        Handle a client parting from channel(s).
        """
        for pchannel in params.split(','):
            if pchannel.strip() in self.server.channels:
                # Send message to all clients in all channels user is in, and
                # remove the user from the channels.
                channel = self.server.channels.get(pchannel.strip())
                response = ':%s PART :%s' % (self.client_ident(), pchannel)
                if channel:
                    for client in channel.clients:
                        client._send(response)
                print(channel.clients)
                channel.clients.remove(self)
                self.channels.pop(pchannel)
            else:
                _vars = self.server.servername, pchannel, pchannel
                response = ':%s 403 %s :%s' % _vars
                self._send(response)

    def handle_quit(self, params):
        """
        Handle the client breaking off the connection with a QUIT command.
        """
        response = ':%s QUIT :%s' % (self.client_ident(), params.lstrip(':'))
        # Send quit message to all clients in all channels user is in, and
        # remove the user from the channels.
        for channel in self.channels.values():
            for client in channel.clients:
                client._send(response)
            print(channel.clients)
            channel.clients.remove(self)

    def handle_dump(self, params):
        """
        Dump internal server information for debugging purposes.
        """
        print("Clients:", self.server.clients)
        for client in self.server.clients.values():
            print(" ", client)
            for channel in client.channels.values():
                print("     ", channel.name)
        print("Channels:", self.server.channels)
        for channel in self.server.channels.values():
            print(" ", channel.name, channel)
            for client in channel.clients:
                print("     ", client.nick, client)

    def handle_ison(self, params):
        response = ':%s 303 %s :' % (self.server.servername, self.client_ident().nick)
        if len(params) == 0 or params.isspace():
            response = ':%s 461 %s ISON :Not enough parameters' % (self.server.servername, self.client_ident().nick)
            return response    
        nickOnline = []
        for nick in params.split(" "):
            if nick in self.server.clients:
                nickOnline.append(nick)
        response += ' '.join(nickOnline)
        return response

    def client_ident(self):
        """
        Return the client identifier as included in many command replies.
        """
        return irc.client.NickMask.from_params(
            self.nick, self.user,
            self.server.servername)

    def finish(self):
        """
        The client conection is finished. Do some cleanup to ensure that the
        client doesn't linger around in any channel or the client list, in case
        the client didn't properly close the connection with PART and QUIT.
        """
        log.info('Client disconnected: %s', self.client_ident())
        response = ':%s QUIT :EOF from client' % self.client_ident()
        for channel in self.channels.values():
            if self in channel.clients:
                # Client is gone without properly QUITing or PARTing this
                # channel.
                for client in channel.clients:
                    client._send(response)
                channel.clients.remove(self)
        if self.nick:
            self.server.clients.pop(self.nick)
        log.info('Connection finished: %s', self.client_ident())

    def __repr__(self):
        """
        Return a user-readable description of the client
        """
        return '<%s %s!%s@%s (%s)>' % (
            self.__class__.__name__,
            self.nick,
            self.user,
            self.host[0],
            self.realname,
        )