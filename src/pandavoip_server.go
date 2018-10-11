package main

import (
    "bufio"
    "strings"
    "log"
    "net"
    "io"
)

func handleConnection(c net.Conn){
    log.Printf("Serving %s\n", c.RemoteAddr().String())
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

    c.Close()
}

func startServer() {
    port := ":50039"

    log.Printf("Starting server on %v%v\n", GetOutboundIP(), port);

    listener, err := net.Listen("tcp4", port);
    if err != nil {
		log.Fatal(err)
    }
    defer listener.Close()

    for {
        c, err := listener.Accept()
        if err != nil {
            log.Fatal(err)
        }
        go handleConnection(c)
    }
}

func GetOutboundIP() net.IP {
    conn, err := net.Dial("udp", "8.8.8.8:80")
    if err != nil {
        log.Fatal(err)
    }
    defer conn.Close()

    localAddr := conn.LocalAddr().(*net.UDPAddr)

    return localAddr.IP
}

func main() {
    startServer();
}
