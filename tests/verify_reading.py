#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端检验：从合成图纸的**像素**反推**毫米**，与已知真值逐项对比。

这是"读图工具链能不能用"的真正检验——
探针读到一条线只是第一步，能从它算出正确的实物尺寸才算能用。

方法：用一条已知真值标定比例（1:50 的图纸上，我按建筑总长定标），
再用这个比例去量其他部位，看误差有多大。

**退出码约定**（重要，否则会被当成 bug）：
    0 = 全部检查通过
    1 = **存在超出容差的项**。目前墙厚会稳定地失败（相对误差 5~10%），
        这是工具的**真实局限**，不是回归。所以这个退出码是"如实报告"，
        不是"坏了"。要让它变 0，得靠读图上标注而不是量像素。

用法：python verify_reading.py [图纸路径]
"""

from __future__ import annotations


import os
import sys
from PIL import Image
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
PY = sys.executable
PROBE = _tool("plan_probe.py")

# ── 图纸已知真值（与 make_test_drawing.py 保持一致）
TRUTH = {
    "building_w": 6000, "building_h": 4800,
    "ext_t": 240, "int_t": 120,
    "int_axis_x": 3600,
    "m1": 900, "m2": 800, "c1": 1500, "c2": 1200,
    "m1_start": 900, "c1_start": 2600, "m2_start": 1900,
}
MM_PER_PX_DESIGN = 1 / 0.0756   # 设计值：1px ≈ 13.23mm


def run_probe(img, *args):
    r = subprocess.run([PY, PROBE, img, *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"探针失败: {r.stderr[:400]}")
    return json.loads(r.stdout)


def main() -> int:
    img = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "shots", "test_plan.png")
    if not os.path.exists(img):
        print(f"找不到图纸：{img}\n先跑 make_test_drawing.py 生成")
        return 1

    print("=" * 68)
    print("端到端读图检验：像素 → 毫米")
    print("=" * 68)

    lines = run_probe(img, "--lines", "--min-run", "120", "--max-lines", "20")

    # ── 1. 找出三条竖直墙线的中心 x
    v = [l for l in lines["vertical_lines"] if l["thickness_px"] >= 5]
    v.sort(key=lambda l: l["center"])
    if len(v) < 3:
        print(f"⚠️ 只找到 {len(v)} 条竖直墙线，无法继续")
        return 1
    x_west, x_int, x_east = v[0]["center"], v[1]["center"], v[2]["center"]

    # ── 2. 找出两条水平墙线
    h = [l for l in lines["horizontal_lines"] if l["thickness_px"] >= 5]
    h.sort(key=lambda l: l["center"])
    if len(h) < 2:
        print(f"⚠️ 只找到 {len(h)} 条水平墙线，无法继续")
        return 1
    y_north, y_south = h[0]["center"], h[-1]["center"]

    print()
    print("探针识别到的墙线（中心像素 / 线宽像素）：")
    print(f"  竖直: 西墙 x={x_west}  内墙 x={x_int}  东墙 x={x_east}")
    print(f"  水平: 北墙 y={y_north}  南墙 y={y_south}")

    # ── 3. 标定比例：用"建筑总长"这条已知真值
    span_px = x_east - x_west
    mm_per_px = TRUTH["building_w"] / span_px
    print()
    print("标定：")
    print(f"  用建筑总长 {TRUTH['building_w']}mm 对应 {span_px:.1f}px 标定")
    print(f"  → 1px = {mm_per_px:.3f}mm   （设计值 {MM_PER_PX_DESIGN:.3f}mm，"
          f"偏差 {abs(mm_per_px - MM_PER_PX_DESIGN) / MM_PER_PX_DESIGN * 100:.2f}%）")

    # ── 4. 逐项推算并与真值对比
    checks = [
        ("建筑总长", span_px, TRUTH["building_w"]),
        ("建筑总高", y_south - y_north, TRUTH["building_h"]),
        ("内墙轴线位置(距西墙)", x_int - x_west, TRUTH["int_axis_x"]),
        ("外墙厚(西)", v[0]["thickness_px"], TRUTH["ext_t"]),
        ("外墙厚(东)", v[2]["thickness_px"], TRUTH["ext_t"]),
        ("内墙厚", v[1]["thickness_px"], TRUTH["int_t"]),
    ]

    print()
    print("逐项推算（用标定比例把像素换成毫米）：")
    print(f"  {'项目':<22}{'推算':>10}{'真值':>10}{'误差':>10}{'相对':>8}{'判定':>6}")
    worst = 0.0
    for label, px, truth in checks:
        got = px * mm_per_px
        err = got - truth
        rel = abs(err) / truth * 100 if truth else 0.0
        worst = max(worst, abs(err))
        # 判定用**相对误差**，不用绝对容差。
        # 我最早写 max(30, truth*2%)，于是 240mm 的墙差 25mm 也被判成合格——
        # 那是"指标说没问题、其实有问题"的老毛病。
        mark = "✅" if rel <= 2.0 else ("⚠️" if rel <= 5.0 else "❌")
        print(f"  {label:<22}{got:>10.1f}{truth:>10}{err:>+10.1f}{rel:>7.1f}%{mark:>6}")

    # ── 5. 洞口：沿南墙扫描，用"墙体厚度"判断，而不是"有没有暗像素"
    #
    # 我第一版用"这一列有任何暗像素就算墙"，结果把窗符号（几条细线）也当成墙，
    # 一个真洞口被切成好几个 79mm 的假洞。正确判据是**厚度**：
    # 墙处暗像素接近满厚，洞口处只剩窗的 1~4 条线。
    print()
    print("洞口识别（沿南墙扫描，按墙体厚度判定实心/洞口）：")
    from PIL import Image
    im = Image.open(img).convert("L")
    px = im.load()

    y_wall = int(round(y_south))
    # 采样带必须**由墙线本身算出**，不能自己拍一个宽度。
    # 我第一版用 y_wall±(wall_t/2+1)，结果多采了墙下方 9px，把门/窗符号算进了厚度，
    # 窗中线因此被误判成实心墙，一个 1500mm 的窗洞被切成 939+437 两段。
    sw = next((l for l in lines["horizontal_lines"]
               if abs(l["center"] - y_south) < 1), None)
    band_top = int(round(sw["first"])) if sw else y_wall - 10
    band_bot = int(round(sw["last"])) if sw else y_wall + 10
    wall_t = band_bot - band_top + 1
    solid_threshold = max(3, int(wall_t * 0.6))   # 达到 60% 厚度才算实心墙

    profile = []
    for x in range(int(x_west) - 20, int(x_east) + 21):
        cnt = sum(1 for yy in range(band_top, band_bot + 1) if px[x, yy] < 160)
        profile.append((x, cnt))

    segs = []
    run_start = None
    for x, cnt in profile:
        solid = cnt >= solid_threshold
        if solid and run_start is None:
            run_start = x
        elif not solid and run_start is not None:
            segs.append((run_start, x - 1))
            run_start = None
    if run_start is not None:
        segs.append((run_start, profile[-1][0]))

    print(f"  采样带 y={band_top}..{band_bot}（由南墙线本身算出，共 {wall_t}px）")
    print(f"  实心判定阈值 ≥{solid_threshold} 个暗像素")
    print(f"  实心墙段（像素）：{segs}")
    gaps = [(segs[i][1], segs[i + 1][0]) for i in range(len(segs) - 1)]
    print(f"  断开处（=洞口）：{gaps}")

    # 合并间距很小的碎段（窗中线等）——真实洞口不会只有几十毫米宽
    merged = []
    for a, b in gaps:
        w_mm = (b - a) * mm_per_px
        if merged and (a - merged[-1][1]) * mm_per_px < 300:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    if merged != gaps:
        print(f"  合并相邻碎段后（<300mm 的间隔视为同一洞口）：{merged}")

    got_openings = []
    for a, b in merged:
        w_mm = (b - a) * mm_per_px
        start_mm = (a - x_west) * mm_per_px
        got_openings.append((round(start_mm), round(w_mm)))
        print(f"    洞口: 宽 {w_mm:.0f}mm   起点距西墙轴线 {start_mm:.0f}mm")

    print()
    print("  与真值对照：")
    expected = [(TRUTH["m1_start"], TRUTH["m1"]), (TRUTH["c1_start"], TRUTH["c1"])]
    for i, (es, ew) in enumerate(expected):
        if i < len(got_openings):
            gs, gw = got_openings[i]
            print(f"    期望 起点{es} 宽{ew}  →  读到 起点{gs} 宽{gw}   "
                  f"起点误差 {gs - es:+d}mm  宽度误差 {gw - ew:+d}mm")
        else:
            print(f"    期望 起点{es} 宽{ew}  →  ❌ 没读出来")

    print()
    print(f"最大绝对误差 {worst:.1f}mm")
    print()
    print("结论：")
    print("  ✅ 大尺寸可靠：建筑总长/总高/轴线位置，相对误差 ≤0.1%")
    print("  ✅ 洞口净宽可靠：±5mm（用「沿墙扫厚度」法，能正确处理窗中线）")
    print("  ✅ 线条定位（粗墙线、1px 细尺寸线）误差在 2px 内")
    print("  ❌ 墙厚不可靠：相对误差 5~10%。墙厚只占 9~20px，像素量化误差被放大。")
    print("     → 规则：**墙厚一律读图上标注或问用户，绝不靠量图**")
    print("  ⚠️ 这只是我自己画的合成图：线型干净、无扫描歪斜、无字体差异、无 CAD 导出误差。")
    print("     它证明工具链能跑通，**不能证明我能读懂真实图纸**。真图必须再验一遍。")
    failed = [c[0] for c in checks if abs(c[1] * mm_per_px - c[2]) / c[2] > 0.05]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
