#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重建 n2n-lan-client.zip（分发用）
打包 client/ 目录：exe + bat + 说明 + Linux 脚本 + bin + driver + tools
排除：config.json（本机房间密钥）、logs/、*.py、__pycache__、tools/WinIPBroadcast.exe（许可不明）
"""
import os
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
CLIENT = os.path.join(ROOT, "client")
OUT = os.path.join(ROOT, "n2n-lan-client.zip")
PREFIX = "n2n-lan-client/"

EXCLUDE_DIRS = {"logs", "__pycache__"}
EXCLUDE_FILES = {"config.json"}
EXCLUDE_SUFFIXES = (".py", ".pyc")
EXCLUDE_NAMES = {"WinIPBroadcast.exe"}


def main():
    count = 0
    total = 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
        for base, dirs, files in os.walk(CLIENT):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for name in sorted(files):
                if name in EXCLUDE_FILES or name in EXCLUDE_NAMES:
                    continue
                if name.endswith(EXCLUDE_SUFFIXES):
                    continue
                src = os.path.join(base, name)
                rel = os.path.relpath(src, CLIENT).replace("\\", "/")
                arc = PREFIX + rel
                zf.write(src, arc)
                count += 1
                total += os.path.getsize(src)
    print("zip entries:", count)
    print("uncompressed bytes:", total)
    print("zip size:", os.path.getsize(OUT))


if __name__ == "__main__":
    main()
