#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 DXF 解析结果画成平面示意图 —— 用于**肉眼核对**数据是否正确。

为什么必须画：我手上有一组数字（外墙 5000×5000、墙厚 50、3 个红色洞口），
但数字自洽不代表**理解正确**。尤其是第 1 个红色洞口在 X 626..676，
而建筑外墙从 X 2059 才开始 —— 它在建筑外面，我不知道那是什么。
画出来一眼就能看出我是不是把什么东西理解错了。
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

import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dxf_detail import parse  # noqa: E402


def segs_of(e):
    t = e["type"]
    if t == "LINE" and e.get("p1"):
        return [(e["p1"], e["p2"])]
    if t == "LWPOLYLINE":
        p = e.get("pts") or []
        r = [(p[i], p[i + 1]) for i in range(len(p) - 1)]
        if e.get("closed") and len(p) > 2:
            r.append((p[-1], p[0]))
        return r
    return []


def main() -> int:
    ents, blocks, layers = parse(_default_dxf())
    walls, doors = [], []
    for e in ents:
        if e["layer"] == "Defpoints":
            continue
        s = segs_of(e)
        if not s:
            continue
        aci = e.get("color") if e.get("color") is not None else layers.get(e["layer"], 7)
        if e["layer"] == "0":
            walls += s
        elif aci in (1, 10, 70):
            doors.append(s)

    allsegs = walls + [x for d in doors for x in d]
    xs = [c for s in allsegs for c in (s[0][0], s[1][0])]
    ys = [c for s in allsegs for c in (s[0][1], s[1][1])]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    pad = 400
    x0, x1, y0, y1 = x0 - pad, x1 + pad, y0 - pad, y1 + pad

    SCALE = 0.16                      # px per mm
    W = int((x1 - x0) * SCALE) + 2
    H = int((y1 - y0) * SCALE) + 2
    img = Image.new("RGB", (W, H), (18, 18, 22))
    dr = ImageDraw.Draw(img)

    def T(p):
        """图纸坐标 → 图像坐标（Y 轴翻转：图纸 Y 向上，图像 Y 向下）"""
        return ((p[0] - x0) * SCALE, (y1 - p[1]) * SCALE)

    # 标注看不太清，墙用亮白加粗
    for a, b in walls:
        dr.line([T(a), T(b)], fill=(240, 240, 240), width=2)
    for d in doors:
        for a, b in d:
            dr.line([T(a), T(b)], fill=(255, 60, 60), width=3)

    # 标出外墙范围
    dr.rectangle([T((2059.13, 2149.48)), T((7059.13, -2850.52))],
                 outline=(60, 200, 255), width=1)

    out = "cad/parsed_preview.png"
    img.save(out)
    print(f"  已画出 {out}  ({W}×{H})")
    print(f"  图纸范围 X {x0:.0f}..{x1:.0f}  Y {y0:.0f}..{y1:.0f}（含 {pad} 余量）")
    print(f"  白色 = 墙线 {len(walls)} 条   红色 = 门 {sum(len(d) for d in doors)} 条")
    print(f"  青色框 = 外墙轮廓 5000×5000")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
