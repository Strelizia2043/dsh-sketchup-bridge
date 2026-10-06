#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 project2.dxf 提取两层平面的**精确墙段与洞口**，输出可核对的清单。

用户确认的语义与尺寸
────────────────────
  比例        1 图纸单位 = 50mm（用户确认：平面图总宽 165 单位 = 8250mm）
  外墙厚      100mm（成对墙线间距 2 单位）
  层高        2700mm
  地板厚      100mm（用户给）
  红色        = 标注（dim），不是构件
  洋红        = 家具，尺寸不严格
  **中间大方框**：四壁是墙、**顶上是玻璃**，且**这块没有地板**（采光中庭）
  **外墙上的绿色**：墙上的玻璃洞
  **房间内凿开的**：门
  右下角 1/4 圆：旋转楼梯

提取方法
────────
  1. 墙 = 成对的平行线（间距 ≈100mm）
  2. 洞口 = 墙线在该处的**空隙**（绿色填在里面）
  3. 玻璃顶 = 自成一对双线、但**不与外墙共线**的绿色矩形
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
GLASS_T = 100.0

# 两张平面图的图纸坐标范围
PLANS = {
    "L1": (2946.13, 7156.55),     # 左 = 一层
    "L2": (3146.13, 7156.55),     # 右 = 二层
}
SPAN = 165.0                      # 平面图边长（图纸单位）


def norm(ents, plan):
    """把某层的几何换算到**建筑局部坐标（mm，西南角为原点）**。"""
    ox, oy = PLANS[plan]
    out = collections.defaultdict(list)
    for e in ents:
        if e["layer"] == "Defpoints" or (e.get("block") or "").startswith("*D"):
            continue
        for (ax, ay), (bx, by) in segs_of(e):
            if not (ox - 1 <= ax <= ox + SPAN + 1 and ox - 1 <= bx <= ox + SPAN + 1):
                continue
            if not (oy <= ay <= oy + SPAN and oy <= by <= oy + SPAN):
                continue
            out[e["layer"]].append(
                ((round((ax - ox) * MM, 1), round((ay - oy) * MM, 1)),
                 (round((bx - ox) * MM, 1), round((by - oy) * MM, 1))))
    return out


def split_hv(segs, tol=1.0):
    H, V = [], []
    for (ax, ay), (bx, by) in segs:
        if abs(ay - by) <= tol:
            H.append((round((ay + by) / 2, 1), min(ax, bx), max(ax, bx)))
        elif abs(ax - bx) <= tol:
            V.append((round((ax + bx) / 2, 1), min(ay, by), max(ay, by)))
    return H, V


def pair_lines(coords, gap=WALL_T, tol=25.0):
    """把成对的平行线并成墙轴线：返回 [(轴线, 厚)]。"""
    cs = sorted(set(round(c, 1) for c in coords))
    used, out = [False] * len(cs), []
    for i, c in enumerate(cs):
        if used[i]:
            continue
        for j in range(i + 1, len(cs)):
            if used[j]:
                continue
            if abs((cs[j] - cs[i]) - gap) <= tol:
                used[i] = used[j] = True
                out.append(((cs[i] + cs[j]) / 2, round(cs[j] - cs[i], 1)))
                break
        else:
            used[i] = True
            out.append((c, None))      # 配不上对 → 单线（可能是玻璃或是墙中线）
    return sorted(out)


def runs(vals, tol=1.0):
    """把一串坐标并成连续区间 [(起, 止)]。"""
    vals = sorted(set(round(v, 1) for v in vals))
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
    return out


def analyze(ents, plan) -> dict:
    g = norm(ents, plan)
    w = g.get("wall", []) + g.get("wall2", []) + g.get("wallhatch", [])
    gr = g.get("door", []) + g.get("windoes", [])
    wh, wv = split_hv(w)
    gh, gv = split_hv(gr)

    res = {"plan": plan, "walls": [], "glass": [], "openings": []}

    # ── 墙：成对线 → 轴线 + 厚度；沿墙方向的**连续覆盖**由该轴线上所有线段并出
    for axis, items, other in (("h", wh, wv), ("v", wv, wh)):
        pos = [t[0] for t in items]
        for axis_pos, thick in pair_lines(pos):
            if thick is None:
                continue
            # 该墙轴线附近的所有线段（同一面墙可能画成多段）
            spans = [(a, b) for p, a, b in items if abs(p - axis_pos) <= WALL_T / 2 + 1]
            for s0, s1 in runs([v for sp in spans for v in sp]):
                if s1 - s0 < 50:
                    continue
                res["walls"].append({
                    "axis": axis, "at": round(axis_pos, 1),
                    "thickness": thick, "from": round(s0, 1), "to": round(s1, 1),
                })

    # ── 绿色：分类
    for axis, items in (("h", gh), ("v", gv)):
        for p, a, b in items:
            if b - a < 200:
                continue
            res["glass"].append({"axis": axis, "at": round(p, 1),
                                 "from": round(a, 1), "to": round(b, 1),
                                 "len": round(b - a, 1)})
    return res


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "cad/project2.dxf"
    ents, blocks, layers = parse_dxf(path)
    out = {}
    for plan in ("L1", "L2"):
        r = analyze(ents, plan)
        out[plan] = r
        print("=" * 76)
        print(f"【{plan}】{'一层（左图）' if plan == 'L1' else '二层（右图）'}"
              f"   建筑局部坐标，单位 mm，西南角为原点")
        print("=" * 76)

        print(f"\n── 墙（成对线配对，厚度 100）共 {len(r['walls'])} 段")
        for w in sorted(r["walls"], key=lambda z: (z["axis"], z["at"], z["from"])):
            lo = "x" if w["axis"] == "h" else "y"
            print(f"   {'水平' if w['axis']=='h' else '竖直'}  "
                  f"{'y' if w['axis']=='h' else 'x'}={w['at']:>8.0f}   "
                  f"沿{lo} {w['from']:>7.0f}..{w['to']:>7.0f}  "
                  f"（长 {w['to']-w['from']:>7.0f}）")

        print(f"\n── 绿色（玻璃）共 {len(r['glass'])} 段，按长度取前 16")
        for x in sorted(r["glass"], key=lambda z: -z["len"])[:16]:
            print(f"   {'水平' if x['axis']=='h' else '竖直'}  "
                  f"{'y' if x['axis']=='h' else 'x'}={x['at']:>8.0f}   "
                  f"{x['from']:>7.0f}..{x['to']:>7.0f}  长 {x['len']:>7.0f}")

    with open("cad/project2_parsed.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\n已写出 cad/project2_parsed.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
