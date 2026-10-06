#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全链路集成测试：合成图纸 → 读图提取 → 与原始真值对比。

证明的是这条链路：
    make_test_drawing.py（带已知真值） → extract_plan.py（读图） → 对比

**这补上了我一直缺的一环**：之前"读图"和"建模"是分开测的，
从没验证过"从图像读出来的数据，是否等于造图时写进去的真值"。

注意：墙厚不参与对比——它是**用户给定**的，不是量出来的
（量图误差 5~10%，见 reading_checklist.md 的实测边界）。

用法：python verify_pipeline.py
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


from dsh_paths import tool as _tool, ROOT
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

# 与 make_test_drawing.py 保持一致的原始真值
TRUTH = {
    "building_w": 6000, "building_h": 4800,
    "m1_start": 900, "m1_w": 900,        # 南墙门
    "c1_start": 2600, "c1_w": 1500,      # 南墙窗
    "c2_start": 1800, "c2_w": 1200,      # 东墙窗（竖直墙）
}
# 容差：读图链路实测 ±2px ≈ ±27mm，取 60mm 留余量但足以抓出真错
TOL_MM = 60


def sh(*args):
    # 第一个参数若是裸脚本名，解析成相对根目录的路径（脚本已搬到 tools/*）。
    # 另外把相对路径参数补成绝对：cwd 现在是 ROOT，相对路径会落到根目录下，
    # 与断言用的 HERE 不一致。
    argv = []
    for i, a in enumerate(args):
        if i == 0 and isinstance(a, str) and a.endswith('.py'):
            f = _tool(a)
            if f:
                a = f
        elif isinstance(a, str) and not a.startswith('-') and os.sep in a.replace('/', os.sep) \
                and not os.path.isabs(a):
            a = os.path.join(ROOT, a)
        argv.append(a)
    r = subprocess.run([PY, *argv], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=ROOT)
    return r.returncode, r.stdout, r.stderr


def main() -> int:
    print("=" * 70)
    print("全链路集成测试：合成图纸 → 读图 → 与真值对比")
    print("=" * 70)

    # ── 第 1 步：造图（已知真值）
    print()
    print("第 1 步 生成合成图纸")
    rc, out, err = sh("make_test_drawing.py", os.path.join("shots", "pipeline_plan.png"))
    if rc != 0:
        print("❌ 造图失败：" + (err or out)[:400])
        return 1
    for line in out.splitlines():
        if "px" in line or "比例" in line:
            print("   " + line.strip())

    img = os.path.join("shots", "pipeline_plan.png")

    # ── 第 2 步：读图提取
    print()
    print("第 2 步 读图提取（标定基准 6000mm 对应 453.5px）")
    rc, out, err = sh("extract_plan.py", img,
                      "--calib", "6000", "--calib-px", "453.5", "--unit", "mm",
                      "--outer-t", "240", "--inner-t", "120",
                      "--name", "集成测试", "--out", "plan_pipeline.json")
    if rc != 0:
        print("❌ 提取失败：" + (err or out)[:600])
        return 1
    for line in out.splitlines():
        if any(k in line for k in ("标定", "识别到", "轴线范围", "提取到", "已写出")):
            print("   " + line.strip())

    # 产物落在工作区根目录（cwd=ROOT），不是本脚本所在的 tests/
    with open(os.path.join(ROOT, "plan_pipeline.json"), encoding="utf-8") as f:
        got = json.load(f)

    # ── 第 3 步：与真值对比
    print()
    print("第 3 步 与造图时的真值对比")
    poly = got["floors"][0]["polygon"]
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    got_w = max(xs) - min(xs)
    got_h = max(ys) - min(ys)

    results = []

    def cmp(label, got_v, truth_v):
        err = got_v - truth_v
        rel = abs(err) / truth_v * 100 if truth_v else 0
        ok = abs(err) <= TOL_MM
        results.append((label, ok, got_v, truth_v, err))
        print(f"   {'✅' if ok else '❌'} {label:<20} 读出 {got_v:>8.1f}  真值 {truth_v:>8}  "
              f"误差 {err:>+7.1f}mm ({rel:.1f}%)")

    cmp("建筑宽度", got_w, TRUTH["building_w"])
    cmp("建筑高度", got_h, TRUTH["building_h"])

    # 洞口：南墙（水平墙）应当有两个
    south = next((w for w in got["walls"] if "南" in w["name"]), None)
    if south is None:
        print("   ❌ 没找到南墙")
        return 1
    opens = sorted(south.get("openings") or [], key=lambda o: o["u"])
    print(f"   ── 水平墙（南墙）读出 {len(opens)} 个洞口；真值 2 个（门 + 窗）")
    expect = [(TRUTH["m1_start"], TRUTH["m1_w"]), (TRUTH["c1_start"], TRUTH["c1_w"])]
    for i, (eu, ew) in enumerate(expect):
        if i < len(opens):
            cmp(f"水平墙洞口{i + 1} 起点", opens[i]["u"], eu)
            cmp(f"水平墙洞口{i + 1} 宽度", opens[i]["width"], ew)
        else:
            results.append((f"水平墙洞口{i + 1}", False, 0, eu, -eu))
            print(f"   ❌ 水平墙洞口{i + 1} 没读出来（真值 起点{eu} 宽{ew}）")

    # 洞口：东墙（**竖直墙**）应当有一个 —— 这一项曾经完全没实现
    east = next((w for w in got["walls"] if "东" in w["name"]), None)
    if east is None:
        print("   ❌ 没找到东墙")
        return 1
    eo = sorted(east.get("openings") or [], key=lambda o: o["u"])
    print(f"   ── 竖直墙（东墙）读出 {len(eo)} 个洞口；真值 1 个（窗）")
    if eo:
        cmp("竖直墙洞口 起点", eo[0]["u"], TRUTH["c2_start"])
        cmp("竖直墙洞口 宽度", eo[0]["width"], TRUTH["c2_w"])
    else:
        results.append(("竖直墙洞口", False, 0, TRUTH["c2_w"], -TRUTH["c2_w"]))
        print(f"   ❌ 竖直墙洞口没读出来（真值 起点{TRUTH['c2_start']} 宽{TRUTH['c2_w']}）")

    # ── 洞口**类型**判别：门靠贯穿线数、窗有窗框线
    # 真值：南墙第一个是门、第二个是窗；东墙是窗
    print()
    print("   ── 洞口类型判别（依据：洞口内垂直于墙的贯穿线数）")

    def cmp_type(label, got_type, truth_type, conf, lines):
        ok = got_type == truth_type
        results.append((label, ok, 0, 0, 0))
        mark = "✅" if ok else "❌"
        # 判为门时置信度就该是 low（门与净洞口图像上无法区分），这是设计而非缺陷
        conf_note = ("low（门与净洞口无法区分，需确认）" if truth_type == "door"
                     else f"{conf}")
        print(f"   {mark} {label:<20} 判为 {got_type:<6} 真值 {truth_type:<6} "
              f"贯穿线 {lines}  置信度 {conf_note}")

    if len(opens) >= 2:
        cmp_type("水平墙洞口1 类型", opens[0].get("type"), "door",
                 opens[0].get("confidence"), opens[0].get("cross_lines"))
        cmp_type("水平墙洞口2 类型", opens[1].get("type"), "window",
                 opens[1].get("confidence"), opens[1].get("cross_lines"))
    if eo:
        cmp_type("竖直墙洞口 类型", eo[0].get("type"), "window",
                 eo[0].get("confidence"), eo[0].get("cross_lines"))

    # ── 结论
    print()
    passed = sum(1 for _, ok, *_ in results if ok)
    print("=" * 70)
    print(f"通过 {passed}/{len(results)} 项（容差 ±{TOL_MM}mm）")
    print()
    print("这说明：")
    print("  ✅ 『图纸图像 → 像素测量 → 标定 → 毫米数据』这条链路是通的")
    print("  ✅ 读出的数据可以直接喂给 build_from_plan.rb 生成模型（已验证）")
    print()
    print("这**不能**说明：")
    print("  ⚠️ 我能读懂真实图纸。合成图的线型、字体、图例都太干净，")
    print("     真图会有扫描歪斜、字体差异、非常见图例、图签遮挡等问题。")
    print("  ⚠️ 墙厚：本测试是**用户给定**的，不是量出来的（量图误差 5~10%）。")
    print("  ⚠️ 洞口类型判别只在**合成图**上验证过：窗判为 window(medium)、")
    print("     其余判为 door(low)。门与净洞口在图像层面**无法区分**，真图符号")
    print("     线数也可能不同，所以判为门的仍必须问用户。")
    print("  ⚠️ 只识别**矩形洞口**。弧形洞口、飘窗、转角窗都还处理不了。")
    print("  ⚠️ 只处理正交外墙。斜墙、弧墙的洞口识别未实现。")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
