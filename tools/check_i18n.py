# -*- coding: utf-8 -*-
"""校验 docs/index.html：data-i18n 键在 zh/en 字典中是否都存在，并检查下载区元素

版本号与 sha256 不再硬编码：从 setup_n2n.iss 读 MyAppVersion，
再对 docs/downloads 下实际的安装包算 sha256 与之对照。
"""
import hashlib
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
p = os.path.join(ROOT, 'docs', 'index.html')
html = open(p, encoding='utf-8').read()

# 版本号来自安装脚本，sha256 来自实际文件
iss = open(os.path.join(ROOT, 'setup_n2n.iss'), encoding='utf-8').read()
m = re.search(r'#define MyAppVersion "([^"]+)"', iss)
VER = m.group(1) if m else ''
setup_name = 'n2n-lan-setup-%s.exe' % VER
setup_path = os.path.join(ROOT, 'docs', 'downloads', setup_name)
if os.path.isfile(setup_path):
    with open(setup_path, 'rb') as f:
        SHA = hashlib.sha256(f.read()).hexdigest()
else:
    SHA = ''
print('版本:', VER, '| 主下载:', setup_name, '| sha256:', SHA or '（安装包不存在）')

# 1) 提取 HTML 中所有 data-i18n 键
keys = set(re.findall(r'data-i18n="([^"]+)"', html))


# 2) 提取 zh / en 两个对象（粗略：从 "    zh: {" 到对应的 "}"）
def extract_dict(name):
    m = re.search(r'\n\s+' + name + r':\s*\{', html)
    if not m:
        return {}
    i = m.end() - 1
    depth = 0
    in_str = False
    esc = False
    body = ''
    for j in range(i, len(html)):
        ch = html[j]
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    body = html[i:j + 1]
                    break
    pairs = {}
    for km in re.finditer(r'"([^"]+)":\s*"((?:[^"\\]|\\.)*)"', body):
        pairs[km.group(1)] = km.group(2)
    return pairs


zh = extract_dict('zh')
en = extract_dict('en')

print('HTML 中 data-i18n 键数量:', len(keys))
print('zh 字典条目:', len(zh), '| en 字典条目:', len(en))
missing_zh = sorted(k for k in keys if k not in zh)
missing_en = sorted(k for k in keys if k not in en)
print('zh 缺失:', missing_zh if missing_zh else '无')
print('en 缺失:', missing_en if missing_en else '无')

# 3) 检查下载区关键元素（主下载 = 安装程序；绿色版 zip 作为次要入口）
checks = ['downloads/' + setup_name, 'id="copyDl"', 'id="dlUrl"', 'aria2c -x 16 -s 16',
          'download="' + setup_name + '"', 'downloads/n2n-lan-client.zip', 'dl1-green']
if SHA:
    checks.insert(4, SHA)
bad = 0
for pat in checks:
    ok = pat in html
    if not ok:
        bad += 1
    print(('OK  ' if ok else 'MISS'), pat)

# 4) 统计 download 属性链接数量
print('download 属性出现次数:', html.count('download="' + setup_name + '"'))
print('判定:', '通过' if bad == 0 else '不通过（%d 项缺失）' % bad)
