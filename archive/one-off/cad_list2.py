#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""project2 两层的墙/洞口清单 —— **由实测坐标归纳**，输出给用户核对。

数据来源：cad/project2_walls.json 的原始墙线段（cad_walls2.py 抽取）。
本脚本做的是"把碎片归纳成墙 + 洞口"，判据写在每一项旁边，便于核对。

用户确认的关键事实：
  · 1 单位 = 50mm；外墙厚 100mm；层高 2700mm；地板厚 100mm
  · 中庭（约 2250..6100 见方）：四壁是墙、顶上玻璃、**没有地板**
  · 外墙上的绿色 = 玻璃洞（落地）
  · 房间内凿开的 = 门
"""

from __future__ import annotations

import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dxf_import import parse_dxf, segs_of  # noqa: E402

MM = 50.0
SPAN = 8250.0
WALL_T = 100.0
WALL_H = 2700.0
FLOOR_T = 100.0
PLANS = {"L1": 2946.13, "L2": 3146.13}
OY = 7156.55
COURT = (2250.0, 2250.0, 6100.0, 6100.0)   # x0,y0,x1,y1（中庭洞口）


def load(ents, plan):
    ox = PLANS[plan]
    w, gr = [], []
    for e in ents:
        if e["layer"] == "Defpoints" or (e.get("block") or "").startswith("*D"):
            continue
        lay = e["layer"].lower()
        tgt = w if ("wall" in lay) else (gr if ("door" in lay or "windo" in lay) else None)
        if tgt is None:
            continue
        for (ax, ay), (bx, by) in segs_of(e):
            if not (ox - 1 <= ax <= ox + 165 + 1 and ox - 1 <= bx <= ox + 165 + 1):
                continue
            if not (OY - 1 <= ay <= OY + 165 + 1 and OY - 1 <= by <= OY + 165 + 1):
                continue
            A = ((ax - ox) * MM, (ay - OY) * MM)
            B = ((bx - ox) * MM, (by - OY) * MM)
            if abs(A[0] - B[0]) < 1:
                tgt.append(("v", round(A[0]), round(min(A[1], B[1]), 1), round(max(A[1], B[1]), 1)))
            elif abs(A[1] - B[1]) < 1:
                tgt.append(("h", round(A[1]), round(min(A[0], B[0]), 1), round(max(A[0], B[0]), 1)))
    return w, gr


def coverage(segs, axis, at, tol=40.0, gap=160.0):
    """某个墙轴线上"有墙线"的连续区间（把 <=gap 的小断口并掉，门窗洞比它大）。"""
    iv = sorted((s, e) for ax, p, s, e in segs if ax == axis and abs(p - at) <= tol)
    if not iv:
        return []
    out = [list(iv[0])]
    for s, e in iv[1:]:
        if s - out[-1][1] <= gap:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(a, b) for a, b in out if b - a >= 60]


def holes(cov, lo, hi, minw=600.0):
    """在 [lo,hi] 里，coverage 之外的部分 = 洞口。"""
    hs = []
    cur = lo
    for a, b in sorted(cov):
        a2, b2 = max(a, lo), min(b, hi)
        if a2 > cur and a2 - cur >= minw:
            hs.append((round(cur, 1), round(a2, 1)))
        cur = max(cur, b2)
    if hi - cur >= minw:
        hs.append((round(cur, 1), round(hi, 1)))
    return hs


def green_in(gr, axis, lo, hi, tol=60.0):
    """落在 [lo,hi] 区间里的绿色段（用于给洞口标类型）。"""
    return [(s, e) for ax, p, s, e in gr
            if ax == axis and not (e < lo - tol or s > hi + tol)]


def main() -> int:
    ents, blocks, layers = parse_dxf(sys.argv[1] if len(sys.argv) > 1 else "cad/project2.dxf")
    result = {}
    for plan in ("L1", "L2"):
        w, gr = load(ents, plan)
        print("=" * 78)
        print(f"【{plan}】{'一层' if plan == 'L1' else '二层'}"
              f"   建筑坐标 mm，西南角原点，外轮廓 {SPAN:.0f}×{SPAN:.0f}")

        walls, openings = [], []
        # 外墙（四面）
        specs = [("v", 50.0, "W-西外墙"), ("v", SPAN - 50, "W-东外墙"),
                 ("h", 50.0, "W-南外墙"), ("h", SPAN - 50, "W-北外墙")]
        # 内墙（实测轴线上取几条主要的）
        for at in (2200.0, 6050.0):
            specs.append(("v", at, f"W-内纵@{at:.0f}"))
        for at in (2200.0, 6050.0):
            specs.append(("h", at, f"W-内横@{at:.0f}"))

        for axis, at, name in specs:
            cov = coverage(w, axis, at)
            if not cov:
                continue
            hs = holes(cov, 0.0, SPAN)
            walls.append({"name": name, "axis": axis, "at": at, "coverage": cov})
            for a, b in hs:
                gs = green_in(gr, axis, a, b)
                # 判定：贴外墙的洞口 → 玻璃（窗）；室内墙上的 → 门
                outer = at < 200 or at > SPAN - 200
                kind = "window" if outer else "door"
                openings.append({"wall": name, "from": a, "to": b,
                                 "width": round(b - a, 1), "kind": kind,
                                 "green": len(gs) > 0})
            print(f"\n  ▸ {name}（{'竖直' if axis=='v' else '水平'}，"
                  f"{'x' if axis=='v' else 'y'}={at:.0f}）")
            print(f"      墙线覆盖: {[(round(a),round(b)) for a,b in cov]}")
            for a, b in hs:
                gs = green_in(gr, axis, a, b)
                outer = at < 200 or at > SPAN - 200
                print(f"      洞口 {a:>6.0f}..{b:>6.0f} 宽 {b-a:>6.0f}  "
                      f"→ {'墙上的玻璃洞' if outer else '门'}   "
                      f"（该处绿色段 {len(gs)} 条）")
        result[plan] = {"walls": walls, "openings": openings}

    # 中庭
    print("\n" + "=" * 78)
    print(f"【中庭（两层共用）】x {COURT[0]:.0f}..{COURT[2]:.0f}  "
          f"y {COURT[1]:.0f}..{COURT[3]:.0f}   "
          f"{COURT[2]-COURT[0]:.0f} × {COURT[3]-COURT[1]:.0f} mm")
    print("   · 四壁是墙（内墙 2200 / 6050）")
    print("   · 顶上玻璃")
    print("   · **没有地板** → 一二层楼板都要挖这个洞")

    with open("cad/project2_plan.json", "w", encoding="utf-8") as f:
        json.dump({"openings": result, "court": COURT,
                   "params": {"wall_h": WALL_H, "floor_t": FLOOR_T,
                              "wall_t": WALL_T, "span": SPAN}},
                  f, ensure_ascii=False, indent=1)
    print("\n已写出 cad/project2_plan.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
