#!/usr/bin/env python3
# https://gist.github.com/idkiller/b9a8b0b83a69c3cefc5a3369cc655f98
# https://gist.github.com/friek/6c10535b2e43f0e0867ce21b0679a337

import socket
import sys
from time import gmtime, strftime
import struct

def analDNSPacket(packet):
    now = strftime("%Y-%M-%d %H:%M:%S", gmtime())
    recvHeader = struct.unpack_from('!HHHHHH', packet[:12])
    recvData = packet[12:].split(b'\x00', 1)
    flag_QnA = recvHeader[1] & 0b1000000000000000
    queryType, queryClass = struct.unpack('!HH', recvData[1][:4])

    rData = packet[12:]
    print('[*] Time : ' + now)
    print('[+] Transaction ID : ' + str(hex(recvHeader[0])))
    print('[+] Flags : ' + str(hex(recvHeader[1])))
    print('[+] Number of queries : ' + str(hex(recvHeader[2])))
    print('[+] Number of authoritative : ' + str(hex(recvHeader[3])))
    print('[+] Number of additional record : ' + str(hex(recvHeader[4])))
    print('[+] Query Type : ' + str(hex(queryType))) + '('+str(queryType)+')'
    print('[+] Query Class : ' + str(hex(queryClass)))

def main(argv):
    multicast_group = argv[1]
    multicast_port = int(argv[2])
    interface_ip = argv[3]

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 32)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', multicast_port))
    sock.setsockopt(socket.SOL_IP, socket.IP_ADD_MEMBERSHIP,
                    socket.inet_aton(multicast_group) + socket.inet_aton(interface_ip))

    while True:
        #received = sock.recv(1500)
        packet, address = sock.recvfrom(65565)
        #print('Received packet of {0} bytes'.format(len(received)))
        now = strftime("%m/%d/%Y, %H:%M:%S", gmtime())
        if b"esp32-" in packet:
            print('[*] Time : ' + now)
            print(packet)
        #analDNSPacket(packet[28:])
        #analDNSPacket(received)



if __name__ == '__main__':
    if len(sys.argv) != 4:
        print("Usage: {0} <group address> <port> <interface ip>".format(sys.argv[0]))
        sys.exit(1)
    main(sys.argv)
