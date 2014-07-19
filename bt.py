#!/usr/bin/env python
# coding=utf-8

import utility
import urllib2
import StringIO, gzip
from dbconnect import save_bt_info, get_info_hashs, get_gp_info_hashs
from bencode import bdecode

def get_btih(info_hash_record):
    str = "0123456789ABCDEF"
    info_hash = info_hash_record["value"]
    
    btih = ""
    for i in range(len(info_hash)):
        btih += str[(ord(info_hash[i]) >> 4) & 15]
        btih += str[ord(info_hash[i]) & 15]

    return btih


def analyse_bt_file_with_torcache(btih):
    basic_url = "http://torcache.net/torrent"
    request_url = basic_url + "/" + btih + ".torrent"

    header_options = {
        "Accept-Encoding" : "gzip,deflate,sdch"
    }
    content = get_bt_file(request_url, header_options)
    bt_info = get_file_info(content)

    return bt_info


def analyse_bt_file_with_btbox(btih):
    basic_url = "http://bt.box.n0808.com"
    refer_url = basic_url + "/" + btih[0:2] + "/" + btih[-2:] + "/"
    request_url = refer_url+ btih + ".torrent"

    header_options = {
        "Referer" : refer_url
    }
    
    content = get_bt_file(request_url, header_options)
    bt_info = get_file_info(content)

    return bt_info


def get_file_info(content):
    if content:
        try:
            content = bdecode(content)
        except:
            return {}

        bt_info = {}
        info = content["info"]
        bt_info["name"] = info["name"]

        if info.has_key("files"):
            bt_info["files"] = []
            files = info["files"]
            for file in files:
                bt_info["files"].append([file["path"][0], file["length"]])
        else:
            bt_info["length"] = info["length"]
    else:
        return {}


def decode_gzip(gzip_data):
    compressed_stream = StringIO.StringIO(gzip_data)
    gziper = gzip.GzipFile(fileobj = compressed_stream)
    data = gziper.read()

    return data


def get_bt_file(request_url, header_options = {}):
    
    headers = {
        "User-Agent" : 'Mozilla/5.0 (Windows; U; Windows NT 6.1; en-US; rv:1.9.1.6) Gecko/20091201 Firefox/3.5.6'
    }
    for option in header_options.keys():
        headers[option] = header_options[option]

    request = urllib2.urlopen(request_url, headers = headers)
    

    try:
        response = urllib2.urlopen(request, timeout = 10)
        content = response.read()
        if response.info().get('Content-Encoding') == 'gzip':
            content = decode_gzip(content)
    except:
        content = ""

    return content


def get_and_save_bt_info(info_hash_record):
    btih = get_btih(info_hash_record)
  
    methods = [analyse_bt_file_with_torcache, analyse_bt_file_with_btbox]

    for method in methods:
        bt_info = method(btih)
        if bt_info:
            bt_info["info_hash"] = utility.from_byte_to_hex(info_hash_record["value"])
            bt_info["magnet"] = "magnet:?xt=urn:btih:" + btih
            bt_info["date"] = info_hash_record["date"]
            save_bt_info(bt_info)
            
            break


def main():
    """
    info_hashs = list(get_info_hashs())
    print len(info_hashs)
    get_peer_info_hashs = list(get_gp_info_hashs())
    print len(get_peer_info_hashs)
    """    
    for info_hash_record in info_hashs:
        get_and_save_bt_info(info_hash_record)

if __name__ == '__main__':
    main()
    
