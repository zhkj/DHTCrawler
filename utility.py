#!/usr/bin/env python
# coding=utf-8

import math
import socket
import struct
from hashlib import sha1
from random import randint


def generate_id(length):
    id = ""
    for i in range(length):
        id += chr(randint(0, 255))

    return id


def generate_node_id():
    hash = sha1()
    hash.update(generate_id(20))
    return hash.digest()


def from_hex_to_byte(hex_string):
    byte_string = ""

    transfer = "0123456789abcdef"
    untransfer = {}
    for i in range(16):
        untransfer[transfer[i]] = i

    for i in range(0, len(hex_string), 2):
        byte_string += chr((untransfer[hex_string[i]] << 4) + untransfer[hex_string[i + 1]])

    return byte_string
    


def from_byte_to_hex(byte_string):
    transfer = "0123456789abcdef"

    hex_string = ""
    for s in byte_string:
        hex_string += transfer[(ord(s) >> 4) & 15]
        hex_string += transfer[ord(s) & 15]

    return hex_string



def decode_nodes(message):
    nodes = []
    for i in range(0, len(message), 26):
        node_id = message[i : i + 20]
        ip = socket.inet_ntoa(message[i + 20 : i + 24])                 #from network order to IP address
        port = struct.unpack("!H", message[i + 24: i + 26])[0]          #"!" means to read by network order
        nodes.append([node_id, (ip, port)])

    return nodes


def encode_nodes(nodes):
    message = ""
    for node in nodes:
        message += node[0]
        message += socket.inet_aton(node[1][0])                         #from IP address to network order
        message += struct.pack("!H", node[1][1])
    
    return message


def xor(node_one_id, node_two_id):
    result = 0
    
    length = len(node_one_id)
    for i in range(length):
        result = (result << 8) + (ord(node_one_id[i]) ^ ord(node_two_id[i]))
    return result


def get_rtable_index(distance):
    return int(math.floor(math.log(distance, 2.0)))


