#!/usr/bin/env python3

import socketserver
import threading
import traceback
import os
import sys
import time
import json
import re
import ssl

from configparser import ConfigParser

from irc_extension import CustomIRC

# object for voice client information
class VoiceClient(object):
    def __init__(self, client_id, addr):
        self.client_id = client_id
        self.addr = addr

    # comparitor
    def am_i(self, client_id, addr):
        return self.client_id == client_id and self.addr == addr

    def get_cid(self):
        return self.client_id


class UDPVoiceHandler(socketserver.BaseRequestHandler):
    def handle(self):
        data = self.request[0]
        socket = self.request[1]
        addr = self.client_address
        # get the client_id
        client_id = int.from_bytes(data[0:4], byteorder='little')
        # check if this client_id is allowed
        if not self.server.check_allowed_client(client_id):
            return
        # add client if new connection
        self.server.add_client_if_new(client_id, addr)
        # send to all other clients
        for client in self.server.connections:
            # check if the client is the one who sent the data
            if not client.am_i(client_id, addr):
                # check if the client is in the voice chat
                if (client.client_id in self.server.allowed_connections):
                    self.server.socket.sendto(data, client.addr)
                else:
                    self.server.connections.remove(client)


# voice server
class ThreadedVoiceServer(socketserver.ThreadingMixIn, socketserver.UDPServer):
    def __init__(self, *args, **kwargs):
        super(ThreadedVoiceServer, self).__init__(*args, **kwargs)
        self.connections = []
        self.allowed_connections = []
        self.command_server = None

    def add_client_if_new(self, client_id, addr):
        for client in self.connections:
            if client.am_i(client_id, addr):
                return

        self.connections.append(VoiceClient(client_id, addr))

    def check_allowed_client(self, client_id):
        return client_id in self.allowed_connections

    def attach_command_server(self, command_server):
        self.voice_server = command_server


class CommandClient(object):
    def __init__(self, client_id, socket):
        self.socket = socket
        self.client_id = client_id

    def am_i(self, client_id):
        return self.client_id == client_id


class TCPCommandHandler(socketserver.BaseRequestHandler, CustomIRC):
    def __init__(self, *args, **kwargs):
        CustomIRC.__init__(self, *args, **kwargs)
        super(TCPCommandHandler, self).__init__(*args, **kwargs)


    def handle(self):
        # handle their connection until they disconnect
        while True:
            try:
                # read the data
                data = self.request.recv(8192).strip()
                print(data)
                if not data:
                    continue
                # only care about the non 0 data
                data = data.split(b'\x00')[0]
                if data[0] is not '{':
                    self.irc_handle(data)
                    continue

                try:
                    # try to parse a json
                    request = json.loads(data.decode())
                except ValueError:
                    # tell them if it is invalid
                    json_data = {
                        "command": "nack",
                        "message": "invalid json"
                    }
                    self.server.send_data(self.request, json.dumps(json_data))
                    continue
            # client disconnect
            except ConnectionResetError:
                self.server.disconnect(client_id)
                return

            # parse the data
            client_id = request['client_id']
            command = request['command']
            self.server.add_client_if_new(client_id, self.request)

            # establishing a new connection
            if command == "establish":
                json_data = {
                    "command": "ack",
                    "message": command
                }
                self.server.send_data(self.request, json.dumps(json_data))
                self.server.update_chat_clients()
                self.server.update_voice_clients()
            # connecting to the voice chat
            elif command == "voice connect":
                json_data = {
                    "command": "ack",
                    "message": command
                }
                self.server.voice_connect(client_id)
                self.server.send_data(self.request, json.dumps(json_data))

                self.server.update_voice_clients()
            # disconnecting from voice chat
            elif command == "voice disconnect":
                json_data = {
                    "command": "ack",
                    "message": command
                }
                self.server.voice_disconnect(client_id)
                self.server.send_data(self.request, json.dumps(json_data))

                self.server.update_voice_clients()
            # sending a text message
            elif command == "text message":
                self.server.text_message(client_id, request)
            # anything else isn't valid
            else:
                json_data = {
                    "command": "nack",
                    "message": "unknown command"
                }
                print("received unknown command from " + str(client_id) + ": " + command)


class ThreadedCommandServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    def __init__(self, *args, **kwargs):
        self.channels = {}
        key_file = kwargs.pop("key_file", None)
        cert_file = kwargs.pop("cert_file", None)
        super(ThreadedCommandServer, self).__init__(*args, **kwargs)
        self.allow_reuse_address = True
        self.connections = []
        self.clients = {}
        self.voice_server = None
        self.servername = "ritlew.com"
        if key_file and cert_file:
            self.socket = ssl.wrap_socket(
                            self.socket, 
                            keyfile=key_file, 
                            certfile=cert_file, 
                            cert_reqs=ssl.CERT_NONE
                            )
            print("SSL files found. Using encrypted connections.")
        else:
            print("SSL files not found or not configured properly. Using unencrypted connections.")

    # wrapper for sending data
    def send_data(self, socket, message):
        # send the length of the message first
        length = len(message.encode())
        socket.sendall(str(length).zfill(10).encode())
        # send the actual message
        socket.sendall(message.encode())

    # send the list of chat clients to all users
    def update_chat_clients(self):
        users = [str(c.client_id).zfill(8) for c in self.connections]
        json_data = {
            "command": "update_chat_users",
            "users": users
        }
        for client in self.connections:
            self.send_data(client.socket, json.dumps(json_data))

    # send the list of voice users to all clients
    def update_voice_clients(self):
        users = [str(c).zfill(8) for c in self.voice_server.allowed_connections]
        json_data = {
            "command": "update_voice_users",
            "users": users
        }
        for client in self.connections:
            self.send_data(client.socket, json.dumps(json_data))

    def add_client_if_new(self, client_id, socket):
        for client in self.connections:
            if client.am_i(client_id):
                return

        print("add tcp with client_id:", client_id)
        self.connections.append(CommandClient(client_id, socket))

    def disconnect(self, client_id):
        for client in self.connections:
            if client.am_i(client_id):
                self.connections.remove(client)
                print("command disconnect:", client_id)
                print("command clients:", [cli.client_id for cli in self.connections])
                break
        self.update_chat_clients()
        self.voice_disconnect(client_id)

    # relays a chat message to all users
    def text_message(self, client_id, request):
        response = {
            "command": "new_message",
            "message": {
                "sender_id": str(client_id),
                "text": request["message"]
            }
        }
        for client in self.connections:
            self.send_data(client.socket, json.dumps(response))

    def voice_connect(self, client_id):
        if self.voice_server is None:
            return
        if client_id not in self.voice_server.allowed_connections:
            self.voice_server.allowed_connections.append(client_id)
            print(client_id, "ok for voice")

    def voice_disconnect(self, client_id):
        if self.voice_server is None:
            return
        if client_id in self.voice_server.allowed_connections:
            self.voice_server.allowed_connections.remove(client_id)
            self.update_voice_clients()
            print("voice disconnect:", client_id)
            print("voice clients:", self.voice_server.allowed_connections)

    def attach_voice_server(self, voice_server):
        self.voice_server = voice_server

class ServerConfig(object):
    def __init__(self, filename):
        self.parser = ConfigParser()
        self.standard_config = {
            "main": {
                "ip": "",
                "command_port": "50039",
                "voice_port": "50038",
            },
            "ssl": {
                "key_file": "",
                "cert_file": ""
            }
        }
        self.read_or_create()
        self.verify_config()
        
    def read_or_create(self):
        if not os.path.exists("config.ini"):
            self.create_default_file()
        else:
            self.parser.read("config.ini")
            # ugly, but it is always only 2 levels
            for section in self.standard_config.keys():
                if section not in self.parser.keys() and section is not "DEFAULT":
                    print(section + " not found in config file. Creating default...")
                    self.parser[section] = self.standard_config[section]
                for key in self.standard_config[section].keys():
                    if key not in self.parser[section].keys():
                        print(key + " not found in " + section + " section. Creating default...")
                        self.parser[section][key] = self.standard_config[section][key]
            with open("config.ini", "w") as file:
                self.parser.write(file)

    def create_default_file(self):
        self.parser.read_dict(self.standard_config)
        with open("config.ini", "w") as file:
            self.parser.write(file)

    def verify_config(self):
        patterns = {
            "ip": r"^((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$",
            "port": r"^[0-9]+$",
        }
        assertions = [
            (self.parser["main"]["ip"] is not "", "IP address is not set in config file."),
            (re.match(patterns["ip"], self.parser["main"]["ip"]), "Invalid IP address."),
            (re.match(patterns["port"], self.parser["main"]["command_port"]), "Invalid command port."),
            (re.match(patterns["port"], self.parser["main"]["voice_port"]), "Invalid voice port."),
            (os.path.exists(self.parser["ssl"]["key_file"]) if self.parser["ssl"]["key_file"] is not "" else True, "Cannot find SSL key file."),
            (os.path.exists(self.parser["ssl"]["cert_file"]) if self.parser["ssl"]["cert_file"] is not "" else True, "Cannot find SSL key file."),
        ]   
        abort = False
        for test in assertions:
            if not test[0]:
                abort = True
                print("CONFIGURE ERROR: " + test[1])
        if abort:
            sys.exit()

print("Startup")

print()
print("Reading config file")
config = ServerConfig("config.ini")
host = config.parser["main"]["ip"]
voice_port = int(config.parser["main"]["voice_port"])
command_port = int(config.parser["main"]["command_port"])
key_file = config.parser["ssl"]["key_file"]
cert_file = config.parser["ssl"]["cert_file"]

try:
    print("")
    print("Starting voice server")
    # start voice server
    voice_server = ThreadedVoiceServer((host, voice_port), UDPVoiceHandler)
    voice_server_thread = threading.Thread(target=voice_server.serve_forever)
    voice_server_thread.daemon = True
    voice_server_thread.start()

    print("Starting command server")
    # start the command server
    command_server = ThreadedCommandServer((host, command_port), TCPCommandHandler, key_file=key_file, cert_file=cert_file)
    command_server_thread = threading.Thread(target=command_server.serve_forever)
    command_server_thread.daemon = True
    command_server_thread.start()

    # give each server a reference of the other
    voice_server.attach_command_server(command_server)
    command_server.attach_voice_server(voice_server)

    print("")
    print("Serving")

    try:
        voice_server_thread.join()
        command_server_thread.join()
    except KeyboardInterrupt:
        sys.exit()

except:
    traceback.print_exc()
    command_server.server_close()
    voice_server.server_close()
    
