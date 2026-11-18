# -*- coding: utf-8 -*-
"""校验 docs/index.html：data-i18n 键在 zh/en 字典中是否都存在，并检查新增下载区元素"""
import re, io, sys, json, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
p = os.path.join(ROOT, 'docs', 'index.html')
html = open(p, encoding='utf-8').read()

# 1) 提取 HTML 中所有 data-i18n 键
keys = set(re.findall(r'data-i18n="([^"]+)"', html))

# 2) 提取 zh / en 两个对象（粗略：从 "zh: {" 到对应的 "}"，按缩进 2 空格 "en: {" 边界切）
def extract_dict(name):
    # 找到 "    zh: {" 或 "    en: {"
    m = re.search(r'\n\s+' + name + r':\s*\{', html)
    if not m:
        return {}
    start = m.start()
    # 从 start 之后找第一个 "\n    }", 但内部对象也可能有 }；用括号配平
    i = m.end() - 1  # 指向 {
    depth = 0
    in_str = False
    esc = False
    for j in range(i, len(html)):
        ch = html[j]
        if in_str:
            if esc: esc = False
            elif ch == '\\': esc = True
            elif ch == '"': in_str = False
        else:
            if ch == '"': in_str = True
            elif ch == '{': depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    body = html[i:j+1]
                    break
    else:
        return {}
    pairs = {}
    for km in re.finditer(r'"([^"]+)"\s*:\s*"((?:[^"\\]|\\.)*)"', body):
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
for pat in ['downloads/n2n-lan-setup-1.2.0.exe', 'id="copyDl"', 'id="dlUrl"', 'aria2c -x 16 -s 16',
            'b650bc21fd82bf6e2e8e6a80b4e67bde083497a10980f82501179ce3a730dfdd',
            'download="n2n-lan-setup-1.2.0.exe"', 'downloads/n2n-lan-client.zip', 'dl1-green']:
    print(('OK  ' if pat in html else 'MISS'), pat)

# 4) 统计 download 属性链接数量
print('download 属性出现次数:', html.count('download="n2n-lan-setup-1.2.0.exe"'))
