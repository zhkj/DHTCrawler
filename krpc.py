#!/usr/bin/env python
# coding=utf-8

import time
import random
import socket
import utility
import threading
from config import INITIAL_NODES
from bencode import bencode, bdecode
from db import save_info_hashs, save_rtable

K = 8
TABLE_NUM = 160
TOKEN_LENGTH = 5
NODE_ID_LENGTH = 20
TRANS_ID_LENGTH = 2

class KRPC(object):
    def __init__(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            self.socket.bind('localhost', 0)
        except:
            print "Cannot bind the port!"


class DHTProtocol(KRPC):
    def __init__(self, node_id, rtable):
        KRPC.__init__(self)
        self.node_id = node_id
        self.rtable = rtable
        self.info_hashs = []

        self.rtable_mutex = threading.Lock() 

    
    def get_k_closest_nodes(self, id):
        rtable_index = utility.get_rtable_index(utility.xor(self.node_id, id))
        
        k_closest_nodes = []
        
        index = rtable_index
        while index >= 0 and len(k_closest_nodes) < K:
            for node in self.rtable[index]:
                if len(k_closest_nodes) < K:
                    k_closest_nodes.append(node)
                else:
                    break
            index -= 1
        index = rtable_index + 1
        while index < 160  and len(k_closest_nodes) < K:
            for node in self.rtable[index]:
                if len(k_closest_nodes) < K:
                    k_closest_nodes.append(node)
                else:
                    break
            index += 1
        
        return k_closest_nodes

    
    def add_nodes_to_rtable(self, nodes):
        if self.rtable_mutex.acquire():
            for node in nodes:
                rtable_index = utility.get_rtable_index(utility.xor(node[0], self.node_id))
                if len(self.rtable[rtable_index]) < K:
                    self.rtable[rtable_index].append(node)
                else:
                    if random.randint(0, 1):
                        index = random.randint(0, K - 1)
                        self.rtable[rtable_index][index] = node
            self.rtable.mutex.release()



    def handle_pi_qdata(self, data, addr):
        response = {}
        response["t"] = data["t"]
        response["y"] = "r"
        response["r"] = {}
        response["r"]["id"] = self.node_id
        response = bencode(response)

        self.socket.sendto(response, addr)

        
    def handle_fn_qdata(self, data, addr):
        target_node_id = data["a"]["target"]
        rtable_index = utility.get_rtable_index(utility.xor(self.node_id, target_node_id))
        
        response_nodes = []
        for node in self.rtable[rtable_index]:
            if node[0] == target_node_id:
                response_nodes.append(node)
                break

        if len(response_nodes) == 0:
            response_nodes = self.get_k_closest_nodes(target_node_id)
        node_message = utility.encode_nodes(response_nodes)

        response = {}
        response["t"] = data["t"]
        response["y"] = "r"
        response["r"] = {}
        response["r"]["id"] = self.node_id
        response["r"]["nodes"] = node_message
        response = bencode(response)

        self.socket.sendto(response, addr)

    
    def handle_gp_qdata(self, data, addr):
        response = {}
        response["t"] = data["t"]
        response["y"] = "r"
        response["r"] = {}
        response["r"]["id"] = self.node_id
        response["r"]["token"] = utility.generate_id(TOKEN_LENGTH)
        response["r"]["nodes"] = self.get_k_closest_nodes(data["a"]["info_hash"])
        response = bencode(response)

        self.socket.sendto(response, addr)
    
    
    def handle_ap_qdata(self, data, addr):
        info_hash = data["a"]["info_hash"]
        self.info_hashs.append(info_hash)
        if len(self.info_hashs) >= 100:
            save_info_hashs(self.info_hashs)
            self.info_hashs = []

        response = {}
        response["t"] = data["t"]
        response["y"] = "r"
        response["r"] = {}
        response["r"]["id"] = self.node_id
        response = bencode(response)

        self.socket.sendto(response, addr)
    
    
    def handle_pi_rdata(self, data, addr):
        pass
    

    def handle_fn_rdata(self, data, addr):
        node_message = data["r"]["nodes"]
        nodes = utility.decode_nodes(node_message)
        self.add_nodes_to_rtable(nodes)
    

    def handle_gp_rdata(self, data, addr):
        pass
    

    def handle_ap_rdata(self, data, addr):
        pass
    

    def handle(self, data, addr):
        data = bdecode(data)
        
        query_handle_function = {
            "ping" : self.handle_pi_qdata,
            "find_node" : self.handle_fn_qdata,
            "get_peers" : self.handle_gp_qdata,
            "announce_peer" : self.handle_ap_qdata
        }
    
        type = data["y"]
        if type == "q":
            query_handle_function[data["q"]](data, addr)
        elif type == "r":
            if data["r"].has_key("token"):
                self.handle_gp_rdata(data, addr)
            elif data["r"].has_key("nodes"):
                self.handle_fn_rdata(data, addr)
    

    def server(self):
        while True:
            data, addr = self.socket.recvfrom(65536)
            self.handle(data, addr)        
    

    def client(self):
        if len(self.rtable) == 0:
            nodes = []
            self.rtable = [[] for i in range(TABLE_NUM)]
            for inital_node in INITIAL_NODES:
                nodes.append(utility.generate_id(NODE_ID_LENGTH), inital_node)
            self.add_nodes_to_rtable(nodes)

        while True:
            self.find_node()
            self.save_rtable()
            time.sleep(8)

    
    def find_node(self):
        target_node_id = utility.generate_id(NODE_ID_LENGTH)
            
        query = {}
        query["t"] = utility.generate_id(TRANS_ID_LENGTH)
        query["y"] = "q"
        query["q"] = "find_node"
        query["a"] = {}
        query["a"]["id"] = self.node_id
        query["a"]["target"] = target_node_id
        query = bencode(query)

        if self.rtable_mutex.acquire():
            for bucket in self.rtable:
                for node in bucket:
                    self.socket.sendto(query, node[1])
            self.rtable.mutex.release()


    def save_rtable(self):
        if self.rtable_mutex.acquire():
            save_rtable(self.node_id, self.rtable)
            self.rtable.mutex.release()

    
    def start(self):
        server_thread = threading.Thread(target = self.server)
        client_thread = threading.Thread(target = self.client)
        
        server_thread.start()
        client_thread.start()
        
