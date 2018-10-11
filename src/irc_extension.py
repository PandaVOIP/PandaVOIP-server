import socketserver
import random
import logging
import re

logging.basicConfig(format='%(asctime)-15s %(message)s')
log = logging.getLogger('tcpserver')

class CustomIRC(object):
    def __init__(self):
        self.nick = None            
        self.realname = None        

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
                response = "421 " + command + " :Unknown command"
            else:
                response = handler(params)
        except AttributeError as e:
            log.error(six.text_type(e))
            raise
        except Exception as e:
            response = ':%s ERROR %r' % (self.server.servername, e)
            log.error(response)
            raise

        if response:
            self._send(response)

        

    def _send(self, msg, sock=None):
        print("sending", msg)
        if sock == None:
            sock = self.request
        try:
            sock.send(msg.encode('utf-8') + b'\r\n')
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

        if self.server.clients.get(nick, None) == self:
            # Already registered to user
            return

        if nick in self.server.clients:
            # Someone else is using the nick
            pass

        if not self.nick:
            # New connection and nick is available; register and send welcome
            # and MOTD.
            self.nick = nick
            self.server.clients[nick] = self
            return

        # Nick is available. Change the nick.
        message = ':%s NICK :%s' % (self.client_ident(), nick)
        print(message)
        self.server.clients.pop(self.nick)
        self.nick = nick
        self.server.clients.append(self.nick)

        # Send a notification of the nick change to all the clients in the
        # channels the client is in.
        for channel in self.channels:
            self._send_to_others(message, channel)

        # Send a notification of the nick change to the client itself
        return message

    def handle_user(self, params):
        """
        Handle the USER command which identifies the user to the server.
        """
        params = params.split(' ', 3)

        if len(params) != 4:
            # need more params
            pass

        user, mode, unused, realname = params
        self.user = user
        self.mode = mode
        self.realname = realname
        response = ":{} {} {} :{}".format(
            self.server.servername, "001", self.nick,
            "Welcome to the Hug Hug Panda Club " + self.nick + "!" + self.user + "@" + self.server.servername
        )
        self._send(response)
        response = ":{} {} {} :{}".format(
            self.server.servername, "002", self.nick,
            "LOL?"
        )
        self._send(response)
        response = ":{} {} {} :{}".format(
            self.server.servername, "003", self.nick,
            "WORK!"
        )
        self._send(response)
        response = ":{} {} {} :{}".format(
            self.server.servername, "004", self.nick,
            "please"
        )
        self._send(response)
        response = ":{} {} {} :{}".format(
            self.server.servername,
            "376",
            self.nick,
            "Welcome to pandavoip. Feel free to join #general."
        )
        self._send(response)
        self.client_id = random.randint(0, 1000000)
        self.command_client = self.server.add_client_if_new(self.client_id, self.request, client_type="irc")
        self.command_client.client_ident = self.client_ident()
        self.command_client.username = self.nick

    def handle_ping(self, params):
        """
        Handle client PING requests to keep the connection alive.
        """
        if len(params) < 1:
            response = ":{} {} {} :{}".format(
                self.server.servername,
                "409",
                self.nick,
                "No origin specified"
            )
        else:
            response = ":{} {} {} :{}".format(
                self.server.servername,
                "PONG",
                self.nick,
                params[1:]
            )
        self._send(response)

    def handle_join(self, params):
        """
        Handle the JOINing of a user to a channel. Valid channel names start
        with a # and consist of a-z, A-Z, 0-9 and/or '_'.
        """
        channel_names = params.split(' ', 1)[0]  # Ignore keys
        for channel_name in channel_names.split(','):
            r_channel_name = channel_name.strip()[1:]
            if r_channel_name[0] != '#':
                r_channel_name = '#' + r_channel_name

            # Valid channel name?
            if not re.match('^#([a-zA-Z0-9_])+$', r_channel_name):
                pass

            # Add user to the channel (create new channel if not exists)
            channel = self.server.get_channel(r_channel_name)

            # Add channel to user's channel list
            if r_channel_name not in self.channels:
                self.channels = r_channel_name

            channel["members"].append(self.command_client)

            # Send the topic
            response = ":{} {} {} {} :{}".format(
                self.server.servername,
                "331",
                self.nick,
                r_channel_name,
                "No topic is set"
            )
            self._send(response)

            # Send join message to everybody in the channel, including yourself
            # and send user list of the channel back to the user.
            response_join = ":{} JOIN {}".format(
                self.client_ident(),
                r_channel_name)
            for client in channel["members"]:
                self._send(response_join, sock=client.socket)

            nicks = [c.username for c in channel["members"]]
            _vals = (
                self.server.servername, self.nick, r_channel_name,
                ' '.join(nicks))
            response_userlist = ':%s 353 %s = %s :%s' % _vals
            self._send(response_userlist)

            _vals = self.server.servername, self.nick, r_channel_name
            response = ':%s 366 %s %s :End of NAMES list' % _vals
            self._send(response)

    def handle_list(self, params):
        response = ":{} {} {} {} :{} {}".format(
            self.server.servername,
            "321",
            self.nick,
            "Channel",
            "Users",
            "Name"
        )
        self._send(response)
        response = ":{} {} {} {} {} :{}".format(
            self.server.servername,
            "322",
            self.nick,
            "#general",
            len(self.server.get_channel("#general")["members"]),
            "No topic is set"
        )
        self._send(response)
        response = ":{} {} {} :{}".format(
            self.server.servername,
            "323",
            self.nick,
            "End of LIST"
        )
        self._send(response)

    def handle_privmsg(self, params):
        """
        Handle sending a private message to a user or channel.
        """
        target, sep, msg = params.partition(' ')
        if not msg:
            # need more params
            pass

        response = ":{} {} {} {}".format(
            self.client_ident(),
            "PRIVMSG",
            target,
            msg,
        )
        if target.startswith('#') or target.startswith('$'):
            # Message to channel. Check if the channel exists.
            channel = self.server.get_channel(target)
            if not channel:
                return

            if target not in self.channels:
                # The user isn't in the channel.
                return

            self._send_to_others(response, channel)
        else:
            pass
            # Message to user
            # client = self.server.clients.get(target, None)
            # if not client:
            #     pass

            # client._send(message)

    def _send_to_others(self, message, channel):
        """
        Send the message to all clients in the specified channel except for
        self.
        """
        other_clients = [
            client for client in channel["members"] if not client.am_i(self.client_id)
        ]
        for client in other_clients:
            self._send(message, sock=client.socket)

    def handle_topic(self, params):
        """
        Handle a topic command.
        """
        channel_name, sep, topic = params.partition(' ')

        channel = self.server.channels.get(channel_name)
        if not channel:
            pass
        if channel.name not in self.channels:
            # The user isn't in the channel.
            pass

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
        # Send quit message to all clients in all channels user is in, and
        # remove the user from the channels.
        response = ":{} {} :{}".format(
            self.client_ident(),
            "QUIT",
            params.lstrip(':')
        )
        self._send(response)

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
        return "{}!{}@{}".format(self.nick, self.user, self.server.servername)

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
