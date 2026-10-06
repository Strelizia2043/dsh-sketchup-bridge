#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DXF 几何详查：把每条线/多段线的端点、颜色、所在块都列出来。

为什么不能只看统计：探查发现"按图层统计"与用户描述的
"白=墙、红=门、绿=窗"对不上（图层只有 Layer1 红 / Layer2 青 / Layer3 绿）。
所以必须看**逐实体的颜色**和**块定义里的几何**——
门窗很可能是画在块里的，而块内实体的图层与外层不同。
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
import sys

sys.path.insert(0, ".")
from dxf_probe import read_pairs, decode_cn  # noqa: E402

ACI_TO_RGB = {
    1: (255, 0, 0), 2: (255, 255, 0), 3: (0, 255, 0), 4: (0, 255, 255),
    5: (0, 0, 255), 6: (255, 0, 255), 7: (255, 255, 255), 8: (128, 128, 128),
    9: (192, 192, 192), 10: (255, 0, 0), 30: (255, 127, 0), 50: (255, 255, 0),
    70: (255, 0, 0), 250: (51, 51, 51), 251: (91, 91, 91), 252: (132, 132, 132),
    253: (173, 173, 173), 254: (214, 214, 214), 255: (255, 255, 255),
}
ACI_NAME = {1: "红", 2: "黄", 3: "绿", 4: "青", 5: "蓝", 6: "洋红", 7: "白/黑",
            8: "深灰", 9: "浅灰", 50: "黄", 70: "红", 10: "红", 30: "橙"}


def parse(path: str):
    """返回 (实体列表, 块定义字典, 图层字典)。

    实体 = dict(type, layer, color, 几何字段...)
    """
    pairs = read_pairs(path)

    # 图层名 → 颜色
    layers = {}
    i = 0
    while i < len(pairs):
        if pairs[i][0] == 0 and pairs[i][1] == "LAYER":
            a = collections.defaultdict(list)
            j = i + 1
            while j < len(pairs) and pairs[j][0] != 0:
                a[pairs[j][0]].append(pairs[j][1])
                j += 1
            nm = decode_cn((a.get(2) or ["?"])[0])
            try:
                layers[nm] = int(a[62][0])
            except (KeyError, ValueError, IndexError):
                layers[nm] = 7
            i = j
            continue
        i += 1

    # 遍历节：ENTITIES 与 BLOCKS（块内几何也要）
    ents = []
    blocks = {}
    sect = None
    cur_block = None
    i = 0
    while i < len(pairs):
        c, v = pairs[i]
        if c == 0 and v == "SECTION":
            sect = pairs[i + 1][1]
            i += 2
            continue
        if c == 0 and v == "ENDSEC":
            sect = None
            cur_block = None
            i += 1
            continue
        if c == 0 and v == "BLOCK":
            a = collections.defaultdict(list)
            j = i + 1
            while j < len(pairs) and pairs[j][0] != 0:
                a[pairs[j][0]].append(pairs[j][1])
                j += 1
            cur_block = decode_cn((a.get(2) or ["*?"])[0])
            blocks.setdefault(cur_block, [])
            i = j
            continue
        if c == 0 and v == "ENDBLK":
            cur_block = None
            i += 1
            continue
        if c == 0 and v in ("LINE", "LWPOLYLINE", "POINT", "SOLID", "CIRCLE",
                            "ARC", "TEXT", "MTEXT", "INSERT", "DIMENSION"):
            etype = v
            a = collections.defaultdict(list)
            j = i + 1
            while j < len(pairs) and pairs[j][0] != 0:
                a[pairs[j][0]].append(pairs[j][1])
                j += 1

            def f(code, idx=0, dflt=None):
                try:
                    return float(a[code][idx])
                except (KeyError, ValueError, IndexError):
                    return dflt

            e = {"type": etype,
                 "layer": decode_cn((a.get(8) or ["0"])[0]),
                 "color": int(a[62][0]) if a.get(62) and a[62][0].strip() else None,
                 "block": cur_block}
            if etype == "LINE":
                e["p1"] = (f(10), f(20))
                e["p2"] = (f(11), f(21))
            elif etype == "LWPOLYLINE":
                xs = [float(x) for x in a.get(10, [])]
                ys = [float(y) for y in a.get(20, [])]
                e["pts"] = list(zip(xs, ys))
                e["closed"] = int(a[70][0]) if a.get(70) else 0
            elif etype == "POINT":
                e["p"] = (f(10), f(20))
            elif etype == "SOLID":
                e["pts"] = [(f(10), f(20)), (f(11), f(21)),
                            (f(12), f(22)), (f(13), f(23))]
            elif etype == "INSERT":
                e["name"] = decode_cn((a.get(2) or ["?"])[0])
                e["at"] = (f(10), f(20))
                e["scale"] = (f(41, dflt=1.0), f(42, dflt=1.0))
                e["rot"] = f(50, dflt=0.0)
            elif etype == "MTEXT":
                e["text"] = decode_cn("".join(a.get(1, [])) + "".join(a.get(3, [])))
                e["at"] = (f(10), f(20))
            elif etype == "DIMENSION":
                e["measure"] = f(42)
                e["text"] = decode_cn((a.get(1) or [""])[0])
                e["at"] = (f(10), f(20))
                e["defpoint"] = (f(13), f(23))
                e["defpoint2"] = (f(14), f(24))
            ents.append(e)
            if cur_block:
                blocks[cur_block].append(e)
            i = j
            continue
        i += 1
    return ents, blocks, layers


def rgb_of(e, layers):
    c = e.get("color")
    if c is None:
        c = layers.get(e["layer"], 7)
    return c, ACI_TO_RGB.get(c, (128, 128, 128)), ACI_NAME.get(c, f"ACI{c}")


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "examples/drawings/shop_plan.dxf"
    ents, blocks, layers = parse(path)
    print(f"=== 图层颜色表 ===")
    for nm, c in layers.items():
        print(f"     {nm:<12} ACI={c:<4} {ACI_NAME.get(c,'?'):<6} RGB={ACI_TO_RGB.get(c)}")
    print()
    print(f"=== 块定义（{len(blocks)} 个）===")
    for nm, es in blocks.items():
        types = collections.Counter(x["type"] for x in es)
        print(f"     {nm:<16} {len(es):>3} 个实体  {dict(types)}")
    print()
    print("=== 模型空间里的 INSERT（块的引用）===")
    for e in ents:
        if e["type"] == "INSERT":
            print(f"     {e['name']:<16} at={e['at']} 缩放={e['scale']} 旋转={e['rot']}")
    print()
    print("── 顶层 ENTITIES 的几何实体（按颜色分组）──")
    groups = collections.defaultdict(list)
    for e in ents:
        if e.get("block"):
            continue
        if e["type"] in ("LINE", "LWPOLYLINE", "SOLID", "POINT"):
            c, rgb, cn = rgb_of(e, layers)
            groups[(c, cn)].append(e)
    for (c, cn), es in sorted(groups.items()):
        print(f"     ACI={c} ({cn}, RGB={ACI_TO_RGB.get(c)})  {len(es)} 个实体")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
