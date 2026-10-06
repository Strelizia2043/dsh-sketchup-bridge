#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成一张**合成的住宅平面图**，用于检验读图工具链。

为什么需要它：`plan_probe.py` 只在 SketchUp 截图（深色粗线、无任何标注）上跑过，
从没在**真正的建筑图**上验证过。真实图纸的特征完全不同：
  * 墙线是双线（墙厚）＋填色（poché）
  * 尺寸链是细线 + 45° 起止短线 + 界线
  * 轴网是点划线 + 端部圆圈编号
  * 门窗有专门符号（门的开启弧、窗的四线）
  * 有房间名、面积、图签

所以造一张来测。**重要**：这只是工具链验证——它能证明"量图工具能不能用"，
**证明不了"我能读懂真实图纸"**。真图纸的线型、字体、图例千变万化。

图纸内容（全部是我给定的已知真值，用来对照）：
    建筑 6000 × 4800mm，外墙 240 厚，内墙 120 厚，内墙轴线 x=3600
    门洞 M1 900mm（南墙）、M2 800mm（内墙）
    窗洞 C1 1500mm（南墙）、C2 1200mm（东墙）
    比例 1:50（按 96dpi 换算）

用法：python make_test_drawing.py [输出路径]
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
    for _d in ['.', 'tools/cad', 'tools/img', 'tools/build']:
        _p = _op.normpath(_op.join(_cur, _d))
        if _p not in _sys.path:
            _sys.path.insert(0, _p)


_dsh_bootstrap()

import math
import os
import sys

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("需要 Pillow")
    raise SystemExit(2)

# ── 比例：1:50，96dpi → 1 实物毫米 = (1/50) 纸面毫米 = (1/50)*(96/25.4) 像素
SCALE = 50.0
PX_PER_PAPER_MM = 96 / 25.4


def mm2px(mm_real: float) -> float:
    return (mm_real / SCALE) * PX_PER_PAPER_MM


# ── 已知真值（默认方案）
W_MM, H_MM = 6000, 4800
EXT_T, INT_T = 240, 120
M1, M2 = 900, 800
C1, C2 = 1500, 1200
INT_X = 3600
M1_U, C1_U, M2_V = 900, 2600, 1900

MARGIN = 250
CANVAS_W = int(mm2px(W_MM) + MARGIN * 2)
CANVAS_H = int(mm2px(H_MM) + MARGIN * 2 + 80)

OX = MARGIN
OY = CANVAS_H - MARGIN - 80

INK = (0, 0, 0)
WALL_FILL = (55, 55, 55)
GRID = (120, 120, 120)
TEXT = (15, 15, 15)


# 图面原点。支持 --scale 后画布尺寸会变，所以不能再用"模块级常量"读它——
# 用 globals() 去改模块常量太脏，改成 main() 里显式设置这两个模块级变量，
# X()/Y() 在**调用时**读取当前值。
_ORIGIN = {"x": 0.0, "y": 0.0}


def X(mm_x: float) -> float:
    return _ORIGIN["x"] + mm2px(mm_x)


def Y(mm_y: float) -> float:
    return _ORIGIN["y"] - mm2px(mm_y)


def font(size: int):
    for name in ("msyh.ttc", "simhei.ttf", "arial.ttf", "DejaVuSans.ttf"):
        for root in (r"C:\Windows\Fonts", "/usr/share/fonts"):
            p = os.path.join(root, name)
            if os.path.exists(p):
                try:
                    return ImageFont.truetype(p, size)
                except OSError:
                    pass
    return ImageFont.load_default()


def rect(d, x0, y0, x1, y1, **kw):
    """安全矩形。PIL 要求 x0<=x1、y0<=y1；而 Y() 是翻转坐标，
    算出来的 y 顺序不保证，所以统一在这里排序（别在调用处手动处理）。"""
    d.rectangle([min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)], **kw)


def dashed(d, p0, p1, dash=14, gap=6, fill=GRID, width=1):
    x0, y0 = p0
    x1, y1 = p1
    total = math.hypot(x1 - x0, y1 - y0)
    if total == 0:
        return
    ux, uy = (x1 - x0) / total, (y1 - y0) / total
    t = 0.0
    while t < total:
        t2 = min(t + dash, total)
        d.line([(x0 + ux * t, y0 + uy * t), (x0 + ux * t2, y0 + uy * t2)], fill=fill, width=width)
        t = t2 + gap


def tick(d, x, y, s=7):
    """尺寸链的 45° 起止短线（建筑制图惯例）"""
    d.line([(x - s, y + s), (x + s, y - s)], fill=INK, width=1)


def dim_h(d, y_axis, nodes_mm, labels_mm=None):
    """水平尺寸链：在 y_axis 处，节点为 nodes_mm"""
    d.line([(X(nodes_mm[0]), y_axis), (X(nodes_mm[-1]), y_axis)], fill=INK, width=1)
    for p in nodes_mm:
        tick(d, X(p), y_axis)
        d.line([(X(p), y_axis), (X(p), y_axis + 30)], fill=GRID, width=1)
    if labels_mm:
        f = font(17)
        for i, txt in enumerate(labels_mm):
            a, b = nodes_mm[i], nodes_mm[i + 1]
            t = str(txt)
            tw = d.textlength(t, font=f)
            d.text(((X(a) + X(b)) / 2 - tw / 2, y_axis - 20), t, fill=TEXT, font=f)


def dim_v(d, x_axis, nodes_mm, labels_mm=None):
    """竖直尺寸链（文字横排，避免依赖字形旋转）"""
    d.line([(x_axis, Y(nodes_mm[0])), (x_axis, Y(nodes_mm[-1]))], fill=INK, width=1)
    for p in nodes_mm:
        tick(d, x_axis, Y(p))
        d.line([(x_axis, Y(p)), (x_axis + 30, Y(p))], fill=GRID, width=1)
    if labels_mm:
        f = font(17)
        for i, txt in enumerate(labels_mm):
            a, b = nodes_mm[i], nodes_mm[i + 1]
            t = str(txt)
            tw = d.textlength(t, font=f)
            d.text((x_axis - 14 - tw, (Y(a) + Y(b)) / 2 - 9), t, fill=TEXT, font=f)


def bubble(d, x, y, label, r=15):
    d.ellipse([x - r, y - r, x + r, y + r], outline=INK, width=2)
    f = font(18)
    tw = d.textlength(label, font=f)
    d.text((x - tw / 2, y - 10), label, fill=INK, font=f)


def main() -> int:
    import argparse
    # `global` 声明必须在使用这些名字**之前**（踩过：
    # 把 `default=SCALE` 写在前面会报 "used prior to global declaration"）。
    global SCALE, W_MM, H_MM, EXT_T, INT_T, M1, M2, C1, C2, INT_X, M1_U, C1_U, M2_V
    ap = argparse.ArgumentParser(description="生成带已知真值的合成平面图")
    ap.add_argument("out", nargs="?", default="test_plan.png")
    ap.add_argument("--scale", type=float, default=SCALE,
                    help="图纸比例分母（50 = 1:50，100 = 1:100）。"
                         "真实图纸 1:100 很常见，而比例会直接改变 mm/px")
    ap.add_argument("--units", default="mm", choices=["mm", "cm"],
                    help="**标注文字**里写的单位（不影响几何，只影响图上的文字与真值报告）")
    # ── 几何参数化：默认值等于原常量，所以**不加参数时行为完全不变**
    ap.add_argument("--w", type=float, default=W_MM, help="建筑宽度 mm")
    ap.add_argument("--h", type=float, default=H_MM, help="建筑进深 mm")
    ap.add_argument("--ext-t", type=float, default=EXT_T, help="外墙厚 mm")
    ap.add_argument("--int-t", type=float, default=INT_T, help="内墙厚 mm")
    ap.add_argument("--m1", type=float, default=M1, help="南墙门洞宽 mm")
    ap.add_argument("--c1", type=float, default=C1, help="南墙窗洞宽 mm")
    ap.add_argument("--c2", type=float, default=C2, help="东墙窗洞宽 mm")
    ap.add_argument("--m2", type=float, default=M2, help="内墙门洞宽 mm")
    ap.add_argument("--int-x", type=float, default=INT_X, help="内墙轴线位置 mm")
    # 洞口起点也要可调：原来是硬编码的，参数化建筑尺寸后会画出**越界的外墙**
    # （南墙第三段起点 4100 而墙长只有 3000），图就废了还以为是提取器的问题。
    ap.add_argument("--m1-u", type=float, default=None, help="南墙门洞起点 mm（默认按比例）")
    ap.add_argument("--c1-u", type=float, default=None, help="南墙窗洞起点 mm（默认按比例）")
    ap.add_argument("--m2-v", type=float, default=None, help="内墙门洞起点 mm（默认按比例）")
    args = ap.parse_args()

    SCALE = args.scale
    W_MM, H_MM = args.w, args.h
    EXT_T, INT_T = args.ext_t, args.int_t
    M1, C1, C2, M2 = args.m1, args.c1, args.c2, args.m2
    INT_X = args.int_x
    # 洞口起点的默认值按墙长成比例，这样参数化任意尺寸都不会越界。
    # 比例取**精确分数**而不是小数：原方案是 M1@900/6000 = 3/20、
    # C1@2600/6000 = 13/30、M2@1900/4800 = 19/48。
    # 用 0.433 这种近似会让默认输出**不再与基准图逐像素一致**（实测差 240）。
    M1_U = args.m1_u if args.m1_u is not None else round(W_MM * 3 / 20)
    C1_U = args.c1_u if args.c1_u is not None else round(W_MM * 13 / 30)
    M2_V = args.m2_v if args.m2_v is not None else round(H_MM * 19 / 48)
    # 图幅与所有几何换算都依赖 SCALE，必须在用它之前重算
    canvas_w = int(mm2px(W_MM) + MARGIN * 2)
    canvas_h = int(mm2px(H_MM) + MARGIN * 2 + 80)
    _ORIGIN["x"] = MARGIN
    _ORIGIN["y"] = canvas_h - MARGIN - 80

    out = args.out
    img = Image.new("RGB", (canvas_w, canvas_h), "white")
    d = ImageDraw.Draw(img)
    et, it = mm2px(EXT_T), mm2px(INT_T)

    # ── 轴网
    for i, ax in enumerate([0, INT_X, W_MM], 1):
        dashed(d, (X(ax), Y(-800)), (X(ax), Y(H_MM + 800)))
        bubble(d, X(ax), Y(-800) - 36, str(i))
        bubble(d, X(ax), Y(H_MM + 800) + 36, str(i))
    for j, ay in enumerate([0, H_MM]):
        dashed(d, (X(-800), Y(ay)), (X(W_MM + 800), Y(ay)))
        lab = "A" if j == 0 else "B"
        bubble(d, X(-800) - 36, Y(ay), lab)
        bubble(d, X(W_MM + 800) + 36, Y(ay), lab)

    m1_a, m1_b = M1_U, M1_U + M1
    c1_a, c1_b = C1_U, C1_U + C1
    m2_a, m2_b = M2_V, M2_V + M2
    c2_a, c2_b = H_MM / 2 - C2 / 2, H_MM / 2 + C2 / 2

    # ── 合法性校验
    #
    # 踩过的坑：洞口起点原来是**硬编码**的（M1 在 900、C1 在 2600），
    # 参数化建筑尺寸后没同步，于是 `--w 3000` 时南墙分段变成
    # [(0,900), (1800,2600), (4100,3000)] —— 第三段起点 4100 超过墙长 3000，
    # 外墙根本没画出来，图里只剩内墙，提取结果自然全错。
    # **造图器画错图，却让我以为提取器有 bug。**
    problems = []
    if m1_b > W_MM or c1_b > W_MM:
        problems.append(f"南墙洞口超出墙长：M1 到 {m1_b}、C1 到 {c1_b}，而墙长只有 {W_MM}")
    if m1_b > c1_a:
        problems.append(f"南墙 M1 与 C1 重叠：M1 到 {m1_b}，C1 从 {c1_a} 起")
    if m2_b > H_MM:
        problems.append(f"内墙门洞超出墙长：M2 到 {m2_b}，而墙长只有 {H_MM}")
    if not (0 < INT_X < W_MM):
        problems.append(f"内墙轴线 x={INT_X} 不在 (0, {W_MM}) 之内")
    if c2_a < m2_a and c2_b > m2_b and abs(INT_X - W_MM) < 1:
        problems.append("C2 与 M2 位置冲突")
    if problems:
        print("❌ 方案不合法，不生成图纸：")
        for p in problems:
            print("   · " + p)
        return 2

    # ── 外墙
    for a, b in [(0, m1_a), (m1_b, c1_a), (c1_b, W_MM)]:      # 南墙，绕开门窗
        x0 = X(a) - (et / 2 if a == 0 else 0)
        x1 = X(b) + (et / 2 if b == W_MM else 0)
        rect(d, x0, Y(0) - et / 2, x1, Y(0) + et / 2, fill=WALL_FILL, outline=INK)
    rect(d, X(0) - et / 2, Y(H_MM) - et / 2, X(W_MM) + et / 2, Y(H_MM) + et / 2,
         fill=WALL_FILL, outline=INK)                          # 北墙
    rect(d, X(0) - et / 2, Y(0), X(0) + et / 2, Y(H_MM),
         fill=WALL_FILL, outline=INK)                          # 西墙
    rect(d, X(W_MM) - et / 2, Y(0), X(W_MM) + et / 2, Y(c2_a),
         fill=WALL_FILL, outline=INK)                          # 东墙下段
    rect(d, X(W_MM) - et / 2, Y(c2_b), X(W_MM) + et / 2, Y(H_MM),
         fill=WALL_FILL, outline=INK)                          # 东墙上段

    # ── 门 M1：开启弧 + 门扇
    d.arc([X(m1_a), Y(0) - mm2px(M1), X(m1_a) + mm2px(M1), Y(0) + mm2px(M1)],
          180, 270, fill=INK, width=1)
    d.line([(X(m1_a), Y(0)), (X(m1_a), Y(0) - mm2px(M1))], fill=INK, width=2)

    # ── 窗 C1（南墙）四线符号
    for k in (-1.5, -0.5, 0.5, 1.5):
        yy = Y(0) + k * (et / 4)
        d.line([(X(c1_a), yy), (X(c1_b), yy)], fill=INK, width=1)
    for xx in (X(c1_a), X(c1_b)):
        d.line([(xx, Y(0) - et / 2), (xx, Y(0) + et / 2)], fill=INK, width=1)

    # ── 窗 C2（东墙）四线符号
    for k in (-1.5, -0.5, 0.5, 1.5):
        xx = X(W_MM) + k * (et / 4)
        d.line([(xx, Y(c2_a)), (xx, Y(c2_b))], fill=INK, width=1)
    for yy in (Y(c2_a), Y(c2_b)):
        d.line([(X(W_MM) - et / 2, yy), (X(W_MM) + et / 2, yy)], fill=INK, width=1)

    # ── 内墙 x=INT_X，绕开门洞 M2
    rect(d, X(INT_X) - it / 2, Y(0), X(INT_X) + it / 2, Y(m2_a),
         fill=WALL_FILL, outline=INK)
    rect(d, X(INT_X) - it / 2, Y(m2_b), X(INT_X) + it / 2, Y(H_MM),
         fill=WALL_FILL, outline=INK)
    d.arc([X(INT_X) - mm2px(M2), Y(m2_b) - mm2px(M2), X(INT_X) + mm2px(M2), Y(m2_b)],
          0, 90, fill=INK, width=1)

    # ── 房间名与面积
    f_r, f_s = font(22), font(17)
    d.text((X(1500), Y(1150)), "客厅", fill=TEXT, font=f_r)
    d.text((X(1500), Y(1300)), "17.3 m2", fill=TEXT, font=f_s)
    d.text((X(4300), Y(1150)), "卧室", fill=TEXT, font=f_r)
    d.text((X(4300), Y(1300)), "8.6 m2", fill=TEXT, font=f_s)

    # ── 尺寸链（读图工具最需要验证的部分）
    dim_h(d, Y(0) + 78, [0, m1_a, m1_b, c1_a, c1_b, W_MM],
          [m1_a, M1, c1_a - m1_b, C1, W_MM - c1_b])
    dim_h(d, Y(0) + 150, [0, W_MM], [W_MM])
    dim_v(d, X(0) - 96, [0, m2_a, m2_b, H_MM], [m2_a, M2, H_MM - m2_b])
    dim_v(d, X(0) - 168, [0, H_MM], [H_MM])

    # ── 门窗编号
    d.text((X(m1_a), Y(0) + 42), "M1", fill=TEXT, font=f_s)
    d.text((X(c1_a), Y(0) + 42), "C1", fill=TEXT, font=f_s)
    d.text((X(W_MM) + 22, Y((c2_a + c2_b) / 2)), "C2", fill=TEXT, font=f_s)
    d.text((X(INT_X) + 18, Y(m2_b) + 8), "M2", fill=TEXT, font=f_s)

    # ── 图签
    tb_y = CANVAS_H - 68
    rect(d, MARGIN, tb_y, CANVAS_W - MARGIN, CANVAS_H - 14, outline=INK, width=1)
    d.line([(MARGIN + 540, tb_y), (MARGIN + 540, CANVAS_H - 14)], fill=INK, width=1)
    d.text((MARGIN + 12, tb_y + 10), f"合成测试平面图   1:{SCALE:.0f}", fill=TEXT, font=font(20))
    d.text((MARGIN + 556, tb_y + 10), f"尺寸单位：{args.units}", fill=TEXT, font=font(20))

    img.save(out)
    print(f"已生成：{out}   画布 {img.size[0]}x{img.size[1]}px")
    print(f"比例 1:{SCALE:.0f}   换算基准：1 实物毫米 = {mm2px(1):.4f} px")
    print()
    print("已知真值（供对照）：")
    print(f"  建筑 {W_MM}x{H_MM}mm   外墙 {EXT_T}   内墙 {INT_T}   内墙轴线 x={INT_X}")
    print(f"  M1={M1}  M2={M2}  C1={C1}  C2={C2}")
    print()
    print("换算成像素的期望位置（用这些核对探针读数）：")
    for label, val in (("x=0", X(0)), ("x=900(M1起)", X(900)), ("x=1800(M1终)", X(1800)),
                       ("x=2600(C1起)", X(2600)), ("x=4100(C1终)", X(4100)),
                       ("x=6000", X(W_MM)), ("x=3600(内墙)", X(INT_X))):
        print(f"  {label:<16} -> {val:.1f}px")
    for label, val in (("y=0", Y(0)), ("y=1900(M2起)", Y(1900)), ("y=2700(M2终)", Y(2700)),
                       ("y=4800", Y(H_MM))):
        print(f"  {label:<16} -> {val:.1f}px")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
