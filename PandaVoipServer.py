import socketserver
import threading
import traceback
import sys
import time


class VoiceClient(object):
    def __init__(self, client_id, addr):
        self.client_id = client_id
        self.addr = addr

    def am_i(self, client_id, addr):
        return self.client_id == client_id and self.addr == addr

    def get_cid(self):
        return self.client_id


class UDPVoiceHandler(socketserver.BaseRequestHandler):
    def handle(self):
        data = self.request[0]
        socket = self.request[1]
        addr = self.client_address
        client_id = int.from_bytes(data[0:4], byteorder='little')
        if not self.server.check_allowed_client(client_id):
            return
        self.server.add_client_if_new(client_id, addr)
        for client in self.server.connections:
            if not client.am_i(client_id, addr):
                if (client.client_id in self.server.allowed_connections):
                    self.server.socket.sendto(data, client.addr)


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


class TCPCommandHandler(socketserver.BaseRequestHandler):
    def handle(self):
        while True:
            try:
                data = self.request.recv(1024).strip()
            except ConnectionResetError:
                self.server.disconnect(client_id)
                return
            client_id = int.from_bytes(data[0:4], byteorder='little')
            message_length = int.from_bytes(data[4:8], byteorder='little')
            self.server.add_client_if_new(client_id, self.request)
            data = data[8:8+message_length].decode('ascii')
            if len(data) == 0:
                self.request.sendall("ok".encode())
                self.server.update_voice_clients()
            elif data == "voice connect":
                self.server.voice_connect(client_id)
                self.request.sendall("voice connect ok".encode())

                self.server.update_voice_clients()
            elif data == "voice disconnect":
                self.server.voice_disconnect(client_id)
                self.request.sendall("voice disconnect ok".encode())

                self.server.update_voice_clients()
            elif data[0:5] == "text ":
                self.server.text_message(client_id, data[5:])
            else:
                print(data)
                self.request.sendall("not ok".encode())


class ThreadedCommandServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    def __init__(self, *args, **kwargs):
        super(ThreadedCommandServer, self).__init__(*args, **kwargs)
        self.allow_reuse_address = True
        self.connections = []
        self.voice_server = None

    def update_voice_clients(self):
        users_str = "".join([str(c).zfill(8) for c in self.voice_server.allowed_connections])
        for client in self.connections:
            client.socket.sendall(("users " + users_str).encode())

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
                print()
                break
        self.voice_disconnect(client_id)

    def text_message(self, client_id, message):
        for client in self.connections:
            client.socket.sendall(("text " + str(client_id).zfill(8) + message).encode())

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

HOST = '127.0.0.1'
voice_port = 50038
command_port = 50039

voice_server = ThreadedVoiceServer((HOST, voice_port), UDPVoiceHandler)
voice_server_thread = threading.Thread(target=voice_server.serve_forever)
voice_server_thread.daemon = True
voice_server_thread.start()

command_server = ThreadedCommandServer((HOST, command_port), TCPCommandHandler)
command_server_thread = threading.Thread(target=command_server.serve_forever)
command_server_thread.daemon = True
command_server_thread.start()

voice_server.attach_command_server(command_server)
command_server.attach_voice_server(voice_server)

print("running")

while True:
    try:
        voice_server_thread.join()
        command_server_thread.join()
    except:
        command_server.server_close()
        voice_server.server_close()
        traceback.print_exc()
