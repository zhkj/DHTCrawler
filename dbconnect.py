#!/usr/bin/env python
# coding=utf-8

import utility
import datetime
import pymongo
from config import HOST, PORT


def save_info_hashs(info_hashs):
    client = pymongo.MongoClient(HOST, PORT)
    database = client.dht_crawler
    info_hashs_collection = database.info_hashs
    
    for info_hash in info_hashs:
        info_hash_record = {
            "value": utility.from_byte_to_hex(info_hash),
            "date" : datetime.datetime.utcnow() 
        }
        info_hashs_collection.insert(info_hash_record)
    
    client.close()


def get_info_hashs():
    client = pymongo.MongoClient(HOST, PORT)
    database = client.dht_crawler
    info_hashs_collection = database.info_hashs
   
    info_hashs = []
    for info_hash_record in info_hashs_collection.find():
        info_hash_record["value"] = utility.from_hex_to_byte(info_hash_record["value"])
        info_hashs.append(info_hash_record) 

    client.close()

    return info_hashs


def save_rtable(node_id, rtable, addr):
    client = pymongo.MongoClient(HOST, PORT)
    database = client.dht_crawler
    rtables_collection = database.rtables

    node_id = utility.from_byte_to_hex(node_id)
    for bucket in rtable:
        for node in bucket:
            node[0] = utility.from_byte_to_hex(node[0])

    if rtables_collection.find_one({"node_id" : node_id}):
        rtables_collection.update({"node_id" : node_id}, {"$set" : {"rtable" : rtable}})
    else:
        rtable_record = {
            "node_id" : node_id,
            "addr" : list(addr),
            "rtable" : rtable
        }
        rtables_collection.insert(rtable_record)
    
    for bucket in rtable:
        for node in bucket:
            node[0] = utility.from_hex_to_byte(node[0])

    client.close()


def get_rtables():
    client = pymongo.MongoClient(HOST, PORT)
    database = client.dht_crawler
    rtables_collection = database.rtables
    
    rtables = list(rtables_collection.find())
    
    for rtable in rtables:
        rtable["node_id"] = utility.from_hex_to_byte(rtable["node_id"])
        for bucket in rtable["rtable"]:
            for node in bucket:
                node[0] = utility.from_hex_to_byte(node[0])

    client.close()

    return rtables


def save_bt_info(bt_info):
    client = pymongo.MongoClient(HOST, PORT)
    database = client.dht_crawler
    bt_infos_collection = database.bt_infos
    
    try:
        bt_infos_collection.insert(bt_info)
    except:
        print "Cannot insert bt_info into database"

    client.close()


def get_bt_infos():
    client = pymongo.MongoClient(HOST, PORT)
    database = client.dht_crawler
    bt_infos_collection = database.bt_infos

    return list(bt_infos_collection.find())
