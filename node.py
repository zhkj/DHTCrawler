#!/usr/bin/env python
# coding=utf-8

from krpc import DHTProtocol
from utility import generate_node_id


class Node(object):
    def __init__(self, node_id = None, rtable = [], addr = None):
        if node_id == None:
            self.node_id = generate_node_id()
        else:
            self.node_id = node_id
        
        self.rtable = rtable
        self.protocol = DHTProtocol(self.node_id, self.rtable, addr)    

