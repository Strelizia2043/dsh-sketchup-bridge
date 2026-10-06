#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DXF 结构探查：先弄清图里到底有什么，再决定怎么解析。

为什么先探不用现成库：这台机器上 **ezdxf / dxfgrabber 都装不上**（pip 受限）。
但 ASCII DXF 就是"组码 / 值"成对出现的纯文本，自己解析完全可行。

为什么先探而不是直接建：我不知道这张图是怎么画的——
墙是 LINE 还是 LWPOLYLINE？颜色是按图层还是按实体？门窗画成什么？
**先探明再动手**，否则又会陷入"猜→改→再猜"。
"""

from __future__ import annotations

# --- DSH 路径修正（重组后自动加，见 fix_imports.py）
def _dsh_bootstrap():
    """把依赖目录加进 sys.path（重组目录后必需）。

    ⚠️ 两个坑：
      1. 不能依赖模块级的 `import os` —— 本函数在文件顶部就被调用，
         那时 `import os` 还没执行（第一版栽在这：NameError: name 'os' is not defined）。
         所以在**函数体内** import。
      2. 不能假设 `os.path.dirname(__file__)` 就是依赖所在目录：
         脚本移到 tools/ 子目录后，依赖（sk_client.py / version.json）在**根目录**。
         所以要逐级上溯，找到含 sk_client.py 的那一层。
    """
    import os.path as _op
    import sys as _sys
    _cur = _op.dirname(_op.abspath(__file__))
    for _ in range(5):
        if _op.exists(_op.join(_cur, 'sk_client.py')):
            break
        _parent = _op.dirname(_cur)
        if _parent == _cur:
            break
        _cur = _parent
    for _d in ['.']:
        _p = _op.normpath(_op.join(_cur, _d))
        if _p not in _sys.path:
            _sys.path.insert(0, _p)


_dsh_bootstrap()

import collections
import json
import sys


def read_pairs(path: str):
    """把 ASCII DXF 读成 (组码, 值) 序列。

    DXF 结构：每个数据项两行 —— 第一行是组码（整数），第二行是值。
    编码用 $DWGCODEPAGE 指定的代码页（这张图是 ANSI_936 即 GBK）。
    """
    with open(path, "rb") as f:
        raw = f.read()
    # 先按 latin-1 解出结构（组码和 ASCII 值都不受影响），
    # 需要中文时再对具体值用 gbk 重解
    text = raw.decode("latin-1")
    lines = text.split("\n")
    if lines and lines[-1].strip() == "":
        lines.pop()
    out = []
    for i in range(0, len(lines) - 1, 2):
        code = lines[i].strip()
        val = lines[i + 1].rstrip("\r")
        try:
            code_i = int(code)
        except ValueError:
            continue
        out.append((code_i, val))
    return out


def decode_cn(s: str) -> str:
    """悬空的中文值用 GBK 还原（latin-1 读出来的字节序列）。"""
    try:
        return s.encode("latin-1").decode("gbk")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "examples/drawings/shop_plan.dxf"
    pairs = read_pairs(path)
    print(f"=== DXF 探查：{path} ===")
    print(f"    组码项总数：{len(pairs):,}")

    # ── 分节
    sections = []
    cur = None
    for i, (c, v) in enumerate(pairs):
        if c == 0 and v == "SECTION":
            cur = pairs[i + 1][1] if i + 1 < len(pairs) else "?"
            sections.append(cur)
    print(f"    节：{sections}")

    # ── 实体扫描：找 ENTITIES / BLOCKS 节
    ents = []
    in_ent = False
    i = 0
    while i < len(pairs):
        c, v = pairs[i]
        if c == 0 and v == "SECTION":
            sect = pairs[i + 1][1] if i + 1 < len(pairs) else ""
            in_ent = sect in ("ENTITIES", "BLOCKS")
            i += 2
            continue
        if c == 0 and v == "ENDSEC":
            in_ent = False
            i += 1
            continue
        if in_ent and c == 0:
            etype = v
            attrs = {}
            j = i + 1
            while j < len(pairs) and pairs[j][0] != 0:
                code, val = pairs[j]
                attrs.setdefault(code, []).append(val)
                j += 1
            ents.append((etype, attrs))
            i = j
            continue
        i += 1

    print(f"    实体总数：{len(ents):,}")
    print()
    print("── 按类型统计")
    for t, n in collections.Counter(e[0] for e in ents).most_common():
        print(f"     {t:<16} {n:>6}")

    print()
    print("── 按图层统计")
    for t, n in collections.Counter(
            (e[1].get(8) or ["(无)"])[0] for e in ents).most_common():
        print(f"     {t:<24} {n:>6}")

    print()
    print("── 按颜色统计（组码 62；缺省 = BYLAYER）")
    col = collections.Counter()
    for _, a in ents:
        col[(a.get(62) or ["BYLAYER"])[0]] += 1
    for t, n in col.most_common(20):
        print(f"     {t:<12} {n:>6}")

    print()
    print("── 图层表（颜色 62 / 线型 6 / 开 70）")
    in_tab = False
    i = 0
    while i < len(pairs):
        c, v = pairs[i]
        if c == 0 and v == "TABLE":
            in_tab = pairs[i + 1][1] == "LAYER" if i + 1 < len(pairs) else False
            i += 2
            continue
        if in_tab and c == 0 and v == "LAYER":
            attrs = {}
            j = i + 1
            while j < len(pairs) and pairs[j][0] != 0:
                attrs.setdefault(pairs[j][0], []).append(pairs[j][1])
                j += 1
            nm = decode_cn((attrs.get(2) or ["?"])[0])
            print(f"     {nm:<24} 颜色={attrs.get(62, ['?'])[0]:<6} "
                  f"线型={(attrs.get(6) or ['?'])[0]:<14} 标志={attrs.get(70, ['?'])[0]}")
            i = j
            continue
        i += 1

    # ── 坐标范围
    xs, ys = [], []
    for _, a in ents:
        for code, arr in a.items():
            if code in (10, 11) and arr:
                try:
                    xs.append(float(arr[0]))
                except ValueError:
                    pass
            if code in (20, 21) and arr:
                try:
                    ys.append(float(arr[0]))
                except ValueError:
                    pass
    if xs and ys:
        print()
        print("── 坐标范围（图纸单位；你说过单位是 mm）")
        print(f"     X: {min(xs):.2f} .. {max(xs):.2f}   跨度 {max(xs) - min(xs):.2f}")
        print(f"     Y: {min(ys):.2f} .. {max(ys):.2f}   跨度 {max(ys) - min(ys):.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
