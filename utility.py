#!/usr/bin/env python
# coding=utf-8

import math
import socket
import struct
from random import randint


def generate_id(length):
    id = ""
    for i in range(length):
        id += chr(randint(0, 255))

    return id


def decode_nodes(message):
    nodes = []
    for i in range(0, len(message), 26):
        node_id = message[i : i + 20]
        ip = socket.inet_ntoa(struct.pack('i', socket.htonl(message[i + 20 : i + 24])))
        port = struct.unpack("H", message[i + 24: i + 26])[0]
        nodes.append((node_id, (ip, port)))

    return nodes


def encode_nodes(nodes):
    message = ""
    for node in nodes:
        message += node[0]
        message += socket.ntohl(struct.unpack("I", socket.inet_aton(node[1][0]))[0])
        message += struct.pack("H", node[1][1])
    
    return message


def xor(node_one_id, node_two_id):
    result = 0
    
    length = len(node_one_id)
    for i in range(length):
        result = (result << 8) + ord(node_one_id[i]) ^ ord(node_two_id[i])
    return result


def get_rtable_index(distance):
    return int(math.floor(math.log(distance, 2.0)))


