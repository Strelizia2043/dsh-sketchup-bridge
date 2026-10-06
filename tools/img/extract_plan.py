#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从平面图图像提取"建筑描述 JSON"——链路中的**读图**环节。

这是把 plan_probe 的测量能力变成结构化数据的中间层：
    图纸图像  →  extract_plan.py  →  plan.json  →  build_from_json.py  →  SketchUp 模型

方法与边界的实测依据（见 reading_checklist.md）：
  * 标定：用一条**已知真值**（图上标注的总尺寸）把像素换算成毫米
  * 墙线：用"沿墙扫厚度"法识别实心墙与洞口（不用"有没有暗像素"，那条会误判窗中线）
  * 墙厚：**不量**。只占 9~20px，相对误差 5~10%，必须由用户给或读标注
  * 房间：由墙围合推断，尺寸取外接矩形（真图上有隔墙时需人工核对）

用法：
    python extract_plan.py 图纸.png --calib 6000 --calib-px 453.5 --unit mm \\
        --outer-t 240 --inner-t 120 --name "测试住宅"
"""

from __future__ import annotations


import os
import sys
import tempfile
import numpy as np
from PIL import Image

import argparse
import json
import subprocess

# --- DSH 路径修正（重组后自动加，见 fix_imports.py）
def _dsh_bootstrap():
    """把依赖目录加进 sys.path（重组目录后必需）。

    ⚠️ 两个坑：
      1. 不能依赖模块级的 `import os` —— 本函数在文件顶部就被调用，
         那时 `import os` 还没执行。所以在**函数体内** import。
      2. 不能假设 `os.path.dirname(__file__)` 就是依赖所在目录：
         脚本在 tools/ 子目录，而 sk_client.py 在**根目录**，要逐级上溯。
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

# 工具定位：重组目录后脚本在 tools/* 下，用 tool() 按名字找（见 dsh_paths.py）
from dsh_paths import tool as _tool, tool_rel as _tool_rel

def _op_root():
    import os.path as _o
    _c = _o.dirname(_o.abspath(__file__))
    for _ in range(5):
        if _o.exists(_o.join(_c, 'sk_client.py')):
            return _c
        _p = _o.dirname(_c)
        if _p == _c:
            break
        _c = _p
    return _o.path.dirname(_o.path.abspath(__file__))

# 工作区根目录（含 sk_client.py 的那一层）。脚本搬到 tools/ 子目录后，
# 产物与基准图的路径必须以**根目录**为基准，不能用 __file__ 所在目录。
ROOT = _op_root()


HERE = os.path.dirname(os.path.abspath(__file__))
PROBE = _tool("plan_probe.py")


def run_probe(img: str, *args) -> dict:
    r = subprocess.run([sys.executable, PROBE, img, *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"探针失败: {r.stderr[:400]}")
    return json.loads(r.stdout)


def _pick_walls(vlines: list, hlines: list) -> tuple[list, list, str]:
    """按**相对厚度**挑出真正的墙线。返回 (竖墙, 横墙, 说明)。

    为什么不能用绝对阈值（参数扫描扫出来的系统性缺陷）：
        原来写死 `thickness_px >= 5`。图幅小的时候墙只有 1~3px，
        整条被滤掉 → "墙线不足"打回；而**尺寸线也是 1~3px**，
        所以把阈值降到 3 并不能解决，只会把尺寸线放进来。
        实测：1:20 放大图墙线被滤到只剩 1 条；3000×9000 的窄房子
        横向墙只剩 1 条 → 建筑方向都判错了（H 差 1494mm）。

    正确判据是**相对**的：真正的墙是图里**最厚的那批线**。
    尺寸线、图签、索引线都显著更细。所以取全部候选里最大厚度的 30% 当门槛。
    """
    allt = [l["thickness_px"] for l in (vlines + hlines)]
    if not allt:
        return [], [], "没有候选线"
    tmax = max(allt)
    cut = max(2, int(round(tmax * 0.30)))
    v = sorted([l for l in vlines if l["thickness_px"] >= cut], key=lambda l: l["center"])
    h = sorted([l for l in hlines if l["thickness_px"] >= cut], key=lambda l: l["center"])
    note = f"最厚 {tmax}px，厚度门槛取 {cut}px（相对最厚的 30%）"
    return v, h, note


def _line_min_run(path: str) -> int:
    """线长门槛。**必须与提取主流程一致**：按各方向自己的尺寸算，取宽松的那个。
    测试台也要用它，否则会用在更严的门槛下得到的线去比较。"""
    w_px, h_px = _image_size(path)
    return min(max(24, int(w_px * 0.10)), max(24, int(h_px * 0.10)))


def _image_size(path: str) -> tuple[int, int]:
    """图幅 (宽, 高)。用来把"最短线长"等阈值按**各方向自己的尺寸**
    设定，而不是都用长边——水平墙的长度受图宽限制、竖直墙受图高限制，
    用统一的长边门槛对窄方向必然过严（1:100 图纸上实测栽过）。"""
    from PIL import Image
    with Image.open(path) as im:
        return im.size


def _image_max_dim(path: str) -> int:
    w, h = _image_size(path)
    return max(w, h)


# ── 自动纠偏（deskew）
#
# 为什么必须做：退化测试台量出来的结论是**歪斜是唯一的致命退化**：
#   1° → 洞口位置偏 46~54mm（还能用）
#   3° → 洞口宽错 3 米、内墙丢失（彻底崩）
# 而扫描件歪斜 1~3° 极其常见，手机拍照更甚。
#
# 做法：**投影方差最大化**——把图按候选角度旋转后做行/列投影，
# 文字和线条对齐时投影直方图的方差最大。这个方法不需要 Hough，
# 对细线、断线、灰度图都稳，代价是每试一个角度要跑一遍投影。
def deskew_image(path: str, out_path: str, max_deg: float = 6.0,
                 step: float = 0.25, coarse_deg: float = 2.0) -> dict:
    from PIL import Image
    import numpy as np

    with Image.open(path) as im0:
        im = im0.convert("L")
    arr0 = np.asarray(im, dtype=np.float32)
    # 二值化再投影：灰度渐变会淹没方差信号。
    # 阈值取 Otsu，而不是写死 160——低对比扫描件的墨线可能整体偏灰。
    thr = _otsu_threshold(arr0)
    ink0 = (arr0 < thr).astype(np.float32)

    def score(angle: float) -> float:
        if abs(angle) < 1e-6:
            ink = ink0
        else:
            r = im.rotate(angle, resample=Image.BILINEAR, fillcolor=255)
            a = np.asarray(r, dtype=np.float32)
            ink = (a < thr).astype(np.float32)
        rows = ink.sum(axis=1)
        cols = ink.sum(axis=0)
        return float(rows.var() + cols.var())

    # 两遍搜索：先粗（步长 coarse），再在最优附近细（步长 step）
    best_a, best_s = 0.0, score(0.0)
    a = -max_deg
    while a <= max_deg + 1e-9:
        s = score(a)
        if s > best_s:
            best_a, best_s = a, s
        a += coarse_deg
    lo, hi = best_a - coarse_deg, best_a + coarse_deg
    a = lo
    while a <= hi + 1e-9:
        s = score(a)
        if s > best_s:
            best_a, best_s = a, s
        a += step

    if abs(best_a) < step / 2:
        if out_path != path:
            Image.open(path).save(out_path)
        return {"angle": 0.0, "applied": False, "thr": round(thr, 1)}

    r = im0.convert("L").rotate(best_a, resample=Image.BICUBIC, fillcolor=255)
    r.save(out_path)
    return {"angle": round(best_a, 2), "applied": True, "thr": round(thr, 1)}


def _otsu_threshold(arr) -> float:
    """Otsu 自适应阈值。写死 160 在低对比扫描件上会失效——
    合成图是纯黑 0/纯白 255 所以随便都对，真实扫描件不是。"""
    import numpy as np
    hist, _ = np.histogram(arr, bins=256, range=(0, 256))
    total = hist.sum()
    if total == 0:
        return 160.0
    omega = np.cumsum(hist) / total
    mu = np.cumsum(hist * np.arange(256)) / total
    mu_t = mu[-1]
    denom = omega * (1.0 - omega)
    denom[denom == 0] = 1e-12
    sigma_b = (mu_t * omega - mu) ** 2 / denom
    thr = float(np.argmax(sigma_b))
    # 极端情况下（全白图等）退回一个合理值
    return thr if 20 <= thr <= 235 else 160.0


# ── 透视修正（用建筑外轮廓四角的交点做单应）
#
# 为什么必须做：退化测试台实测 2% 透视 → 宽度偏 +132mm；5% → +357mm；10% → +754mm。
# **即使 2% 也超出 ±60mm 容差**，而手机拍照几乎必然带 2~10%。
#
# 前五次尝试全部失败，失败点都在"分离外墙"这一步。共同错误是
# **按位置选轮廓**（找最左/最右的墨迹）——但家具、房间名、尺寸线、图签
# 都比墙更靠边。实测踩过：四角算出 x=-55、y=-471 这种荒唐值。
#
# 现在的判据换成了**长直线**，这是关键区别：
#   1. 对每一列/行，只统计属于**长游程**（≥图幅 8%）的墨迹像素，得到"贯穿长度"剖面
#      → 家具短边、文字笔画、尺寸线细段都不算数
#   2. 剖面里簇宽 ≥8px 的峰值才是墙（实测：真墙簇宽 10~35，尺寸线/图签是 1~2）
#   3. 在峰值附近 ±18px 的小窗口内**追踪线心随位置的偏移**，得到倾斜的直线
#      → 单应需要这个倾斜；只在窗口内找，就不会抓到窗口外的家具
#   4. 四条线两两求交 → 四角 → 解单应 → 把四角映射成正矩形
#
# 验证方式：修正后重跑提取，看建筑宽度误差是否从几百毫米回到几十毫米。

def mm_per_px(img: str, known_mm: float, known_px: float | None, tol_ratio: float = 500) -> tuple[float, str]:
    """确定像素→毫米的比例。

    known_px 给了就直接用；没给就用"建筑外轮廓宽度"当基准——
    但那是**推算**，必须标 source=derived 并写明依据。
    """
    if known_px:
        return known_mm / known_px, f"{known_mm}mm / {known_px}px（用户给定基准）"
    lines = run_probe(img, "--lines", "--min-run", str(max(24, int(_image_max_dim(img) * 0.13))),
                      "--max-lines", "20")
    v = [l for l in lines["vertical_lines"] if l["thickness_px"] >= 5]
    v.sort(key=lambda l: l["center"])
    if len(v) < 2:
        raise RuntimeError(f"只找到 {len(v)} 条竖直墙线，无法标定；请用 --calib-px 直接给基准")
    span = v[-1]["center"] - v[0]["center"]
    return known_mm / span, f"{known_mm}mm / {span:.1f}px（用最外两条墙线中心距推算）"


def band_of(lines: dict, y_center: float) -> tuple[int, int]:
    """取某条**水平**墙线的上下边界（用于沿墙扫厚度）"""
    for l in lines["horizontal_lines"]:
        if abs(l["center"] - y_center) < 1.5:
            return int(round(l["first"])), int(round(l["last"]))
    t = 12
    return int(y_center - t), int(y_center + t)


def band_of_vertical(lines: dict, x_center: float) -> tuple[int, int]:
    """取某条**竖直**墙线的左右边界。

    竖直墙的"厚度"在 X 方向，所以采样带是 x 区间，扫描沿 Y。
    这就是把同一套"沿墙扫厚度"算法泛化到另一个方向，不需要第二套逻辑。
    """
    for l in lines["vertical_lines"]:
        if abs(l["center"] - x_center) < 1.5:
            return int(round(l["first"])), int(round(l["last"]))
    t = 12
    return int(x_center - t), int(x_center + t)


def count_cross_lines(img, axis: str, band: tuple[int, int], lo: int, hi: int,
                      frac: float = 0.7) -> tuple[int, list[int]]:
    """数洞口范围内**垂直于墙方向**的贯穿线数量。

    用途：区分窗与门。实测依据（diag_opening_type.py，合成图纸已知真值）：
        门（M1）贯穿线 = 1 条   —— 门的开启弧画在洞外，洞里基本没有线
        窗（C1）贯穿线 = 4 条   —— 窗的四线符号
        窗（C2）贯穿线 = 3 条
    所以 **≥3 条 ⇒ 有正向证据是窗**。这是保守用法：
    只在有证据时下结论，判不出来就说判不出来（政策要求：不猜）。

    注意：这个阈值是**合成图**上测出来的。真图的窗符号线数可能不同
    （单线窗、推拉窗、飘窗都不一样），所以判成窗只给 medium 而不是 high。
    """
    from PIL import Image
    im = Image.open(img).convert("L")
    px = im.load()
    b0, b1 = band
    span = hi - lo
    hits = []
    if span <= 0:
        return 0, []
    if axis == "x":
        for y in range(b0, b1 + 1):
            cnt = sum(1 for x in range(lo, hi) if px[x, y] < 160)
            if cnt >= span * frac:
                hits.append(y)
    else:
        for x in range(b0, b1 + 1):
            cnt = sum(1 for y in range(lo, hi) if px[x, y] < 160)
            if cnt >= span * frac:
                hits.append(x)
    # 合并相邻（一条粗线会占多行/多列）
    merged, prev = 0, None
    for v in hits:
        if prev is None or v - prev > 2:
            merged += 1
        prev = v
    return merged, hits


def scan_run(img, axis: str, fixed_center: float, band: tuple[int, int],
             lo: int, hi: int, mmpp: float, min_pier_mm: float = 200):
    """沿一段墙扫描"实心段"与"洞口段"。

    泛化成**任意方向**，而不是给水平墙/竖直墙各写一套：
      axis='x' → 墙沿 X 走，沿 Y 取厚度采样（固定 y 中心）
      axis='y' → 墙沿 Y 走，沿 X 取厚度采样（固定 x 中心）
    这样两套逻辑共用同一份经过验证的"沿墙扫厚度"算法。
    （"有没有暗像素就算墙"那条是错的——窗的中线会被误判成实心墙。）

    返回 (实心段列表, 合并后的洞口列表)，坐标是**沿扫描方向的像素位置**。
    """
    from PIL import Image
    im = Image.open(img).convert("L")
    px = im.load()
    b0, b1 = band
    thickness_px = b1 - b0 + 1
    solid_need = max(3, int(thickness_px * 0.6))

    def dark_count(pos: int) -> int:
        if axis == "x":
            return sum(1 for t in range(b0, b1 + 1) if px[pos, t] < 160)
        return sum(1 for t in range(b0, b1 + 1) if px[t, pos] < 160)

    segs, run = [], None
    for pos in range(int(lo) - 20, int(hi) + 21):
        solid = dark_count(pos) >= solid_need
        if solid and run is None:
            run = pos
        elif not solid and run is not None:
            segs.append((run, pos - 1))
            run = None
    if run is not None:
        segs.append((run, int(hi) + 20))

    gaps = [(segs[i][1], segs[i + 1][0]) for i in range(len(segs) - 1)]
    # ── 合并"中间墙垛太窄"的相邻空隙
    #
    # 语义要看清：`a - merged[-1][1]` 是"上一隙的结束 → 这一隙的开始"，
    # 也就是**两隙之间那段实心墙（墙垛）的宽度**，**不是隙宽**。
    #
    # 表达式本身一直是对的，错的是**我给它起的名字**：
    # 参数原来叫 `min_gap_mm`（听起来是"隙宽门槛"），
    # 于是后来读代码时我被自己的名字骗了，以为在合并"窄隙"。
    # 它实际在合并的是"**中间墙垛小于门槛**的相邻洞口"。
    #
    # 后果：两个洞口之间只要剩一段窄墙垛，就被并成一个洞口。
    # 实测（参数扫描的"超大洞口 4500"方案）：两洞口间有 200mm 墙垛，
    # 合并后洞口宽错 2194mm。
    #
    # 现在改名 `min_pier_mm`（墙垛最小宽度），并把这个语义写进注释。
    # 逻辑没改，改的是名字——但名字错了会让人读错逻辑，这本身就是缺陷。
    #
    # ── 一个已记录、但**没能解决**的边界情况
    #
    # 若洞口**内部**有一条"在墙厚方向上贯通"的竖线（窗中梃、门窗框、门扇边线），
    # 扫描会把它当成墙垛，于是一个洞口被切成两个。
    # 实测（参数扫描"超大洞口"方案）：C1 是 2000mm 的窗，符号里有一条线
    # 贯通了整个墙厚，结果洞口被切成 1138 + 741 两段，再被合并成 4194。
    #
    # 我试过加一条"不依赖阈值"的几何合理性守卫
    # （两侧都是宽洞 + 墙垛达到最小可用宽度 → 不合并），**没解决问题**，
    # 所以按"失败的机制不留"的原则已撤掉。
    #
    # 为什么难：那条线的墨迹**确实贯通了整面墙厚**，
    # 从"沿墙扫厚度"这个判据看，它和真正的墙垛没有区别。
    # 要真正解决需要识别"这条竖线是不是窗符号的一部分"——
    # 那已经进入符号识别的范畴，不是加个阈值能办的。
    #
    # 目前的缓解措施：合并发生时**逐个洞口记录**并标 low + 写明原因
    # （见下面的 absorbed），让用户知道"这个宽度可能是两个洞口"。
    # 这是**诚实报告**而不是**正确识别**——边界在此，已如实写进文档。
    merged = []
    absorbed = []       # 每个输出洞口吸收了几处合并（0 = 没受影响）
    for a, b in gaps:
        if merged and (a - merged[-1][1]) * mmpp < min_pier_mm:
            merged[-1] = (merged[-1][0], b)
            absorbed[-1] += 1
            continue
        merged.append((a, b))
        absorbed.append(0)
    return segs, merged, absorbed


def scan_wall(img, y_center, x_from, x_to, band, mmpp, min_pier_mm=200):
    """水平墙（沿 X 走）——保留旧签名，内部转调 scan_run"""
    return scan_run(img, "x", y_center, band, x_from, x_to, mmpp, min_pier_mm)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--calib", type=float, required=True, help="已知真值尺寸（毫米）")
    ap.add_argument("--calib-px", type=float, default=None,
                    help="该真值对应的像素距离。不给则由最外墙线推算（会成为 derived 级）")
    ap.add_argument("--unit", default="mm", choices=["mm", "cm", "m"])
    ap.add_argument("--outer-t", type=float, default=None, help="外墙厚（**必须由用户给或读标注**）")
    ap.add_argument("--inner-t", type=float, default=None, help="内墙厚")
    ap.add_argument("--height", type=float, default=2800, help="墙高")
    ap.add_argument("--name", default="从图纸提取")
    ap.add_argument("--out", default="plan_extracted.json")
    ap.add_argument("--no-deskew", action="store_true",
                    help="关闭自动纠偏（默认开启；歪斜 3° 就会让洞口识别彻底出错）")
    ap.add_argument("--max-deskew", type=float, default=6.0,
                    help="纠偏搜索的最大角度（度），默认 6")
    args = ap.parse_args()

    if not os.path.exists(args.image):
        print(f"找不到图纸：{args.image}")
        return 1

    # ── 单位闸门：用户政策要求"没标注单位就打回"
    scale_unit = {"mm": 1.0, "cm": 10.0, "m": 1000.0}[args.unit]
    known_mm = args.calib * scale_unit

    print("=" * 66)
    print("从图纸提取建筑描述")
    print("=" * 66)
    print(f"图纸：{args.image}")
    print(f"单位：{args.unit}（标定值 {args.calib} → {known_mm}mm）")

    if args.outer_t is None and args.inner_t is None:
        print()
        print("❌ 打回：没有提供墙厚。")
        print("   实测依据：墙厚只占 9~20px，量图的相对误差 5~10%，不可用。")
        print("   请从图纸标注读出墙厚，或用 --outer-t/--inner-t 指定。")
        return 2

    # ── 透视：**没有检测，也没有修正** —— 这是硬前置要求
    #
    # 实测（退化测试台）：2% 透视 → 建筑宽度偏 +132mm；5% → +357mm；10% → +754mm。
    # **即使 2% 的轻微透视也超出 ±60mm 容差**，而手机拍照几乎必然带 2~10%。
    #
    # 我做了**六版**尝试，全部失败，代码已全部删除（不留半成品）：
    #   1. 用建筑外轮廓四角的交点做单应 —— 在整行里找"最左的厚墨迹"，
    #      抓到的是尺寸线/家具（四角算出 x=-55、y=-471）
    #   2. 同上，改用"墨迹总量"定位建筑范围 —— 范围被撑到整张图
    #   3. 同上，改用"该行存在厚墨迹"定位 —— 家具和引线也贡献厚墨迹
    #   4. 同上，限定在两端 15% 窗口内找 —— 四条外轮廓线拟合不全
    #   5. 用"上下半图各自的倾斜角之差"做**检测** —— 角度卡在搜索边界 ±4°，
    #      干净图误报、10% 透视反而漏报
    #   6. 用"长游程剖面 + 簇宽过滤"找墙线（这一版**墙线找对了**，
    #      可视化确认四条外墙都被准确追踪），但**四角求交后比例仍然错**：
    #      p10 修正后上下缘跨度几乎相等（6506 / 6585，说明透视确实被拉平了），
    #      可建筑长宽比却变成 660:365 = 1.81，而真值是 6000:4800 = 1.25 —— 图被压扁了。
    #      根因：**用四条线求交得到的四角，无法精确确定单应所需的 4 组点对应**；
    #      追踪到的"四角"高度也只测到 y=292..658，而真实建筑是 249..612。
    #
    # 根因是同一个：**在有家具、房间名、尺寸线、图签的图里可靠地定位外轮廓角点，
    # 是个真正的计算机视觉问题**。这台机器上没有 cv2 / skimage / scipy，
    # 只有 numpy + PIL，自己写 Hough+角点检测的复杂度远超收益。
    #
    # 所以这一条走**诚实拒绝**：不修正、也不假装能检测，写进文档当前置要求。
    # 这是我目前能力边界上唯一还没跨过去的一项，也是**最该被如实告知**的一项。

    # ── 自动纠偏（歪斜是退化测试台量出来的**唯一致命项**）
    #
    # 实测：1° 时洞口位置偏 46~54mm；3° 时洞口宽错 3 米、内墙丢失。
    # 而扫描件歪斜 1~3° 极其常见，所以这一步必须做在一切之前。
    if not args.no_deskew:
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.close()
        try:
            dsk = deskew_image(args.image, tmp.name, max_deg=args.max_deskew)
        except Exception as e:  # noqa: BLE001
            dsk = {"angle": 0.0, "applied": False, "error": str(e)[:120]}
        if dsk.get("applied"):
            print(f"纠偏：原图歪斜 {dsk['angle']:+.2f}°，已自动转正"
                  f"（投影方差最大化，Otsu 阈值 {dsk.get('thr')}）")
            args.image = tmp.name
        else:
            note = f"（纠偏未生效：{dsk['error']}）" if dsk.get("error") else ""
            print(f"纠偏：未检出歪斜，按原图处理{note}")
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

    mmpp, basis = mm_per_px(args.image, known_mm, args.calib_px)
    print(f"标定：1px = {mmpp:.3f}mm   （依据：{basis}）")

    # ── 透视：**没有检测，也没有修正** —— 这是硬前置要求
    #
    # 实测（退化测试台）：2% 透视 → 建筑宽度偏 +132mm；5% → +357mm；10% → +754mm。
    # **即使 2% 的轻微透视也超出 ±60mm 容差**，而手机拍照几乎必然带 2~10%。
    #
    # 我做了五版尝试，全部失败，且已**全部删除**（不留半成品）：
    #   1. 用建筑外轮廓四角的交点做单应 —— 在整行里找"最左的厚墨迹"，
    #      抓到的是尺寸线/家具（四角算出 x=-55、y=-471）
    #   2. 同上，改用"墨迹总量"定位建筑范围 —— 范围被撑到整张图
    #   3. 同上，改用"该行存在厚墨迹"定位 —— 家具和引线也贡献厚墨迹
    #   4. 同上，限定在两端 15% 窗口内找 —— 四条外轮廓线拟合不全，直接失败
    #   5. 用"上下半图各自的倾斜角之差"做**检测** —— 角度总卡在搜索边界 ±4°，
    #      上半下半乱跳；干净图误报、10% 透视反而漏报
    #
    # 根因是同一个：**在有家具、房间名、尺寸线、图签的图里可靠地分离出"外墙"
    # 是个真正的计算机视觉问题**，不是几行启发式能解决的。
    #
    # 所以这一条走**诚实拒绝**而不是"猜着掰回来"：不修正、也不假装能检测，
    # 写进文档当前置要求。这是我目前能力边界上唯一还没跨过去的一项。

    # ── 线检测的"最短线长"要按**各方向自己的尺寸**算，不能都用长边
    #
    # 踩过的坑（分两次量出来的）：
    #   · 最早写死 --min-run 120：半分辨率（476px 宽）时门槛占图宽 25%，
    #     墙线全漏，还报"墙线数量不足，请提供更清晰的图纸"——
    #     **把分辨率问题误报成清晰度问题**。于是改成按图幅比例。
    #   · 但改成"长边 × 13%"后，在 **1:100 图纸**上又栽了：
    #     图幅 726×761 时门槛 98px，而**底部外墙被内墙和洞口打断，
    #     最长连续游程只有 78px** → 整条墙漏检 → 整张图被打回。
    #     水平墙的长度受**图宽**限制、竖直墙受**图高**限制，
    #     用一个统一的长边门槛，对窄的那个方向必然过严。
    #     （1:50 那张图只是**勉强**过的：最长游程 154 对门槛 123，仅 1.25 倍余量。）
    w_px, h_px = _image_size(args.image)
    print(f"图幅 {w_px}×{h_px}px")
    min_run_x = max(24, int(w_px * 0.10))   # 水平墙受图宽限制
    min_run_y = max(24, int(h_px * 0.10))   # 竖直墙受图高限制
    # 探测接口只有一个门槛，取**宽松**的那个：宁可让探测多报，
    # 后面还有"相对厚度"和"两条线才算墙"两道过滤兜着。
    min_run = min(min_run_x, min_run_y)
    lines = run_probe(args.image, "--lines", "--min-run", str(min_run), "--max-lines", "40")
    v, h, thick_note = _pick_walls(lines["vertical_lines"], lines["horizontal_lines"])
    print(f"识别到 {len(v)} 条竖直墙线、{len(h)} 条水平墙线（{thick_note}）")

    if len(v) < 2 or len(h) < 2:
        print("❌ 打回：墙线数量不足，无法确定建筑轮廓。")
        print(f"   图幅 {w_px}×{h_px}px。若是**低分辨率或手机照片**，"
              "墙线可能确实太短——请裁掉图签/空白后重发，或提供更清晰的图纸。")
        return 2

    xs = [l["center"] for l in v]
    ys = [l["center"] for l in h]
    x0_px, x1_px = xs[0], xs[-1]
    y0_px, y1_px = ys[0], ys[-1]
    W = (x1_px - x0_px) * mmpp
    H = (y1_px - y0_px) * mmpp
    print(f"建筑轴线范围：{W:.0f} × {H:.0f} mm")

    data = {
        "meta": {
            "name": args.name,
            "units": "mm",
            "source": os.path.basename(args.image),
            "unit_original": args.unit,
            "scale_basis": f"1px = {mmpp:.4f}mm，依据：{basis}",
            "calibration_source": "dim" if args.calib_px else "derived",
            "assumptions": [
                "墙厚由用户提供，未从图上测量（量图误差 5~10%，不可用）",
                "房间轮廓由墙线围合推断，真图上有隔墙时需人工核对",
                "洞口类型：洞口内 ≥3 条贯穿线判为窗（medium），否则判为门（low）。"
                "该阈值是在合成图上测出来的，真图的窗符号线数可能不同；"
                "**门与净洞口在图像层面无法区分**。",
                "窗的高度 1400、窗台 900 是按常规取的推定值，需用户确认",
            ],
        },
        "floors": [{
            "name": "F1-楼板", "z": 0,
            "thickness": 100,
            "polygon": [[0, 0], [round(W), 0], [round(W), round(H)], [0, round(H)]],
            "source": "derived", "basis": "由最外两条墙线中心距推算",
        }],
        "walls": [],
        "rooms": [],
        "_extraction": {"mm_per_px": round(mmpp, 5), "wall_v_px": xs, "wall_h_px": ys},
    }

    # ── 四面外墙：都做洞口识别（水平墙沿 X 扫，竖直墙沿 Y 扫）
    #
    # 洞口类型判定（保守策略）：
    #   · 洞口内有 ≥3 条贯穿线 → **有正向证据是窗**，标 window + confidence=medium
    #   · 否则 → 标 door + confidence=low，并在 note 里说明"可能与门/净洞口混淆"
    # 为什么不一律问用户、也不一律猜：见 count_cross_lines 的实测依据。
    # 判不出来时**明确说判不出来**，不用猜测填空（工作政策）。
    def wall(name, p_from, p_to, thickness, axis, fixed_px, span_px, band):
        ent = {
            "name": name,
            "from": [round(p_from[0]), round(p_from[1])],
            "to": [round(p_to[0]), round(p_to[1])],
            "thickness": thickness, "height": args.height,
            "source": "derived",
            "basis": "墙线位置由探针测得，墙厚由用户给定",
            "openings": [],
        }
        # ── 墙垛合并阈值：随**墙厚**走，而不是写死一个毫米数
        #
        # 这是一个真实权衡，两个方向都会出错：
        #   · 阈值太大（300mm）→ 两个洞口间的窄墙垛被并掉，
        #     两个洞变成一个（实测"超大洞口"方案宽错 2194mm）
        #   · 阈值太小（150mm）→ 洞口**内部**的窄空隙不再被合并，
        #     洞宽被撑大（实测 1:100 与厚墙方案 OP2_W 从 −20 变成 −600）
        #
        # 取"墙厚 × 1.2"作为折中：它随比例和墙厚自动缩放，
        # 而且任何真正能站人的墙垛（≥ 墙厚）都会被保留。
        min_pier = max(150.0, (band[1] - band[0] + 1) * mmpp * 1.2)
        _, gaps, absorbed = scan_run(args.image, axis, fixed_px, band,
                                     span_px[0], span_px[1], mmpp, min_pier)
        # 墙段的总长（墙的两个端点在**沿扫描方向**上的跨度）
        wall_len_mm = (span_px[1] - span_px[0]) * mmpp
        for gi, (a, b) in enumerate(gaps):
            u = (a - span_px[0]) * mmpp
            w = (b - a) * mmpp
            # 这个洞口吸收了几处合并（0 = 没受影响）
            #
            # 为什么要**按洞口**记而不是按墙记：
            # 我第一版把"这面墙合并过几次"当成整面墙的属性，
            # 于是**同一面墙上的所有洞口都被打了警告**。
            # 实测：南墙有 1 处合并，但 900 的门和 1495 的窗**都被标了**
            # "可能实际是两个洞口"——其中一个完全没问题。
            # 这会让用户怀疑两个洞口，浪费他的注意力，也削弱警告的可信度。
            n_merges = absorbed[gi] if gi < len(absorbed) else 0
            if w < 300:
                continue
            # ── 丢弃贴在墙端、或落在墙段之外的"洞口"
            #
            # 退化测试台量出来的假象：`scan_run` 的扫描范围是 [`lo`-20, `hi`+20]
            # 像素，比墙段本身宽；墙端之外的空处于是被当成一个洞口，
            # 产出 u=-516、u=4935 这种**幽灵洞口**（实测见过）。
            # 判据：洞口必须**基本落在墙段之内**——允许 5% 的贴边裕量，
            # 但不能整段跑到墙外，也不能贴在墙端只占一点点。
            if u < -wall_len_mm * 0.02 or u + w > wall_len_mm * 1.02:
                continue
            if u + w <= 0 or u >= wall_len_mm:
                continue
            n_lines, _ = count_cross_lines(args.image, axis, band, a, b)
            is_window = n_lines >= 3
            # ⚠️ 若这面墙在扫描时发生过"中间墙垛太窄而被合并"，那么这个洞口的
            # 结果可能是**两个洞口并成一个**——必须让用户知道，不能悄悄给个宽数字。
            # 实测（参数扫描的"超大洞口 4500"方案）：两洞口间有 200mm 墙垛，
            # 合并后洞口宽 4194mm，看起来像个真实的大洞口，实际是两个。
            merged_note = ""
            conf = "medium" if is_window else "low"
            if n_merges > 0:
                conf = "low"
                merged_note = (f"⚠️ 这个洞口里并进了 {n_merges} 段**很窄的墙垛**"
                               "（比我设的下限还窄）。所以它的宽度"
                               "**可能实际是两个（或多个）洞口**，请照图纸核对。")
            ent["openings"].append({
                "type": "window" if is_window else "door",
                "u": round(u), "width": round(w),
                "height": 1400 if is_window else 2100,
                "sill": 900 if is_window else 0,
                "label": f"{name}-洞{len(ent['openings']) + 1}",
                "source": "derived",
                "basis": (f"由墙上实心段之间的空隙测得；洞口内有 {n_lines} 条贯穿线"
                          + ("（≥3，符合窗符号特征）" if is_window else "（<3，无窗的线特征）")),
                "confidence": conf,
                "cross_lines": n_lines,
                "merged_piers": n_merges,
                "note": (merged_note + " " if merged_note else "") +
                        ("判为窗：洞口内有贯穿线，符合窗符号特征。"
                         "但窗的高度/窗台高是我按常规取的，需确认。"
                         if is_window else
                         "判为门：洞口内没有窗的线特征。"
                         "但**门与净洞口在这个层面无法区分**，需确认；"
                         "若是窗则高度与窗台高也需给出。"),
            })
        return ent

    data["walls"].append(wall("W-南", [0, 0], [round(W), 0], args.outer_t,
                              "x", y1_px, (x0_px, x1_px), band_of(lines, y1_px)))
    data["walls"].append(wall("W-北", [0, round(H)], [round(W), round(H)], args.outer_t,
                              "x", y0_px, (x0_px, x1_px), band_of(lines, y0_px)))
    data["walls"].append(wall("W-西", [0, 0], [0, round(H)], args.outer_t,
                              "y", x0_px, (y0_px, y1_px), band_of_vertical(lines, x0_px)))
    data["walls"].append(wall("W-东", [round(W), 0], [round(W), round(H)], args.outer_t,
                              "y", x1_px, (y0_px, y1_px), band_of_vertical(lines, x1_px)))

    print(f"提取到 {len(data['walls'])} 面墙，"
          f"{sum(len(w['openings']) for w in data['walls'])} 个洞口候选")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"已写出：{args.out}")
    print()
    print("⚠️ 这是**推算**结果，不是读标注得来。按工作政策，")
    print("   必须先把这份数据 + 疑问清单交给用户确认，才能建模。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
