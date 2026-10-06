#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图纸分析探针：把"看图"变成"量图"。

用途（配合 reading_checklist.md 的第 2 步）：
  1. 报告图片尺寸、灰度分布、墨迹密度——判断是不是能用的图
  2. **自动检测长直线**（墙线、轴网线、尺寸线）——用来核对轴网是否等距
  3. 裁剪放大任意区域——用来读清我肉眼看不准的尺寸数字
  4. 按用户给的像素坐标量距离——这是"真的能算出来"的支撑

用法：
    python plan_probe.py plan.png --info
    python plan_probe.py plan.png --lines --min-run 200
    python plan_probe.py plan.png --crop 300 200 900 700 --out crop.png --zoom 3
    python plan_probe.py plan.png --dist 300 200 300 900
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

import argparse
import json
import os
import sys

try:
    from PIL import Image
except ImportError:
    print("需要 Pillow：请用工作区自带的 python 运行")
    raise SystemExit(2)


def info(path: str) -> dict:
    im = Image.open(path)
    g = im.convert("L")
    px = list(g.getdata())
    n = len(px)
    dark = sum(1 for v in px if v < 128)
    mid = sum(1 for v in px if 128 <= v < 220)
    light = n - dark - mid
    return {
        "path": os.path.abspath(path),
        "size_px": im.size,
        "mode": im.mode,
        "format": im.format,
        "gray_mean": round(sum(px) / n, 1),
        "ink_ratio_dark": round(dark / n, 4),
        "ink_ratio_mid": round(mid / n, 4),
        "background_ratio": round(light / n, 4),
    }


def detect_lines(path: str, min_run: int, max_lines: int) -> dict:
    """按行/列统计长直线。返回像素坐标与线长。

    原理：一条水平墙线会让某一行的"墨迹占比"和"最长连续墨迹长度"同时变高。
    够用且不依赖 OpenCV。
    """
    g = Image.open(path).convert("L")
    w, h = g.size
    px = g.load()
    thresh = 160

    # ── 先定位建筑跨度，供"墨迹占比"判据使用
    #
    # 为什么要先定位：判定一行是不是墙，不能只看"最长连续游程"。
    # 墙常被**内墙 T 形接头**和**洞口**打断——实测（参数扫描）：
    #   3000×9000 窄长房的底部外墙被打断成多段，
    #   没有一段达到门槛 → 整条墙漏检 → 建筑方向都判错。
    #
    # 跨度怎么定，我踩了两次：
    #   · 第一版用"整行墨迹 ≥ 图宽 20%"：小房子（3000×2400）算出 y=240..581，
    #     而真实建筑是 y=571..752 —— 底部墙占比不够，被排除在跨度外，fill 分母就错了。
    #   · 第二版改成"存在 ≥15px 连续墨迹"：**还是错**，因为尺寸线和轴网
    #     本身都是很长的连续直线，203 行、252 列全部通过。
    #
    # 正确判据要同时看**两个尺度**：
    #   · 沿该行的**短游程**（≥15px）—— 证明这里有"墙那样厚的实心段"，
    #     而不是细线；尺寸线只有 1~2px，过不了这一关
    #   · 这样的行要**连续出现多行**（≥ 图幅的 1.5%）—— 墙是一条**带**，
    #     而孤立的粗线不是
    def wall_bands(fixed_is_row: bool):
        """返回所有"墙带"的 (起, 止) 行/列范围。"""
        length_total = w if fixed_is_row else h
        other = h if fixed_is_row else w
        short = max(15, int(length_total * 0.05))   # 沿该方向要有这么长的实心段
        flags = []
        for fixed in range(other):
            longest = 0
            cur = 0
            for v in range(length_total):
                val = px[v, fixed] if fixed_is_row else px[fixed, v]
                if val < thresh:
                    cur += 1
                    if cur > longest:
                        longest = cur
                else:
                    cur = 0
            flags.append(longest >= short)
        min_band = max(3, int(other * 0.015))
        bands = []
        i = 0
        while i < other:
            if flags[i]:
                j = i
                while j + 1 < other and flags[j + 1]:
                    j += 1
                if j - i + 1 >= min_band:
                    bands.append((i, j))
                i = j + 1
            else:
                i += 1
        return bands

    def axis_profile(fixed_is_row: bool, span: tuple[int, int] | None):
        length_total = w if fixed_is_row else h
        other = h if fixed_is_row else w
        rows = []
        lo, hi = (span if span else (0, length_total - 1))
        span_len = max(1, hi - lo + 1)
        for fixed in range(other):
            longest = 0
            cur = 0
            total = 0
            inked_span = 0
            for v in range(length_total):
                val = px[v, fixed] if fixed_is_row else px[fixed, v]
                if val < thresh:
                    cur += 1
                    total += 1
                    if cur > longest:
                        longest = cur
                else:
                    cur = 0
                if lo <= v <= hi and val < thresh:
                    inked_span += 1
            fill = inked_span / span_len
            rows.append((fixed, longest, round(total / length_total, 3), fill))
        return rows

    h_bands = wall_bands(True)
    v_bands = wall_bands(False)

    def span_of(bands):
        if not bands:
            return None
        return (bands[0][0], bands[-1][1])

    span_y = span_of(h_bands)   # 横墙所在的行 → 建筑在 y 方向的跨度
    span_x = span_of(v_bands)   # 竖墙所在的列 → 建筑在 x 方向的跨度

    def scan(fixed_is_row: bool, limit: int):
        length = w if fixed_is_row else h
        other = h if fixed_is_row else w
        rows = axis_profile(fixed_is_row, span_x if fixed_is_row else span_y)
        out = []
        for fixed, longest, ratio, fill in rows:
            # 判定"是不是墙"用**两条互补的判据**：
            #   · 最长连续游程够长（完整无洞口的墙）
            #   · 或 在建筑跨度内墨迹占比够高（被接头/洞口打断的墙）
            if longest >= limit or fill >= 0.55:
                out.append((fixed, longest, ratio, fill))
        return out

    def merge(rows):
        merged = []
        for fixed, longest, ratio, fill in rows:
            if merged and fixed - merged[-1]["last"] <= 2:
                merged[-1]["last"] = fixed
                merged[-1]["members"].append(fixed)
                if longest > merged[-1]["longest"]:
                    merged[-1]["longest"] = longest
                merged[-1]["ink"] = max(merged[-1]["ink"], ratio)
                if fill > merged[-1]["fill"]:
                    merged[-1]["fill"] = fill
            else:
                merged.append({"first": fixed, "last": fixed, "members": [fixed],
                               "longest": longest, "ink": ratio, "fill": fill})
        for m in merged:
            m["center"] = round(sum(m["members"]) / len(m["members"]), 1)
            m["thickness_px"] = len(m["members"])
            m["fill"] = round(m["fill"], 3)
            m.pop("members")
        merged.sort(key=lambda m: -m["longest"])
        return merged[:max_lines]

    h_lines = merge(scan(True, min_run))
    v_lines = merge(scan(False, min_run))

    # 从检测到的强线之间算间距（用于核对"轴网是否等距"）
    def spacings(lines):
        cs = sorted(round(m["center"]) for m in lines)
        return [cs[i + 1] - cs[i] for i in range(len(cs) - 1)]

    return {
        "size_px": [w, h],
        "min_run": min_run,
        "horizontal_lines": h_lines,
        "vertical_lines": v_lines,
        "horizontal_spacings_px": spacings(h_lines),
        "vertical_spacings_px": spacings(v_lines),
    }


def crop(path: str, box, out: str, zoom: float) -> dict:
    im = Image.open(path).convert("RGB")
    x0, y0, x1, y1 = box
    x0, x1 = min(x0, x1), max(x0, x1)
    y0, y1 = min(y0, y1), max(y0, y1)
    piece = im.crop((x0, y0, x1, y1))
    if zoom and zoom != 1:
        piece = piece.resize((int(piece.width * zoom), int(piece.height * zoom)), Image.LANCZOS)
    piece.save(out)
    return {"out": os.path.abspath(out), "crop_box": [x0, y0, x1, y1],
            "out_size_px": piece.size, "zoom": zoom}


def dist(path: str, a, b) -> dict:
    g = Image.open(path)
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    return {
        "size_px": list(g.size),
        "from_px": list(a), "to_px": list(b),
        "dx_px": dx, "dy_px": dy,
        "distance_px": round((dx * dx + dy * dy) ** 0.5, 2),
        "note": "像素距离。换算成毫米还需要一个已知的参考尺寸（图纸上的标注），"
                "由 DSH 用 scale_from_reference 计算，不在这里猜。",
    }


def scale_from_reference(d_px: float, known_mm: float, target_px: float) -> dict:
    """用一条已知标注做基准，换算其他像素距离。这是 B 级推算的唯一合法工具。"""
    mm_per_px = known_mm / d_px
    return {
        "mm_per_px": round(mm_per_px, 5),
        "known_distance_px": d_px,
        "known_distance_mm": known_mm,
        "target_px": target_px,
        "target_mm": round(target_px * mm_per_px, 1),
        "basis": f"{target_px}px × ({known_mm}mm / {d_px}px)",
        "caveat": "这是按比例尺推算的 B/C 级数据。若图纸比例不准或图像有透视/拉伸，"
                  "结果会偏。关键尺寸仍应以图上标注为准。",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="图纸分析探针")
    ap.add_argument("image")
    ap.add_argument("--info", action="store_true")
    ap.add_argument("--lines", action="store_true")
    ap.add_argument("--min-run", type=int, default=200, help="一条线至少多长才算（像素）")
    ap.add_argument("--max-lines", type=int, default=25)
    ap.add_argument("--crop", nargs=4, type=int, metavar=("X0", "Y0", "X1", "Y1"))
    ap.add_argument("--out", default="crop.png")
    ap.add_argument("--zoom", type=float, default=2.0)
    ap.add_argument("--dist", nargs=4, type=int, metavar=("X1", "Y1", "X2", "Y2"))
    ap.add_argument("--scale", nargs=3, type=float,
                    metavar=("KNOWN_PX", "KNOWN_MM", "TARGET_PX"),
                    help="用已知标注换算目标距离（B 级推算）")
    args = ap.parse_args()

    if not os.path.exists(args.image):
        print(f"找不到图片: {args.image}")
        return 1

    did = False
    if args.info or not any([args.lines, args.crop, args.dist, args.scale]):
        print(json.dumps(info(args.image), ensure_ascii=False, indent=2))
        did = True
    if args.lines:
        print(json.dumps(detect_lines(args.image, args.min_run, args.max_lines),
                         ensure_ascii=False, indent=2))
        did = True
    if args.crop:
        print(json.dumps(crop(args.image, args.crop, args.out, args.zoom),
                         ensure_ascii=False, indent=2))
        did = True
    if args.dist:
        print(json.dumps(dist(args.image, args.dist[:2], args.dist[2:]),
                         ensure_ascii=False, indent=2))
        did = True
    if args.scale:
        print(json.dumps(scale_from_reference(*args.scale), ensure_ascii=False, indent=2))
        did = True
    return 0 if did else 0


if __name__ == "__main__":
    raise SystemExit(main())
