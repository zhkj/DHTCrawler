#!/usr/bin/env python
# coding=utf-8

import datetime
import pymongo
from config import HOST, PORT


def save_info_hashs(info_hashs):
    client = pymongo.MongoClient(HOST, PORT)
    database = client.dht_crawler
    info_hashs_collection = database.info_hashs
    
    for info_hash in info_hashs:
        info_hash_record = {
            "value": info_hash,
            "date" : datetime.datetime.utcnow() 
        }
        info_hashs_collection.insert(info_hash_record)
    
    client.close()


def get_info_hashs():
    client = pymongo.MongoClient(HOST, PORT)
    database = client.dht_crawler
    info_hashs_collection = database.info_hashs
    
    info_hashs = []
    for record in list(info_hashs_collection.find()):
        info_hashs.append(record)    
    
    client.close()

    return info_hashs


def save_rtable(node_id, rtable):
    client = pymongo.MongoClient(HOST, PORT)
    database = client.dht_crawler
    rtables_collection = database.rtables
    
    if rtables_collection.find_one({"node_id" : node_id}):
        rtables_collection.update({"node_id" : node_id}, {"$set" : {"rtable" : rtable}})
    else:
        rtable_record = {
            "node_id" : node_id,
            "rtable" : rtable
        }
        rtables_collection.insert(rtable_record)

    client.close()


def get_rtables():
    client = pymongo.MongoClient(HOST, PORT)
    database = client.dht_crawler
    rtables_collection = database.rtables
    
    rtables = []
    for record in list(rtables_collection.find()):
        rtables.append(record)

    client.close()

    return rtables_collection


def save_bt_info(bt_info):
    client = pymongo.MongoClient(HOST, PORT)
    database = client.dht_crawler
    bt_infos_collection = database.bt_infos
    
    bt_infos_collection.insert(bt_info)

    client.close()


def get_bt_infos():
    client = pymongo.MongoClient(HOST, PORT)
    database = client.dht_crawler
    bt_infos_collection = database.bt_infos

    return list(bt_infos_collection.find())
