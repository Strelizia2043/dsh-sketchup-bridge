#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""读图链路的退化测试台。

为什么要做这件事：
在此之前，读图链路只在**我自己画的、干净到不真实的合成图**上验证过
（纯黑 0 / 纯白 255，阈值 160 随便都对）。真实图纸是扫描件或手机照片，会带：
歪斜、灰度、噪声、模糊、低分辨率、图签遮挡、JPEG 压缩。

这个脚本把基准图按这些方式逐项劣化，**用已知真值量出每种退化下的误差**，
从而找出最先失效的环节——而不是靠猜"哪里可能有问题"。

真值（来自 make_test_drawing.py）：
    建筑 6000×4800，外墙 240、内墙 120，内墙轴线 x=3600
    门 M1 900@900、M2 800@1900，窗 C1 1500@2600、C2 1200@y1800
标定基准：6000mm ↔ 453.5px（与 verify_pipeline.py 一致）
"""

from __future__ import annotations


import os
import random
import sys
import numpy as np
from PIL import Image
import subprocess
from PIL import ImageFilter
import io
from PIL import ImageDraw
import json

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
PY = sys.executable
OUT = os.path.join(HERE, "degrade_out")

BASE = os.path.join(ROOT, "shots", "test_plan.png")
CALIB_MM = 6000.0
CALIB_PX = 453.5

TRUTH = {
    "width": 6000.0,
    "height": 4800.0,
    "int_x": 3600.0,
    "m1_u": 900.0, "m1_w": 900.0,
    "c1_u": 2600.0, "c1_w": 1500.0,
    "c2_u": 1800.0, "c2_w": 1200.0,
}


def degrade(im: Image.Image, mode: str) -> tuple[Image.Image, float]:
    """返回 (退化后的图, 像素标定缩放因子)。

    缩放因子的含义：`--calib-px` 是**在这张图上量到的**像素跨度。
    降采样 k 倍后，同一段物理长度在图上的像素数**变为 1/k**，
    所以标定值应当乘 1/k —— 我第一版乘了 k，结果 6000mm 的跨度算成
    1500mm（正好 1/4），一度让我以为"降采样会让提取整体失效"。
    """
    w, h = im.size
    if mode == "clean":
        return im, 1.0
    if mode == "rotate_1deg":
        return im.rotate(1.0, resample=Image.BICUBIC, fillcolor=255), 1.0
    if mode == "rotate_3deg":
        return im.rotate(3.0, resample=Image.BICUBIC, fillcolor=255), 1.0
    if mode == "rotate_5deg":
        return im.rotate(5.0, resample=Image.BICUBIC, fillcolor=255), 1.0
    if mode == "gray_lowcontrast":
        # 模拟浅色扫描：墨线不再是纯黑，对比度只剩 35%
        return im.point(lambda v: int(210 - (210 - v) * 0.35)), 1.0
    if mode == "paper_gray":
        # 纸张发灰（拍照常见）：白底压到 ~180，墨线仍深
        return im.point(lambda v: int(180 - (180 - v) * 0.85)), 1.0
    if mode == "noise_sigma15":
        import random
        random.seed(7)
        px = im.load()
        for y in range(h):
            for x in range(w):
                px[x, y] = max(0, min(255, px[x, y] + int(random.gauss(0, 15))))
        return im, 1.0
    if mode == "noise_sigma40":
        import random
        random.seed(11)
        px = im.load()
        for y in range(h):
            for x in range(w):
                px[x, y] = max(0, min(255, px[x, y] + int(random.gauss(0, 40))))
        return im, 1.0
    if mode == "blur_2px":
        return im.filter(ImageFilter.GaussianBlur(2.0)), 1.0
    if mode == "blur_4px":
        return im.filter(ImageFilter.GaussianBlur(4.0)), 1.0
    if mode == "half_res":
        return im.resize((w // 2, h // 2), Image.LANCZOS), 0.5
    if mode == "quarter_res":
        return im.resize((w // 4, h // 4), Image.LANCZOS), 0.25
    if mode == "third_res":
        return im.resize((w // 3, h // 3), Image.LANCZOS), 1.0 / 3.0
    if mode == "jpeg_q30":
        buf = io.BytesIO()
        im.convert("RGB").save(buf, format="JPEG", quality=30)
        buf.seek(0)
        return Image.open(buf).convert("L"), 1.0
    if mode == "titleblock":
        out = im.copy()
        d = ImageDraw.Draw(out)
        bw = int(w * 0.32)
        bh = int(h * 0.24)
        d.rectangle([w - bw, h - bh, w, h], fill=255, outline=0, width=3)
        for i in range(6):
            yy = h - bh + 16 + i * 18
            d.line([w - bw + 12, yy, w - 12, yy], fill=110, width=1)
        return out, 1.0
    if mode == "shadow":
        out = im.copy()
        d = ImageDraw.Draw(out)
        bw = int(w * 0.14)
        for x in range(bw):
            d.line([x, 0, x, h], fill=int(255 - (bw - x) / bw * 80))
        return out, 1.0

    # ── 透视（手机拍照最常见，而纠偏只修旋转、修不了透视）
    #
    # 做法：解一个 3×3 透视矩阵，把"顶边收窄、底边不变"映射到图上，
    # 模拟"从下方斜着拍一张纸"。挪动量按图幅比例给。
    #
    # 为什么用解方程而不是 PIL 的 QUAD/PERSPECTIVE 手填系数：
    # PIL 的 QUAD 取点顺序和 PERSPECTIVE 的系数含义都很容易记反，
    # 我第一版就是先写了个 QUAD 又叠了个 transform，纯属混乱。
    # 解方程（4 组点对 → 8 个系数）结果唯一，不用猜。
    if mode.startswith("persp_"):
        k = {"persp_2pct": 0.02, "persp_5pct": 0.05, "persp_10pct": 0.10}[mode]
        return _perspective(im, k), 1.0

    raise SystemExit(f"不认识的退化模式：{mode}")


def _perspective(im: Image.Image, k: float) -> Image.Image:
    """把图做一次透视变形：顶边收窄 k 比例、底边不变。

    这是"从下方斜着拍一张纸"最典型的形态——顶边离相机远所以显得窄。
    解 3×3 透视矩阵：找把目标四角映射到源四角的系数。
    """
    import numpy as np

    w, h = im.size
    dx = w * k

    def solve(dst, src):
        A, B = [], []
        for (x, y), (u, v) in zip(dst, src):
            A.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
            B.append(u)
            A.append([0, 0, 0, x, y, 1, -v * x, -v * y])
            B.append(v)
        return np.linalg.solve(np.array(A, dtype=float), np.array(B, dtype=float))

    dst = [(0, 0), (w, 0), (w, h), (0, h)]
    src = [(dx, 0), (w - dx, 0), (w, h), (0, h)]
    coef = solve(dst, src)
    return im.transform((w, h), Image.PERSPECTIVE, coef,
                        resample=Image.BICUBIC, fillcolor=255)


MODES = [
    "clean",
    "rotate_1deg", "rotate_3deg", "rotate_5deg",
    "persp_2pct", "persp_5pct", "persp_10pct",
    "gray_lowcontrast", "paper_gray",
    "noise_sigma15", "noise_sigma40",
    "blur_2px", "blur_4px",
    "third_res", "half_res", "quarter_res",
    "jpeg_q30", "titleblock", "shadow",
]


def run_extract(path: str, scale: float) -> dict:
    outp = os.path.join(OUT, os.path.basename(path).rsplit(".", 1)[0] + ".json")
    cmd = [PY, _tool("extract_plan.py"), path,
           "--calib", str(CALIB_MM), "--calib-px", str(CALIB_PX * scale),
           "--unit", "mm", "--outer-t", "240", "--inner-t", "120",
           "--name", "退化测试", "--out", outp]
    r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300)
    if r.returncode != 0:
        return {"_error": (r.stderr or r.stdout or "").strip().splitlines()[-1:] and
                (r.stderr or r.stdout).strip()[-260:] or "退出码非 0"}
    if not os.path.exists(outp):
        return {"_error": "没有产出 JSON"}
    try:
        with open(outp, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:  # noqa: BLE001
        return {"_error": f"JSON 解析失败: {e}"}


def measure(data: dict) -> dict:
    out = {}
    ws = data.get("walls") or []
    xs, ys = [], []
    for w in ws:
        for p in (w.get("from"), w.get("to")):
            if p:
                xs.append(float(p[0]))
                ys.append(float(p[1]))
    if xs and ys:
        out["width"] = max(xs) - min(xs)
        out["height"] = max(ys) - min(ys)
    vx = []
    for w in ws:
        fx, fy = float(w["from"][0]), float(w["from"][1])
        tx, ty = float(w["to"][0]), float(w["to"][1])
        if abs(fx - tx) < 1 and abs(fy - ty) > 1000:
            vx.append(fx)
    if vx:
        vx = sorted(set(round(v, 1) for v in vx))
        inner = [v for v in vx if v not in (min(vx), max(vx))]
        if inner:
            out["int_x"] = inner[0]
    if ws:
        south = min(ws, key=lambda w: min(float(w["from"][1]), float(w["to"][1])))
        sops = sorted(south.get("openings") or [], key=lambda o: float(o.get("u", 0)))
        for i, key in enumerate(("m1", "c1")):
            if i < len(sops):
                out[f"{key}_u"] = float(sops[i].get("u", 0))
                out[f"{key}_w"] = float(sops[i].get("width", 0))
        for w in ws:
            fx, fy = float(w["from"][0]), float(w["from"][1])
            tx, ty = float(w["to"][0]), float(w["to"][1])
            if abs(fx - tx) < 1 and abs(fy - ty) > 1000 and (w.get("openings") or []):
                if abs(fy) < 1:
                    o = w["openings"][0]
                    out["c2_u"] = float(o.get("u", 0))
                    out["c2_w"] = float(o.get("width", 0))
    return out


KEYS = ["width", "height", "int_x", "m1_u", "m1_w", "c1_u", "c1_w", "c2_u", "c2_w"]


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    if not os.path.exists(BASE):
        print(f"❌ 找不到基准图 {BASE}；先跑 make_test_drawing.py 生成")
        return 1
    base = Image.open(BASE).convert("L")
    print(f"基准图 {os.path.relpath(BASE, HERE)}  尺寸 {base.size}")
    print(f"标定基准 {CALIB_MM:.0f}mm ↔ {CALIB_PX}px")
    print()

    hdr = f"{'退化':<18}" + "".join(f"{k:>10}" for k in KEYS)
    print(hdr)
    print("-" * len(hdr))
    worst = {}
    failed = []
    for mode in MODES:
        im, scale = degrade(base.copy(), mode)
        p = os.path.join(OUT, f"{mode}.png")
        im.save(p)
        data = run_extract(p, scale)
        if "_error" in data:
            print(f"{mode:<18}  ❌ {str(data['_error'])[:80]}")
            failed.append((mode, data["_error"]))
            continue
        got = measure(data)
        line = f"{mode:<18}"
        for k in KEYS:
            if k in got:
                e = got[k] - TRUTH[k]
                mark = "" if abs(e) <= 30 else ("!" if abs(e) <= 200 else "!!")
                line += f"{e:>8.0f}{mark:<2}"
                worst[k] = max(worst.get(k, 0), abs(e))
            else:
                line += f"{'—':>10}"
        print(line)

    print()
    print("标记：无 = ±30mm 内可接受；! = 30~200mm；!! = >200mm；— = 没提取到")
    print()
    if worst:
        print("各量的最大误差（跨所有退化）：")
        for k in KEYS:
            if k in worst:
                print(f"  {k:<8} {worst[k]:>8.0f} mm")
    if failed:
        print()
        print("失败的退化：")
        for mode, err in failed:
            print(f"  {mode}: {str(err)[:120]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
