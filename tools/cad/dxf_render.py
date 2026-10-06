#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 DXF 按**图层**上色画成 PNG —— 先看见，再动手。

为什么必须先画：图层名和实体数是"元数据"，不等于"我理解了这张图"。
上一张图我就是靠画出来才发现
  · 一个"门"其实孤零零在建筑外面
  · 一层和二层的图形挤在同一张图上
**看见再动手，能省掉后面反复返工。**

上色规则：按**图层名**匹配（比颜色号稳——这张图 red 同时是 dim 和 plant）。
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
import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dxf_import import parse_dxf, segs_of  # noqa: E402

# 图层关键词 → 颜色（按**顺序**匹配，越靠前优先）
RULES = [
    ("dim",        (255, 70, 70)),     # 标注 红
    ("wall",       (240, 240, 240)),   # 墙   白（画粗一点）
    ("door",       (60, 255, 60)),     # 门/玻璃 绿
    ("windo",      (60, 255, 60)),     # 窗   绿
    ("glass",      (60, 255, 60)),
    ("furniture",  (255, 60, 255)),    # 家具 洋红
    ("stair",      (255, 200, 0)),     # 楼梯 橙黄
    ("plant",      (0, 200, 120)),     # 植物 青绿
    ("hatch",      (90, 90, 120)),     # 填充 暗蓝灰
    ("solar",      (60, 160, 255)),    # 太阳能 蓝
]
DEFAULT = (110, 110, 110)


def color_of(layer: str):
    low = layer.lower()
    for key, col in RULES:
        if key in low:
            return col
    return DEFAULT


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "examples/drawings/two_story_house.dxf"
    out = sys.argv[2] if len(sys.argv) > 2 else "shots/preview.png"
    only_layer = sys.argv[3] if len(sys.argv) > 3 else None
    max_px = int(sys.argv[4]) if len(sys.argv) > 4 else 1600

    ents, blocks, layers = parse_dxf(path)
    groups = collections.defaultdict(list)
    for e in ents:
        if e["layer"] == "Defpoints":
            continue          # 标注定义点，不是图形
        if (e.get("block") or "").startswith("*D"):
            continue          # 标注块内部
        if only_layer and only_layer.lower() not in e["layer"].lower():
            continue
        s = segs_of(e)
        if s:
            groups[e["layer"]].append(s)

    allsegs = [sg for v in groups.values() for s in v for sg in s]
    if not allsegs:
        print("没有可画的线段")
        return 1
    xs = [c for s in allsegs for c in (s[0][0], s[1][0])]
    ys = [c for s in allsegs for c in (s[0][1], s[1][1])]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    w, h = x1 - x0, y1 - y0
    pad = max(w, h) * 0.03 + 1
    x0, x1, y0, y1 = x0 - pad, x1 + pad, y0 - pad, y1 + pad
    w, h = x1 - x0, y1 - y0

    S = min(max_px / w, max_px / h)
    W, H = int(w * S) + 2, int(h * S) + 2
    img = Image.new("RGB", (W, H), (14, 14, 18))
    dr = ImageDraw.Draw(img)

    def T(p):
        return ((p[0] - x0) * S, (y1 - p[1]) * S)   # 图纸 Y 向上 → 图像 Y 向下

    # 先画填充/次要，墙最后画（压在顶层）
    order = sorted(groups, key=lambda L: (0 if "wall" in L.lower() else 1))
    for L in order:
        col = color_of(L)
        wid = 3 if "wall" in L.lower() else 1
        for seg in groups[L]:
            for a, b in seg:
                dr.line([T(a), T(b)], fill=col, width=wid)

    img.save(out)
    print(f"已画出 {out}  ({W}×{H})  图纸范围 {w:.1f} × {h:.1f}")
    print("  图层 → 颜色 → 线段数：")
    for L in sorted(groups, key=lambda z: -len(groups[z])):
        c = color_of(L)
        print(f"    {L:<22} RGB{c}  {sum(len(s) for s in groups[L]):>5} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
