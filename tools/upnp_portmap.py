#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UPnP 自动端口映射工具（免登录路由器管理页）
============================================
通过 UPnP IGD 协议自动向路由器/光猫申请端口映射，
无需管理员密码。仅标准库（socket + urllib + xml）。

用法：
    python upnp_portmap.py                # 只探测：列出当前 UPnP 映射
    python upnp_portmap.py 8088 tcp       # 添加一条 TCP 8088 映射
    python upnp_portmap.py 7654 udp       # 添加一条 UDP 7654 映射
    python upnp_portmap.py list           # 列出已存在的映射
    python upnp_portmap.py del 8088 tcp   # 删除映射

依赖：路由/光猫需开启 UPnP（默认多数开启；关闭时需进管理页开启或致电客服）。
"""

import socket
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900
MY_IP = "192.168.1.4"  # 服务器内网 IP（如变化请修改）


def ssdp_discover():
    """发现 InternetGatewayDevice，返回 LOCATION 列表"""
    msg = ("M-SEARCH * HTTP/1.1\r\n"
           "HOST: %s:%d\r\n"
           'MAN: "ssdp:discover"\r\n'
           "MX: 3\r\n"
           "ST: urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n"
           "\r\n" % (SSDP_ADDR, SSDP_PORT)).encode("utf-8")
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(6)
    s.sendto(msg, (SSDP_ADDR, SSDP_PORT))
    locations = []
    deadline = time.time() + 6
    try:
        while time.time() < deadline:
            try:
                data, _ = s.recvfrom(4096)
            except socket.timeout:
                break
            text = data.decode("utf-8", "ignore")
            loc = None
            for line in text.split("\r\n"):
                if line.lower().startswith("location:"):
                    loc = line.split(":", 1)[1].strip()
                    break
            if loc and loc not in locations:
                locations.append(loc)
    finally:
        s.close()
    return locations


NS = {
    "s": "http://schemas.xmlsoap.org/soap/envelope/",
    "u": "urn:schemas-upnp-org:service:WANIPConnection:1",
    "u2": "urn:schemas-upnp-org:service:WANPPPConnection:1",
}


def get_service(location):
    """从描述文件解析 WAN*Connection 服务的 controlURL 与 serviceType"""
    req = urllib.request.Request(location, headers={"User-Agent": "n2n-upnp/1.0"})
    desc = urllib.request.urlopen(req, timeout=8).read()
    root = ET.fromstring(desc)
    # 忽略命名空间查找任意 service
    for svc in root.iter():
        if svc.tag.endswith("service"):
            st = svc.findtext("{urn:schemas-upnp-org:metadata-1-0/upnp/}serviceType")
            cu = svc.findtext("{urn:schemas-upnp-org:metadata-1-0/upnp/}controlURL")
            if st and cu and ("WANIPConnection" in st or "WANPPPConnection" in st):
                if not cu.startswith("http"):
                    cu = location.rsplit("/", 1)[0] + cu
                return st, cu
    return None, None


def soap(control_url, service_type, action, args):
    """发送 SOAP 动作"""
    xmlns = service_type
    body = "<u:%s xmlns:u=\"%s\">" % (action, xmlns)
    for k, v in args.items():
        body += "<%s>%s</%s>" % (k, v, k)
    body += "</u:%s>" % action
    payload = (
        "<?xml version=\"1.0\"?>\n"
        "<s:Envelope xmlns:s=\"http://schemas.xmlsoap.org/soap/envelope/\" "
        "s:encodingStyle=\"http://schemas.xmlsoap.org/soap/encoding/\">"
        "<s:Body>%s</s:Body></s:Envelope>" % body
    ).encode("utf-8")
    req = urllib.request.Request(
        control_url, data=payload,
        headers={
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPAction": '"%s#%s"' % (xmlns, action),
            "User-Agent": "n2n-upnp/1.0",
        })
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.read()
    except urllib.error.HTTPError as e:
        return e.read()


def find_igd():
    locs = ssdp_discover()
    if not locs:
        print("[x] 未发现 UPnP 网关设备")
        print("    可能原因：路由器/光猫未开启 UPnP。")
        print("    处理：致电宽带客服要求远程开启 UPnP，或告知管理密码。")
        return None, None
    for loc in locs:
        try:
            st, cu = get_service(loc)
            if st and cu:
                print("[+] 发现网关: %s" % loc)
                print("    服务: %s" % st)
                return st, cu
        except Exception as e:
            print("[-] 解析失败 %s: %s" % (loc, e))
    print("[x] 网关描述中未找到端口映射服务")
    return None, None


def add_port(st, cu, ext, proto, internal_ip=MY_IP, internal_port=None, desc="n2n"):
    internal_port = internal_port or ext
    resp = soap(st, cu, "AddPortMapping", {
        "NewRemoteHost": "",
        "NewExternalPort": str(ext),
        "NewProtocol": proto.upper(),
        "NewInternalPort": str(internal_port),
        "NewInternalClient": internal_ip,
        "NewEnabled": "1",
        "NewPortMappingDescription": desc,
        "NewLeaseDuration": "0",
    })
    text = resp.decode("utf-8", "ignore")
    if "errorCode" in text or "UPnPError" in text:
        err = text.split("<errorCode>")[1].split("</errorCode>")[0] if "<errorCode>" in text else "?"
        print("[x] 添加失败 errorCode=%s" % err)
        print("    常见：402=参数错, 501=设备不支持, 725=仅在租约期允许, 718=冲突(已存在)")
        return False
    print("[+] 已添加映射: %s/%s -> %s:%s (%s)" % (ext, proto.upper(), internal_ip, internal_port, desc))
    return True


def del_port(st, cu, ext, proto):
    resp = soap(st, cu, "DeletePortMapping", {
        "NewRemoteHost": "",
        "NewExternalPort": str(ext),
        "NewProtocol": proto.upper(),
    })
    text = resp.decode("utf-8", "ignore")
    if "errorCode" in text:
        err = text.split("<errorCode>")[1].split("</errorCode>")[0] if "<errorCode>" in text else "?"
        print("[x] 删除失败 errorCode=%s" % err)
        return False
    print("[+] 已删除映射: %s/%s" % (ext, proto.upper()))
    return True


def list_ports(st, cu):
    resp = soap(st, cu, "GetGenericPortMappingEntry", {"NewPortMappingIndex": "0"})
    text = resp.decode("utf-8", "ignore")
    if "errorCode" in text:
        print("（无现有映射或设备不支持列举）")
        return
    import re
    entries = []
    idx = 0
    while True:
        resp = soap(st, cu, "GetGenericPortMappingEntry", {"NewPortMappingIndex": str(idx)})
        text = resp.decode("utf-8", "ignore")
        if "errorCode" in text or "UPnPError" in text:
            break
        proto = re.search(r"<NewProtocol>(\w+)</NewProtocol>", text)
        ext = re.search(r"<NewExternalPort>(\d+)</NewExternalPort>", text)
        intc = re.search(r"<NewInternalClient>([\d.]+)</NewInternalClient>", text)
        intp = re.search(r"<NewInternalPort>(\d+)</NewInternalPort>", text)
        dsc = re.search(r"<NewPortMappingDescription>([^<]*)</NewPortMappingDescription>", text)
        if ext:
            entries.append("%s/%s -> %s:%s %s" % (
                ext.group(1), (proto.group(1) if proto else "?"),
                (intc.group(1) if intc else "?"), (intp.group(1) if intp else "?"),
                (dsc.group(1) if dsc else "")))
        idx += 1
    if entries:
        for e in entries:
            print("  " + e)
    else:
        print("（无现有映射）")


def main():
    if len(sys.argv) < 2:
        st, cu = find_igd()
        if st:
            print("== 现有 UPnP 映射 ==")
            list_ports(st, cu)
        return
    st, cu = find_igd()
    if not st:
        return
    cmd = sys.argv[1].lower()
    if cmd == "list":
        list_ports(st, cu)
    elif cmd == "del" and len(sys.argv) >= 4:
        del_port(st, cu, int(sys.argv[2]), sys.argv[3])
    elif cmd in ("add", "map") and len(sys.argv) >= 4:
        add_port(st, cu, int(sys.argv[2]), sys.argv[3])
    else:
        print("用法：见文件顶部说明")


if __name__ == "__main__":
    main()
