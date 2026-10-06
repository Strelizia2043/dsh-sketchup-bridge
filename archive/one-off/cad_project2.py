#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分析 project2.dxf：把两层平面拆成墙 / 洞口 / 玻璃房间，并打印可核对清单。

用户给的语义（原话）：
  · 红色的全部都是标注的 dimension
  · 标注×5 = mm（经几何印证：1 图纸单位 = 50mm）
  · 粉色的是家具，尺寸形制不严格，别太夸张就行
  · 右下角圆形 1/4 白色的是旋转楼梯（左边一层、右边二层）
  · 层高约 2700mm
  · **整个方矩形房间中间那一块绿色的是玻璃**
  · **墙上面开孔的绿色也是玻璃**
  · **只有在房间内凿开的才是门**
  · 地板厚 100mm，**地板不是家具**

⚠️ 这张图最容易踩的坑：door 图层和 windoes 图层**同为绿色 ACI 3**，
   而且**同一个门洞里既有 door 也有 windoes 的线段**（门洞两侧是玻璃隔断）。
   所以"是门还是玻璃"不能靠图层名判，得靠**位置**：
     · 贴在**外墙**上的洞口 → 墙上的玻璃洞
     · 落在**室内隔墙**上的洞口 → 门
     · 围成一个**闭合矩形**的绿色 → 玻璃房间
"""

from __future__ import annotations

import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dxf_import import parse_dxf, segs_of  # noqa: E402

MM_PER_UNIT = 50.0          # 用户确认：平面图总宽 165 单位 = 8250mm
WALL_T = 2.0                # 成对墙线间距 → 100mm
FLOOR_T = 100.0             # 用户给：地板厚 10cm
WALL_H = 2700.0             # 用户给：层高约 2.7m

# 两张平面图的范围（实测）
PLANS = {
    "L1": (2940.0, 3115.0, 7145.0, 7330.0),   # 左 = 一层
    "L2": (3140.0, 3315.0, 7145.0, 7330.0),   # 右 = 二层
}


def mm(v: float) -> float:
    return round(v * MM_PER_UNIT, 1)


def collect(ents, plan):
    bx0, bx1, by0, by1 = PLANS[plan]
    out = collections.defaultdict(list)
    for e in ents:
        if e["layer"] == "Defpoints" or (e.get("block") or "").startswith("*D"):
            continue
        for s in segs_of(e):
            (ax, ay), (bx, by) = s
            if not (bx0 - 1 <= ax <= bx1 + 1 and bx0 - 1 <= bx <= bx1 + 1):
                continue
            if not (by0 <= ay <= by1 and by0 <= by <= by1):
                continue
            out[e["layer"]].append(s)
    return out


def axis_lines(segs, tol=0.01):
    """把线段分成水平/垂直两类，返回 (水平, 垂直)，每条为 (固定坐标, 起, 止)。"""
    H, V = [], []
    for (ax, ay), (bx, by) in segs:
        if abs(ay - by) < tol:
            H.append((round(ay, 2), round(min(ax, bx), 2), round(max(ax, bx), 2)))
        elif abs(ax - bx) < tol:
            V.append((round(ax, 2), round(min(ay, by), 2), round(max(ay, by), 2)))
    return H, V


def merge_coords(vals, tol=0.6):
    """把相近的坐标并成一条线（墙的两个面线间距 1，用 tol 分不开，所以要分组）。"""
    vals = sorted(set(round(v, 2) for v in vals))
    groups, cur = [], [vals[0]] if vals else []
    for v in vals[1:]:
        if v - cur[-1] <= tol:
            cur.append(v)
        else:
            groups.append(cur)
            cur = [v]
    if cur:
        groups.append(cur)
    return [round(sum(g) / len(g), 2) for g in groups]


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "cad/project2.dxf"
    ents, blocks, layers = parse_dxf(path)

    print("=" * 74)
    print("project2.dxf 分析  （1 图纸单位 = %.0fmm，用户确认）" % MM_PER_UNIT)
    print("=" * 74)

    for plan in ("L1", "L2"):
        g = collect(ents, plan)
        bx0, bx1, by0, by1 = PLANS[plan]
        print(f"\n{'─' * 74}\n【{plan}】"
              f"{'一层（左）' if plan == 'L1' else '二层（右）'}"
              f"   图幅 {mm(bx1 - bx0)} × {mm(by1 - by0)} mm")
        for L in sorted(g, key=lambda z: -len(g[z])):
            H, V = axis_lines(g[L])
            print(f"   {L:<20} {len(g[L]):>5} 线段  （水平 {len(H)}, 垂直 {len(V)}）")

        # ── 墙线位置
        allw = g.get("wall", []) + g.get("wall2", []) + g.get("wallhatch", [])
        H, V = axis_lines(allw)
        ycoord = merge_coords([h[0] for h in H])
        xcoord = merge_coords([v[0] for v in V])
        print(f"\n   ▸ 墙线 X 位置（{len(xcoord)} 条）: "
              f"{[round((c - bx0) * MM_PER_UNIT) for c in xcoord]}")
        print(f"   ▸ 墙线 Y 位置（{len(ycoord)} 条）: "
              f"{[round((c - by0) * MM_PER_UNIT) for c in ycoord]}")
        if len(xcoord) >= 2:
            print(f"   ▸ 相邻 X 间距(mm): "
                  f"{[round((b - a) * MM_PER_UNIT) for a, b in zip(xcoord, xcoord[1:])]}")
        if len(ycoord) >= 2:
            print(f"   ▸ 相邻 Y 间距(mm): "
                  f"{[round((b - a) * MM_PER_UNIT) for a, b in zip(ycoord, ycoord[1:])]}")

        # ── 绿色（door + windoes）：区分"矩形的玻璃房间"与"洞口"
        green = g.get("door", []) + g.get("windoes", [])
        gh, gv = axis_lines(green)
        gx = merge_coords([v[0] for v in gv])
        gy = merge_coords([h[0] for h in gh])
        print(f"\n   ▸ 绿色构件的 X 位置: {[round((c - bx0) * MM_PER_UNIT) for c in gx]}")
        print(f"   ▸ 绿色构件的 Y 位置: {[round((c - by0) * MM_PER_UNIT) for c in gy]}")

        # 绿色线段里较长的那些 → 大概率是"洞口的宽度"
        gl = sorted([abs(b - a) for _, a, b in gh] + [abs(b - a) for _, a, b in gv],
                    reverse=True)
        print(f"   ▸ 绿色线段长度前 12（mm）: {[round(v * MM_PER_UNIT) for v in gl[:12]]}")

    print(f"\n{'─' * 74}")
    print("提示：绿色构件要按**位置**判性质——"
          "贴外墙的洞口=墙上的玻璃；围成闭合矩形的=玻璃房间；室内隔墙上的=门。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
