#!/usr/bin/env python
# coding=utf-8

from krpc import DHTProtocol
from utility import generate_id


NODE_ID_LENGTH = 20

class Node(object):
    def __init__(self, node_id = None, rtable = []):
        if node_id == None:
            self.node_id = generate_id(NODE_ID_LENGTH)
        else:
            self.node_id = node_id
        
        self.rtable = rtable
        self.protocol = DHTProtocol(self.node_id, self.rtable)    

