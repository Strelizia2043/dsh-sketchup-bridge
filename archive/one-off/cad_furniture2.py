#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 DXF 的 furniture 图层聚成"家具块"，输出可直接建模的矩形清单。

用户说「粉色的就是家具，实际上它的尺寸还有形制没有定的那么死，
只要别太夸张就行了」——所以这里只需要**合理的体块**，不追求形制。

做法：把家具图元的包围盒按"相互靠近就合并"聚成若干簇，
每簇取包围盒 → 一个体块。**用并查集做连通性归并**，避免逐个实体建出 485 个碎块。
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dxf_import import parse_dxf, segs_of  # noqa: E402

MM = 50.0
PLANS = {"L1": 2946.13, "L2": 3146.13}
OY = 7156.55
SPAN = 165.0
# 归并阈值：两个盒子的间隙小于它就算同一件家具
MERGE_GAP = 30.0


def boxes_of(ents, plan):
    ox = PLANS[plan]
    out = []
    for e in ents:
        if e["layer"] != "furniture" or (e.get("block") or "").startswith("*D"):
            continue
        ss = segs_of(e)
        if not ss:
            continue
        xs = [c for s in ss for c in (s[0][0], s[1][0])]
        ys = [c for s in ss for c in (s[0][1], s[1][1])]
        if not (ox - 1 <= min(xs) and max(xs) <= ox + SPAN + 1):
            continue
        if not (OY - 1 <= min(ys) and max(ys) <= OY + SPAN + 1):
            continue
        out.append(((min(xs) - ox) * MM, (min(ys) - OY) * MM,
                    (max(xs) - ox) * MM, (max(ys) - OY) * MM))
    return out


def merge(boxes, gap=MERGE_GAP):
    """并查集：包围盒互相靠近（间隙 ≤ gap）就并成一簇。"""
    n = len(boxes)
    par = list(range(n))

    def find(a):
        while par[a] != a:
            par[a] = par[par[a]]
            a = par[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            par[rb] = ra

    for i in range(n):
        xi0, yi0, xi1, yi1 = boxes[i]
        for j in range(i + 1, n):
            xj0, yj0, xj1, yj1 = boxes[j]
            # 两个矩形在 x/y 上的间隙
            gx = max(0.0, max(xi0, xj0) - min(xi1, xj1))
            gy = max(0.0, max(yi0, yj0) - min(yi1, yj1))
            if gx <= gap and gy <= gap:
                union(i, j)

    groups = {}
    for i, b in enumerate(boxes):
        groups.setdefault(find(i), []).append(b)
    out = []
    for _, bs in groups.items():
        out.append((min(b[0] for b in bs), min(b[1] for b in bs),
                    max(b[2] for b in bs), max(b[3] for b in bs), len(bs)))
    return sorted(out, key=lambda t: -(t[2] - t[0]) * (t[3] - t[1]))


def main() -> int:
    ents, _, _ = parse_dxf(sys.argv[1] if len(sys.argv) > 1 else "cad/project2.dxf")
    res = {}
    for plan in ("L1", "L2"):
        bs = boxes_of(ents, plan)
        ms = merge(bs)
        print("=" * 74)
        print(f"【{plan}】家具：{len(bs)} 个实体 → 归并成 {len(ms)} 件")
        for x0, y0, x1, y1, n in ms[:28]:
            w, h = x1 - x0, y1 - y0
            if w < 100 or h < 100:
                continue
            print(f"   X {x0:>7.0f}..{x1:>7.0f}  Y {y0:>7.0f}..{y1:>7.0f}   "
                  f"{w:>6.0f} × {h:>6.0f}  ({n} 个图元)")
        res[plan] = [{"x0": round(a, 1), "y0": round(b, 1),
                      "x1": round(c, 1), "y1": round(d, 1), "parts": e}
                     for a, b, c, d, e in ms
                     if (c - a) >= 100 and (d - b) >= 100]
    with open("cad/project2_furniture.json", "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("\n已写出 cad/project2_furniture.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
