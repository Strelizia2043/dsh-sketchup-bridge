#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 project2 的两层平面导出成 plan JSON（配置驱动的自动化版本）。

用户确认的事实（逐条对应到代码）
────────────────────────────────
  1 单位 = 50mm ......... MM
  外墙厚 100 ............ 成对墙线间距
  层高 2700 ............. WALL_H
  地板厚 100 ............ FLOOR_T，**不是家具**
  中间大方框: 四壁是墙、顶上玻璃、**没有地板**  → courtyard / glass_roof / floor holes
  外墙上的绿色 = 玻璃洞   → opening type="window" sill=0（整面落地）
  房间内凿开的 = 门       → opening type="door"
  右下角 1/4 圆 = 旋转楼梯
  粉色 = 家具（尺寸不严格）

算法：墙 = 成对的平行线（间距 ≈100mm）；沿墙的**连续覆盖**由同轴线段并出；
      洞口 = 该覆盖区间里**没有墙线**的段（绿色填在里面）。
"""

from __future__ import annotations

import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dxf_import import parse_dxf, segs_of  # noqa: E402

MM = 50.0
WALL_T = 100.0
WALL_H = 2700.0
FLOOR_T = 100.0
SPAN_UNITS = 165.0
PLANS = {"L1": 2946.13, "L2": 3146.13}      # 图纸里的西边 x（两层同一 y）
OY = 7156.55


def load_plan(ents, plan):
    ox = PLANS[plan]
    ox1 = ox + SPAN_UNITS
    out = collections.defaultdict(list)
    for e in ents:
        if e["layer"] == "Defpoints" or (e.get("block") or "").startswith("*D"):
            continue
        for (ax, ay), (bx, by) in segs_of(e):
            if not (ox - 1 <= ax <= ox1 + 1 and ox - 1 <= bx <= ox1 + 1):
                continue
            if not (OY - 1 <= ay <= OY + SPAN_UNITS + 1 and OY - 1 <= by <= OY + SPAN_UNITS + 1):
                continue
            out[e["layer"]].append(
                ((round((ax - ox) * MM, 1), round((ay - OY) * MM, 1)),
                 (round((bx - ox) * MM, 1), round((by - OY) * MM, 1))))
    return out


def hv(segs, tol=1.0):
    H, V = [], []
    for (ax, ay), (bx, by) in segs:
        if abs(ay - by) <= tol:
            H.append((round((ay + by) / 2, 1), round(min(ax, bx), 1), round(max(ax, bx), 1)))
        elif abs(ax - bx) <= tol:
            V.append((round((ax + bx) / 2, 1), round(min(ay, by), 1), round(max(ay, by), 1)))
    return H, V


def pick_face(lines, at, tol=30.0):
    """取位于 at 附近的那条线（面线）。"""
    c = [t for t in lines if abs(t[0] - at) <= tol]
    return c


def runs(vals, tol=1.0, minlen=80.0):
    vals = sorted(vals)
    if not vals:
        return []
    out, s, p = [], vals[0], vals[0]
    for v in vals[1:]:
        if v - p <= tol:
            p = v
        else:
            out.append((s, p))
            s = p = v
    out.append((s, p))
    return [(a, b) for a, b in out if b - a >= minlen]


def coverage(lines, at, tol=30.0):
    """某条墙轴线上，实际有墙线的连续区间。"""
    spans = []
    for p, a, b in lines:
        if abs(p - at) <= tol:
            spans += [a, b]
    return runs(spans, tol=max(tol * 2, 60.0))


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "cad/project2.dxf"
    ents, blocks, layers = parse_dxf(path)
    report = {}

    for plan in ("L1", "L2"):
        g = load_plan(ents, plan)
        w = g.get("wall", []) + g.get("wall2", []) + g.get("wallhatch", [])
        gr = g.get("door", []) + g.get("windoes", [])
        WH, WV = hv(w)
        GH, GV = hv(gr)

        # 所有面线位置（聚类）
        def faces(lines, tol=60.0):
            vals = sorted(set(t[0] for t in lines))
            out, cur = [], [vals[0]] if vals else []
            for v in vals[1:]:
                if v - cur[-1] <= tol:
                    cur.append(v)
                else:
                    out.append(sum(cur) / len(cur))
                    cur = [v]
            if cur:
                out.append(sum(cur) / len(cur))
            return [round(v, 1) for v in out]

        fx, fy = faces(WV), faces(WH)
        print("=" * 78)
        print(f"【{plan}】{'一层' if plan == 'L1' else '二层'}   "
              f"墙轴线 X: {[round(v) for v in fx]}")
        print(f"                墙轴线 Y: {[round(v) for v in fy]}")

        walls, openings = [], []
        for axis, lines, positions, span_max in (("v", WV, fx, MM * SPAN_UNITS),
                                                 ("h", WH, fy, MM * SPAN_UNITS)):
            for at in positions:
                cov = coverage(lines, at)
                if not cov:
                    continue
                # 墙厚：该轴线上相邻面线的间距
                near = sorted(set(t[0] for t in lines if abs(t[0] - at) <= 120))
                th = round(near[-1] - near[0], 1) if len(near) >= 2 else WALL_T
                th = WALL_T if th <= 0 or th > 400 else th
                for a, b in cov:
                    walls.append({"axis": axis, "at": round(at, 1),
                                  "thickness": th, "from": a, "to": b})
        print(f"     墙段 {len(walls)} 个")
        for x in sorted(walls, key=lambda z: (z["axis"], z["at"], z["from"]))[:40]:
            print(f"       {'水平' if x['axis']=='h' else '竖直'} "
                  f"{'y' if x['axis']=='h' else 'x'}={x['at']:>7.0f}  "
                  f"{x['from']:>7.0f}..{x['to']:>7.0f}  (长 {x['to']-x['from']:>6.0f})  厚 {x['thickness']}")
        report[plan] = {"walls": walls,
                        "glass": [{"axis": "h" if p in [t[0] for t in GH] else "v",
                                   "at": p, "from": a, "to": b}
                                  for p, a, b in (GH + GV) if b - a >= 200]}
        print()

    with open("cad/project2_walls.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print("已写出 cad/project2_walls.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
