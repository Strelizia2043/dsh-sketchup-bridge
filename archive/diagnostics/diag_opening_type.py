#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测准"洞口类型判别"的特征——先量，再决定用不用。

假设：**窗有窗框线穿过洞口**（平常见的四线窗符号），门没有（门的开启弧画在洞外）。
如果这条特征可靠，就能把洞口分成"确定是窗"和"不确定"，从而少问用户几个问题。

关键：这是"量出来的结论"，不是"我以为"。所以先对已知真值的合成图纸测：
    南墙 M1（门，真值）：洞口内应当没有贯穿线
    南墙 C1（窗，真值）：洞口内应当有 4 条贯穿线
    东墙 C2（窗，真值）：同理
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def probe(img, *args):
    r = subprocess.run([PY, os.path.join(HERE, "plan_probe.py"), img, *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return json.loads(r.stdout)


def count_lines(img, axis, band, lo, hi):
    """数洞口范围内、垂直于墙方向的暗线数量。

    axis='x'（水平墙）：洞口的"贯穿线"是水平线 → 沿 y 逐行统计，行内有一长段暗像素算一条
    axis='y'（竖直墙）：贯穿线是竖直线 → 沿 x 逐列统计
    """
    from PIL import Image
    im = Image.open(img).convert("L")
    px = im.load()
    b0, b1 = band
    runs = []
    span = hi - lo

    if axis == "x":
        for y in range(b0, b1 + 1):
            cnt = sum(1 for x in range(lo, hi) if px[x, y] < 160)
            if cnt >= span * 0.7:          # 该行大部分是暗的 → 一条贯穿线
                runs.append(y)
    else:
        for x in range(b0, b1 + 1):
            cnt = sum(1 for y in range(lo, hi) if px[x, y] < 160)
            if cnt >= span * 0.7:
                runs.append(x)

    # 合并相邻（一条粗线会占多行/多列）
    merged = 0
    prev = None
    for v in runs:
        if prev is None or v - prev > 2:
            merged += 1
        prev = v
    return merged, runs


def main() -> int:
    img = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "shots", "pipeline_plan.png")
    if not os.path.exists(img):
        print(f"找不到图纸 {img}，先跑 make_test_drawing.py")
        return 1

    lines = probe(img, "--lines", "--min-run", "120", "--max-lines", "20")
    h = sorted([l for l in lines["horizontal_lines"] if l["thickness_px"] >= 5],
               key=lambda l: l["center"])
    v = sorted([l for l in lines["vertical_lines"] if l["thickness_px"] >= 5],
               key=lambda l: l["center"])

    print("=" * 68)
    print("洞口类型判别特征测量（合成图纸，已知真值）")
    print("=" * 68)
    print()
    print("假设：窗有窗框线穿过洞口，门没有。若假设成立，贯穿线数应当明显区分。")
    print()

    # ── 南墙（水平墙）：M1 门、C1 窗
    y_wall = h[-1]
    band = (int(y_wall["first"]), int(y_wall["last"]))
    # 由 make_test_drawing 的已知像素位置换算：x=318..386 是 M1，446..560 是 C1
    cases = [
        ("南墙 M1（真值：门）", "x", band, 320, 384),
        ("南墙 C1（真值：窗）", "x", band, 448, 558),
    ]
    # ── 东墙（竖直墙）：C2 窗。真值 y 1800..3000mm，对应像素 476..386
    x_wall = v[-1]
    vband = (int(x_wall["first"]), int(x_wall["last"]))
    cases.append(("东墙 C2（真值：窗）", "y", vband, 388, 474))

    print(f"{'位置':<24}{'贯穿线数':>8}   明细")
    results = {}
    for label, axis, bd, lo, hi in cases:
        n, raw = count_lines(img, axis, bd, lo, hi)
        results[label] = n
        print(f"{label:<24}{n:>8}   {raw[:12]}")

    print()
    print("=" * 68)
    print("结论：")
    door_n = results.get("南墙 M1（真值：门）", -1)
    win_ns = [v2 for k, v2 in results.items() if "窗" in k]
    print(f"  门 的贯穿线数 = {door_n}")
    print(f"  窗 的贯穿线数 = {win_ns}")
    if win_ns and all(w >= 3 for w in win_ns) and door_n <= 1:
        print("  ✅ 假设成立：窗 ≥3 条、门 ≤1 条，特征可分")
        print("     → 可以据此把『确定是窗』标出来（confidence=medium），不必一律问用户")
    else:
        print("  ❌ 假设不成立或边界模糊，**不应**用这个特征判类型")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
