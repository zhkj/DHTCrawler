#!/usr/bin/env python
# coding=utf-8

import config
from dbconnect import get_rtables
from node import Node

def main():
    node_num = config.NODE_NUM
    nodes = [None for i in range(node_num)]

    rtables = get_rtables()
    for i in range(min(node_num, len(rtables))):
        nodes[i] = Node(rtables[i]["node_id"], rtables[i]["rtable"])
        nodes[i].protocol.start()
    for i in range(len(rtables), node_num):
        nodes[i] = Node()
        nodes[i].protocol.start()


if __name__ == '__main__':
    main()

