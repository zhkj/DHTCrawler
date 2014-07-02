#!/usr/bin/env python
# coding=utf-8

import urllib2
from dbconnect import save_bt_info, get_hash_infos
from bencode import bdecode

def get_btih(info_hash_record):
    str = "0123456789ABCDEF"
    info_hash = info_hash_record["value"]
    
    btih = ""
    for i in range(len(info_hash)):
        btih += str[(ord(info_hash[i]) >> 4) & 15]
        btih += str[ord(info_hash[i]) & 15]

    return btih


def get_request_url(btih):
    basic_url = "http://bt.box.n0808.com"
    refer_url = basic_url + "/" + btih[0:2] + "/" + btih[-2:] + "/"
    full_url = refer_url+ btih + ".torrent"
    
    return full_url, refer_url


def get_and_save_bt_info(info_hash_record):
    btih = get_btih(info_hash_record)
    refer_url, full_url = get_request_url(btih)
    
    headers = {
        "Referer" : refer_url,
        "User-Agent" : 'Mozilla/5.0 (Windows; U; Windows NT 6.1; en-US; rv:1.9.1.6) Gecko/20091201 Firefox/3.5.6'
    }

    request = urllib2.Request(full_url, headers = headers)
    
    try:
        content = urllib2.urlopen(request, timeout = 10).read()
    except:
        print "Cannot get the bt file for " + btih
        return

    content = bdecode(content)
    
    bt_info = {}
    bt_info["info_hash"] = info_hash_record["value"]
    bt_info["magnet"] = "magnet:?xt=urn:btih:" + btih
    bt_info["date"] = info_hash_record["date"]

    info = content["info"]
    bt_info["name"] = info["name"]

    if info.has_key("files"):
        bt_info["files"] = []
        files = info["files"]
        for file in files:
            bt_info["files"].append([file["path"], file["length"]])
    else:
        bt_info["length"] = info["length"]

    save_bt_info(bt_info)


def main():
    hash_infos = get_hash_infos()
    for hash_info_record in hash_infos:
        get_and_save_bt_info(hash_info_record)


if __name__ == '__main__':
    main()
    
