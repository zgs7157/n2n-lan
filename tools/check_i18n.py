# -*- coding: utf-8 -*-
"""校验 docs/index.html：data-i18n 键在 zh/en 字典中是否都存在，并检查新增下载区元素"""
import re, io, sys, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

p = r'C:\Users\Administrator\DoubaoWork\chats\2026-10-08\new-chat\n2n-lan\docs\index.html'
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

# 3) 检查下载区关键元素
for pat in ['downloads/n2n-lan-client.zip', 'id="copyDl"', 'id="dlUrl"', 'aria2c -x 16 -s 16',
            'e6e8ebc1af7e4a3dde67bcc0db92b1191682cc5fc110e631baf8c62cb2b4f51c', 'download="n2n-lan-client.zip"']:
    print(('OK  ' if pat in html else 'MISS'), pat)

# 4) 统计 download 属性链接数量
print('download 属性出现次数:', html.count('download="n2n-lan-client.zip"'))
