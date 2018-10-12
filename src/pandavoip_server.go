package main

import (
	"bufio"
	"io"
	"log"
	"net"
	"strings"
)

type CommandClient struct {
	username string
	conn     net.Conn
}

type CommandServer struct {
	serverName string
	users      []CommandClient
}

func (server *CommandServer) clientDisconnect(user CommandClient) {
	for i, u := range server.users {
		if u == user {
			server.users = append(server.users[:i], server.users[i+1:]...)
			break
		}
	}
}

func (server *CommandServer) getUsernames() []string {
	var names []string

	for _, user := range server.users {
		names = append(names, user.username)
	}

	return names
}

func (server *CommandServer) handleConnection(c net.Conn) {
	log.Printf("Serving %s\n", c.RemoteAddr().String())

	client := CommandClient{c.RemoteAddr().String(), c}

	server.users = append(server.users, client)

	log.Printf("Users: %v\n", server.getUsernames())

	for {
		netData, err := bufio.NewReader(c).ReadString('\n')
		if err == io.EOF {
			break
		} else if err != nil {
			log.Fatal(err)
		}

		temp := strings.TrimSpace(string(netData))
		if temp == "STOP" {
			break
		}

		result := "ok\n"
		c.Write([]byte(string(result)))
	}
	log.Printf("Disconnected %s\n", c.RemoteAddr().String())

	server.clientDisconnect(client)
	log.Printf("Users: %v\n", server.getUsernames())

	c.Close()
}

func startServer() {
	server := CommandServer{"ritlew.com", []CommandClient{}}
	port := ":50039"

	log.Printf("Starting server on %v%v\n", GetOutboundIP(), port)

	listener, err := net.Listen("tcp4", port)
	if err != nil {
		log.Fatal(err)
	}
	defer listener.Close()

	for {
		c, err := listener.Accept()
		if err != nil {
			log.Fatal(err)
		}
		go server.handleConnection(c)
	}
}

func GetOutboundIP() net.IP {
	conn, err := net.Dial("udp", "8.8.8.8:80")
	if err != nil {
		log.Fatal(err)
	}
	defer conn.Close()
	defer conn.Close()

	localAddr := conn.LocalAddr().(*net.UDPAddr)

	return localAddr.IP
}

func main() {
	startServer()
}
