package main

import (
	"bufio"
	"io"
	"log"
	"net"
	"strconv"
	"strings"
)

func GetOutboundIP() net.IP {
	conn, err := net.Dial("udp", "8.8.8.8:80")
	if err != nil {
		log.Fatal(err)
	}
	defer conn.Close()

	localAddr := conn.LocalAddr().(*net.UDPAddr)

	return localAddr.IP
}

type CommandClient struct {
	username string
	conn     net.Conn
}

type CommandServer struct {
	serverName string
	ip         net.IP
	port       int
	users      []CommandClient
}

func (server *CommandServer) startServer() {
	log.Printf("Starting server on %v:%v\n", server.ip.String(), server.port)

	listener, err := net.Listen("tcp4", ":"+strconv.Itoa(server.port))
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

func main() {
	server := CommandServer{
		serverName: "ritlew.com",
		ip:         GetOutboundIP(),
		port:       50039,
	}
	server.startServer()
}
