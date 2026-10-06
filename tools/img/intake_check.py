#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""进件评估：拿到一张图纸先判断"能不能用、能读出什么、还缺什么"。

为什么需要这一条命令：
真实工作流是「用户发图 → 我判断 → 再动手」。但这个判断此前散在三处：
`plan_probe`（线检测）、纠偏（歪斜）、退化测试台的经验（各项容差）。
没有任何一条命令能一次给出结论，所以每次都要手工拼。

这个脚本把 21 轮积累的判据合并到一次运行里，输出：
  1. 图幅 / 对比度 / 墨迹占比 —— 能不能二值化
  2. 歪斜角（要不要纠偏）
  3. 墙线检出情况（竖直/水平各几条、厚度是否够）
  4. **透视风险**（检测，不修正——修正做过六版全失败）
  5. 标定可行性（能否用"最外两条墙线"自动定比例）
  6. 分辨率是否够分清窗框线（决定洞口类型判别能不能用）
  7. 结论 + 我应该问用户什么

⚠️ 所有判据都是**实测出来的**（见 抗退化实测.md），不是拍脑袋定的阈值。
"""

from __future__ import annotations


import argparse
import os
import sys
from PIL import Image
import json
import numpy as np
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


def otsu(arr: np.ndarray) -> float:
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
    return thr if 20 <= thr <= 235 else 160.0


def probe_lines(path: str, min_run: int, max_lines: int = 30) -> dict:
    r = subprocess.run([sys.executable, PROBE, path, "--lines",
                        "--min-run", str(min_run), "--max-lines", str(max_lines)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"探针失败: {(r.stderr or r.stdout)[:200]}")
    return json.loads(r.stdout)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="进件评估：这张图纸能不能用")
    ap.add_argument("image")
    ap.add_argument("--calib-mm", type=float, default=None,
                    help="若已知某个标注尺寸（如总长 6000），给出可一并检验标定是否自洽")
    args = ap.parse_args()

    if not os.path.exists(args.image):
        print(f"❌ 找不到图：{args.image}")
        return 1

    with Image.open(args.image) as im:
        gray = im.convert("L")
        size = im.size
        mode = im.mode
    arr = np.asarray(gray, dtype=np.float32)
    thr = otsu(arr)
    ink = arr < thr
    H, W = ink.shape
    dim = max(H, W)

    print("=" * 70)
    print(f"进件评估：{os.path.basename(args.image)}")
    print("=" * 70)
    print(f"图幅 {W}×{H}px   色彩模式 {mode}")
    print(f"Otsu 阈值 {thr:.0f}   墨迹占比 {ink.mean() * 100:.2f}%")

    problems = []      # 会导致打回
    caveats = []       # 能用但要提醒
    asks = []          # 需要用户提供

    # ── 1. 分辨率与线长门槛
    #
    # 门槛必须按**各方向自己的尺寸**算。踩过两次：
    #   · 写死 120px → 半分辨率图上墙线全漏，还报"图不清晰"（把分辨率问题误报成清晰度问题）
    #   · 改成"长边 × 13%" → 1:100 图上底部外墙被内墙和洞口打断，
    #     最长连续游程 78px 而门槛 98px，整条墙漏检、整张图被打回
    min_run_x = max(24, int(W * 0.10))
    min_run_y = max(24, int(H * 0.10))
    min_run = min(min_run_x, min_run_y)
    print(f"线长门槛：横 {min_run_x}px / 竖 {min_run_y}px（实际传 {min_run}px，取宽松的）")

    # ── 2. 墙线检出
    L = probe_lines(args.image, min_run)
    v = sorted([l for l in L["vertical_lines"] if l["thickness_px"] >= 5],
               key=lambda l: l["center"])
    h = sorted([l for l in L["horizontal_lines"] if l["thickness_px"] >= 5],
               key=lambda l: l["center"])
    print(f"检出墙线：竖直 {len(v)} 条、水平 {len(h)} 条（厚度 ≥5px）")
    for l in v:
        print(f"   V center={l['center']:7.1f} 厚{l['thickness_px']:>3}px 最长{l['longest']:>4}px")
    for l in h:
        print(f"   H center={l['center']:7.1f} 厚{l['thickness_px']:>3}px 最长{l['longest']:>4}px")

    if len(v) < 2 or len(h) < 2:
        problems.append(f"墙线不足（竖 {len(v)}、横 {len(h)}）——无法确定建筑轮廓")

    # ── 3. 标定可行性
    calib = None
    if len(v) >= 2:
        span = v[-1]["center"] - v[0]["center"]
        if span > 20:
            calib = span
            print(f"标定可行性：最外两条竖墙线中心距 {span:.1f}px"
                  f"（可作为 --calib-px；需配用户给出的 --calib 实际毫米数）")
            if args.calib_mm:
                mmpp = args.calib_mm / span
                print(f"   若 {span:.1f}px = {args.calib_mm:.0f}mm，则 1px = {mmpp:.3f}mm")
        else:
            problems.append("两条竖墙线几乎重合，无法标定")
    else:
        problems.append("竖墙线不足，无法自动标定（需用户直接给 --calib-px）")

    # ── 4. 透视风险（检测，不修正）
    # ── 4. 透视：**测不了，所以直接问**
    #
    # 我做了**七版**透视检测/修正的尝试，全部失败，代码已全部删除：
    #   1~4  用外轮廓四角做单应（按位置选轮廓 → 抓到尺寸线/家具）
    #   5    "上下半图倾斜角之差"做检测 → 角度卡在搜索边界，干净图误报、10% 漏报
    #   6    "长游程剖面 + 簇宽过滤"找墙线 → **墙线找对了**，但四角求交后比例仍错
    #        （p10 修正后长宽比 1.81，真值 1.25，图被压扁）
    #   7    "竖墙上下厚度比"做检测 → 固定 ±30px 窗口在高处偏了，
    #        读到 1~2px 而墙有 19~20px（抓到家具边/房间名笔画）
    #
    # 第 6、7 版暴露的是同一件事：**没有 CV 库时，在杂乱图纸里稳健追踪墙线做不到**
    # （这台机器上没有 cv2 / skimage / scipy，只有 numpy + PIL）。
    #
    # 所以这一项**不检测、不修正、直接问**——符合"拿不准就问，不许猜"的政策。
    # 给用户一个可操作的自查方法，比我猜一个不可靠的指标强。
    asks.append(
        "**请确认图纸是平铺正拍的**（不是斜着举手机拍的）。"
        "原因：实测 2% 透视就会让建筑宽度偏 132mm、5% 偏 357mm，"
        "而我**试过七版自动修正全部失败**，没有可靠手段。"
        "自查方法：图上同一道墙在上下两端的**画面厚度**应当基本一致；"
        "若明显一头粗一头细，就是斜拍了，请重拍或改用扫描件")

    # ── 5. 清晰度底线：窗框线要能分辨
    thinnest = min([l["thickness_px"] for l in v + h], default=0)
    frame_px = thinnest / 4.0 if thinnest else 0
    print(f"最薄墙线 {thinnest}px → 窗框线估计约 {frame_px:.1f}px")
    if frame_px < 1.5:
        caveats.append(
            f"窗框线估计只有 {frame_px:.1f}px——**洞口类型（门/窗）判别会失效**，"
            "窗可能被判成门。位置和宽度仍准，但我会就每个洞口问你")
    if thinnest and thinnest < 5:
        problems.append("最薄墙线不足 5px，提取会丢失部分墙体")

    # ── 6. 对比度
    #
    # 不能用分位数：墨线只占图面约 5%，`5 分位` 仍然落在**白纸**上，
    # 于是"对比 = 0"（实测踩过，把一张纯黑线条的图报成对比度不足）。
    # 按阈值两侧取均值才反映真实的纸/墨亮度。
    paper = float(arr[arr >= thr].mean()) if (arr >= thr).any() else 255.0
    line = float(arr[arr < thr].mean()) if (arr < thr).any() else 0.0
    print(f"纸张亮度 {paper:.0f}   墨线亮度 {line:.0f}   对比 {paper - line:.0f}")
    if paper - line < 60:
        caveats.append(f"对比度偏低（{paper - line:.0f}）——已用 Otsu 自适应阈值，"
                       "一般仍可用，但建议重扫更清晰的一份")

    # ── 7. 缺什么（按工作政策：拿不准必须问，不能猜）
    if not args.calib_mm and calib:
        asks.append(f"图纸上标注的一个已知尺寸（例如建筑总长）。"
                    f"图上对应 {calib:.1f}px —— 我**不猜比例**，需要你给一个真实毫米数")
    asks.append("**墙厚**（外墙/内墙各多少 mm）。实测墙厚只占 9~20px，"
                "量图的相对误差 5~10%，**不可用**，必须从标注读或你直接给")

    # ── 输出结论
    print()
    print("=" * 70)
    if problems:
        print("❌ 结论：**不能直接提取**")
        for p in problems:
            print(f"   · {p}")
    else:
        print("✅ 结论：**可以提取**")
    if caveats:
        print()
        print("⚠️ 需要提醒的：")
        for c in caveats:
            print(f"   · {c}")
    print()
    print("❓ 我需要你提供的：")
    for a in asks:
        print(f"   · {a}")
    print()
    print("下一步（我会先给你看数据与疑问清单，你确认后才建模）：")
    cmd = [f'extract_plan.py "{os.path.basename(args.image)}"']
    if args.calib_mm and calib:
        cmd.append(f'--calib {args.calib_mm:.0f} --calib-px {calib:.1f}')
    else:
        cmd.append('--calib <你给的毫米数> --calib-px ' +
                   (f'{calib:.1f}' if calib else '<像素跨度>'))
    cmd.append('--unit mm --outer-t <外墙厚> --inner-t <内墙厚> --out plan_extracted.json')
    print("   " + " ".join(cmd))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
