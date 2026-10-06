#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从建筑描述 JSON 生成 SketchUp 模型，并逐项自检。

用法：python build_from_json.py test_house.json
      python build_from_json.py test_house.json --keep   # 不清空已有模型
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
    for _d in ['.', 'tools/cad', 'tools/img']:
        _p = _op.normpath(_op.join(_cur, _d))
        if _p not in _sys.path:
            _sys.path.insert(0, _p)


_dsh_bootstrap()

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sk_client import SC, BridgeError  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

# ⚠️ 生成器不与本脚本同目录：本脚本在 tools/build/，而 build_from_plan.rb
# 在**工作区根目录**（装机包里可能在 dsh_bridge/）。所以按名字在几个候选位置找，
# 不能直接 os.path.join(HERE, ...) —— 那样 load 会报 LoadError。
def _find_root(start):
    cur = start
    for _ in range(5):
        if os.path.exists(os.path.join(cur, 'sk_client.py')):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return start


ROOT = _find_root(HERE)


def _find_generator(name="build_from_plan.rb"):
    for cand in (os.path.join(ROOT, name),
                 os.path.join(ROOT, "dsh_bridge", name),
                 os.path.join(HERE, name)):
        if os.path.exists(cand):
            return cand
    return os.path.join(ROOT, name)      # 找不到也返回一个可报错的路径


GENERATOR = _find_generator()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("plan", help="建筑描述 JSON 文件")
    ap.add_argument("--discard", action="store_true",
                    help="允许清空**有未保存改动**的当前文档（默认拒绝）")
    ap.add_argument("--keep", action="store_true", help="不清空已有模型")
    ap.add_argument("--shot", default="plan-build", help="截图名（空字符串则不截图）")
    ap.add_argument("--questions-only", action="store_true",
                    help="只检查数据并列出疑问清单，不建几何"
                         "（**现在的默认行为就是这个**，此参数保留是为了兼容旧调用）")
    ap.add_argument("--confirm", action="store_true",
                    help="确认数据与疑问清单无误，**开始建几何**。"
                         "不加这个参数时只审查、不碰模型——"
                         "按工作政策「先向用户展示数据与疑问清单确认，再建模」")
    ap.add_argument("--generator", default=None,
                    help="指定生成器 .rb（默认 build_from_plan.rb）。"
                         "用于反向验证：指向一个故意改坏的副本来确认检查能抓到错误")
    args = ap.parse_args()
    # 未显式确认 → 只审查不建。旧调用里显式用 --questions-only 的也照旧。
    review_only = (not args.confirm) or args.questions_only

    with open(args.plan, encoding="utf-8") as f:
        data = json.load(f)

    meta = data.get("meta") or {}
    n_walls = len(data.get("walls") or [])
    n_floors = len(data.get("floors") or [])
    n_open = sum(len(w.get("openings") or []) for w in (data.get("walls") or []))
    print(f"== 读取 {os.path.basename(args.plan)}：{meta.get('name', '(无名称)')}")
    print(f"   {n_floors} 个楼板 / {n_walls} 面墙 / {n_open} 个洞口")

    c = SC(timeout=180)

    if review_only:
        # 按工作政策：先出疑问清单，让用户确认后再建。所以这里不碰模型。
        print()
        print("== 疑问清单（只检查数据，不建几何）")
        gen_path = GENERATOR.replace("\\", "/")
        plan_path = os.path.abspath(args.plan).replace("\\", "/")
        code = "\n".join([
            f"load '{gen_path}'",
            f"data = JSON.parse(File.read('{plan_path}'))",
            "puts JSON.generate(DshBuild.questions_for(data))",
        ])
        try:
            r = c.ruby(code, undo=False, timeout=120)
        except BridgeError as e:
            print(f"   ❌ [{e.code}] {str(e)[:400]}")
            return 1
        out = str(r.get("output", "")).strip()
        qs = None
        for line in out.splitlines()[::-1]:
            if line.strip().startswith("["):
                try:
                    qs = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
        if qs is None:
            print("   ⚠️ 没解析到清单，原始输出：" + out[:600])
            return 1
        if not qs:
            print("   ✅ 没有需要确认的地方（所有尺寸都标了 source: dim 且置信度足够）")
        else:
            print(f"   共 {len(qs)} 处需要你确认：")
            print()
            for i, q in enumerate(qs, 1):
                print(f"   {i}. 【{q['at']}】")
                print(f"      为什么问：{q['why']}")
                print(f"      {q['ask']}")
                print()
        # 必须在这里返回：语义是"只审查、不建几何"。
        # 少这个 return 就会顺着往下清空模型并开工，正好违反"先问后建"。
        print()
        print("=" * 66)
        if qs:
            print(f"⚠️ 有 {len(qs)} 处待你确认。**我没有动模型。**")
        else:
            print("✅ 数据齐全，没有疑问。**我没有动模型。**")
        print("   确认无误后，加 --confirm 我才开始建模：")
        print(f"     build_from_json.py {os.path.basename(args.plan)} --confirm")
        return 0

    if not args.keep:
        # ⚠️ 清空前先看：**当前文档是不是用户的工作现场**。
        #
        # 为什么加这道闸：我的测试脚本（verify_flow / verify_cad / verify_restart /
        # verify_pipeline）都会调这个入口重建模型，于是**把用户正开着的文档清掉**。
        # 实测：用户的两层楼工作模型被合成测试住宅顶掉了三次，
        # 他以为"模型突然变成了最早试验的那个"。
        #
        # 判据两条，**缺一不可**：
        #   · modified? = true  → 有未保存改动
        #   · 顶层组 > 0        → 文档里有东西（**哪怕已经存过盘**）
        # 只查第一条会漏：测试先重建一次，modified 就变 false 了，
        # 第二次清空被放行——等于没挡住。刚打开的文档也是 false，
        # 但它同样是用户的工作。
        try:
            st = c.ruby('m = Sketchup.active_model; '
                        'puts [m.modified?.to_s, m.title.to_s, '
                        'm.entities.grep(Sketchup::Group).size.to_s].join("|")',
                        undo=False)
            parts = (st.get('output', '').strip().split('|') + ['', '', ''])[:3]
            mod, title, ngrp = parts[0], parts[1], parts[2]
        except BridgeError:
            mod, title, ngrp = 'false', '', '0'
        try:
            n_i = int(ngrp)
        except (TypeError, ValueError):
            n_i = 0
        if (mod == 'true' or n_i > 0) and not args.discard:
            print()
            print("   ⛔ 拒绝清空：当前文档里已经有东西")
            print(f"      文档：{title or '(未命名)'}   顶层组 {ngrp}"
                  f"   未保存改动 {mod}")
            print("      这个入口会先清空模型再重建，现有内容会丢。")
            print("      确实要覆盖请加 --discard；想保留请先自己存盘。")
            return 3
        print()
        print("== 清空模型")
        try:
            r = c.erase(all_=True, confirm=True)
            print(f"   清掉 {r['erased']} 个顶层实体")
        except BridgeError as e:
            print(f"   ❌ [{e.code}] {str(e)[:200]}")
            return 1

    print()
    print("== 生成几何")
    gen = args.generator or GENERATOR
    if not os.path.isabs(gen):
        gen = _find_generator(gen) if not os.path.isabs(gen) else gen
    gen_path = os.path.abspath(gen).replace("\\", "/")
    plan_path = os.path.abspath(args.plan).replace("\\", "/")
    print(f"   生成器：{os.path.basename(gen_path)}")
    # 说明：用 load 而不是 require——这样每次都能重新加载生成器，
    # 我改完生成器不用重启 SketchUp（沿用 dsh_handlers 的热重载思路）
    code = "\n".join([
        f"load '{gen_path}'",
        f"data = JSON.parse(File.read('{plan_path}'))",
        "report = DshBuild.build(data)",
        "puts JSON.generate(report)",
    ])
    try:
        r = c.ruby(code, op_name=f"DSH 生成：{meta.get('name', '建筑')}", timeout=240)
    except BridgeError as e:
        print(f"   ❌ [{e.code}] {str(e)[:900]}")
        return 1

    out = str(r.get("output", "")).strip()
    report = None

    def _find_report(text):
        """在输出里找那个 JSON 报告对象。
        不能用"最后一行"——报告可能被后面接的 measure/截图输出顶掉位置。
        从每个 '{' 起用 JSONDecoder.raw_decode 试，取最长的那个能解析成功的。"""
        dec = json.JSONDecoder()
        best = None
        i = 0
        while True:
            i = text.find("{", i)
            if i == -1:
                break
            try:
                obj, _ = dec.raw_decode(text[i:])
                if isinstance(obj, dict) and "built" in obj:
                    if best is None or len(obj.get("built", [])) > len(best.get("built", [])):
                        best = obj
            except json.JSONDecodeError:
                pass
            i += 1
        return best

    def _find_brief(text):
        """截断后的兜底：从 `"brief":[` 起用方括号配对切出这一段并解析。
        brief 排在 JSON 最前面，所以截断时它通常是完整的。"""
        key = '"brief"'
        i = text.find(key)
        if i == -1:
            return None
        j = text.find("[", i)
        if j == -1:
            return None
        depth = 0
        in_str = False
        esc = False
        for k in range(j, len(text)):
            ch = text[k]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[j:k + 1])
                    except json.JSONDecodeError:
                        return None
        return None

    report = _find_report(out)
    if report is None:
        # 退一步：逐行试（老办法）
        for line in out.splitlines()[::-1]:
            line = line.strip()
            if line.startswith("{"):
                try:
                    cand = json.loads(line)
                    if isinstance(cand, dict) and ("built" in cand or "brief" in cand):
                        report = cand
                        break
                except json.JSONDecodeError:
                    continue

    # 报告被截断时，`brief` 仍然完整（它排在 JSON 最前面且体积小）。
    # 这时只能看摘要——必须**说清楚**，不能让"信息缺失"看起来像"没建出来"。
    truncated = False
    if report is None:
        brief = _find_brief(out)
        if brief:
            report = {"brief": brief, "built": []}
            truncated = True

    if report is None:
        print("   ⚠️ 没解析到结构化报告，原始输出：")
        print("   " + out[:1500])
    else:
        if truncated:
            print("   ⚠️ 完整报告被输出上限截断了（模型规模大时会发生）。"
                  "下面只显示**摘要**——每项都建成了，只是细节字段没传回来。")
            print()
            print("   ── 摘要")
            for b in report.get("brief") or []:
                print("      " + "  ".join(f"{k}={v}" for k, v in b.items() if v is not None))
            print()
            tl = sum(1 for _ in (report.get("brief") or []))
            print(f"   ── 摘要共 {tl} 个构件（细节请在模型里用 diag 脚本查看）")
            return 0
        print(f"   changed={r['changed']} delta={r['delta']}")
        print(f"   构件 {len(report.get('built', []))} 个，顶层组 {report.get('total_groups')}")
        print()
        print("   ── 构件明细")
        for b in report.get("built", []):
            if b["kind"] == "wall":
                top = b.get("top_mm")
                flag = "✅" if top is not None and abs(top - 2800) < 1 else "⚠️"
                print(f"   {flag} 墙 {b['name']:<14} 长 {b['length_mm']:>7}mm  "
                      f"拆成 {b['slabs']} 块  洞口 {b['openings']} 个  顶面 {top}mm")
                for j in b.get("joinery") or []:
                    if j.get("error"):
                        print(f"         ❌ 门窗 {j['label']}: {j['error']}")
                    else:
                        sz = j.get("size") or [0, 0, 0]
                        kind = "门" if j.get("type") == "door" else "窗"
                        print(f"         └ {kind} {j['label']:<10} "
                              f"{sz[0]:.0f}×{sz[1]:.0f}mm 窗台{sz[2]:.0f}  {j['panels']} 块料")
            elif b["kind"] == "room":
                flag = "✅" if b.get("valid") else "⚠️"
                ceil = b.get("ceiling") or 0
                ceil_s = f"  天花 +{ceil:.0f}mm" if ceil else "  (无天花)"
                print(f"   {flag} 房间 {b['name']:<12} {b['size_mm'][0]:.0f}×{b['size_mm'][1]:.0f}mm"
                      f"  角点 {b['min_mm']}{ceil_s}")
                for issue in b.get("issues") or []:
                    print(f"         └ {issue}")
            elif b["kind"] == "envelope":
                zr = b.get("z_range") or [0, 0]
                print(f"   ✅ 整层顶板 {b['name']:<14} {b['size_mm'][0]:.0f}×{b['size_mm'][1]:.0f}mm  "
                      f"z={zr[0]:.0f}..{zr[1]:.0f}  坐在 {b['rests_on']}  出挑 {b['eave']:.0f}")
            elif b["kind"] == "roof":
                rg = b.get("ridge_z")
                zr = b.get("z_range")
                tag = f"屋脊 {rg}" if rg else "平屋面"
                ztxt = f"  实测 z={zr[0]}..{zr[1]}" if zr else ""
                print(f"   ✅ 屋面 {b['name']:<16} {b['form']:<6} 坡 {b['pitch_deg']:.1f}°  "
                      f"{tag}  基面 {b['base_z']}{ztxt}  厚 {b['thickness']:.0f} "
                      f"出挑 {b['eave']:.0f}  {b['pieces']} 块")
            elif b["kind"] == "furniture":
                flag = "⚠️" if b.get("confidence") == "low" else "✅"
                basis = f"  ← {b['basis']}" if b.get("basis") else "  ← ⚠️ 没写依据"
                print(f"   {flag} 家具 {b['name']:<8} {b.get('ftype', '?'):<9} "
                      f"@{b['at']} 角{b['angle']:.0f}°  "
                      f"{b['size'][0]:.0f}×{b['size'][1]:.0f}（顶面 {b['size'][2]:.0f}）  "
                      f"{b['parts']} 块{basis}")
            elif b["kind"] == "stair":
                flag = "⚠️" if b.get("warnings") else "✅"
                mode = b.get("mode") or "single"
                if mode != "single":
                    # 多跑（2 跑 / 4 跑等价拆分）：字段是 tread1/tread2，没有 tread
                    label = {"two_flight": "双跑", "4_flight": "四跑"}.get(mode, mode)
                    td = "/".join(str(b[k]) for k in ("tread1", "tread2") if b.get(k))
                    print(f"   {flag} 楼梯 {b['name']:<12} **{label}** {b['steps']} 级 "
                          f"(踏面宽 {td})  踏面高 {b['rise']}mm  总高 {b['height']:.0f}  "
                          f"水平投影 {b['run']:.0f}  {b['pieces']} 块")
                else:
                    print(f"   {flag} 楼梯 {b['name']:<12} {b['steps']} 级  "
                          f"踏面高 {b['rise']}mm × 踏面宽 {b['tread']}mm  "
                          f"梯宽 {b['width']:.0f}  总高 {b['height']:.0f}  水平投影 {b['run']:.0f}")
                for w in b.get("warnings") or []:
                    print(f"         └ {w}")
            elif b["kind"] == "elevation":
                name = b.get("name", "?")
                ur, zr = b.get("u_range") or [0, 0], b.get("z_range") or [0, 0]
                flag = "⚠️" if b.get("warning") else "✅"
                print(f"   {flag} 立面 {name:<18} 沿墙 {ur[0]:.0f}..{ur[1]:.0f}  "
                      f"标高 {zr[0]:.0f}..{zr[1]:.0f}  厚 {b.get('thickness'):.0f}  "
                      f"洞口 {b.get('holes', 0)} 个  挂在 {b.get('base_wall')}")
                if b.get("warning"):
                    print(f"         └ {b['warning']}")
            elif b["kind"] == "floor":
                print(f"      floor {b['name']:<12} 尺寸 {b['size_mm']}  z={b.get('min_z')}")
            else:
                print(f"      {b['kind']} {b.get('name')}")
        if report.get("warnings"):
            print()
            print("   ── 警告")
            for w in report["warnings"]:
                print(f"   ⚠️ {w}")
        if report.get("materials"):
            m = report["materials"]
            print()
            print("   ── 材质")
            for nm, cnt in sorted((m.get("applied") or {}).items(), key=lambda kv: -kv[1]):
                tag = "（新建）" if nm in (m.get("created") or []) else ""
                print(f"      {nm}{tag}: {cnt} 个构件")
            for f in (m.get("failed") or []):
                print(f"      ❌ {f}")
            if not m.get("applied"):
                print("      （没有构件匹配到材质规则）")
        if report.get("errors"):
            print()
            print("   ── 错误")
            for e_ in report["errors"]:
                print(f"   ❌ {e_}")

    print()
    print("== measure 核对关键尺寸（期望值**从本次数据推导**，不硬编码）")
    # 之前这里写死了 test_house 的期望值（8000 长度、900 窗台），
    # 拿它去核对别的图纸就会误报。改为从 data 推导。
    checks = []
    for w in (data.get("walls") or [])[:2]:
        fx, fy = w["from"]
        tx, ty = w["to"]
        length = ((tx - fx) ** 2 + (ty - fy) ** 2) ** 0.5
        checks.append((f"{w['name']} 轴线长度", (fx, fy, 0), (tx, ty, 0), length))
        for o in (w.get("openings") or [])[:1]:
            u = o["u"]
            checks.append((f"{w['name']} 首个洞口净宽",
                           (fx + u, fy, 10), (fx + u + o["width"], fy, 10), o["width"]))
        h = w.get("height", 0)
        checks.append((f"{w['name']} 墙高", (fx + 100, fy, 0), (fx + 100, fy, h), h))
    for f in (data.get("floors") or [])[:1]:
        xs = [p[0] for p in f["polygon"]]
        ys = [p[1] for p in f["polygon"]]
        checks.append((f"{f['name']} 宽度", (min(xs), min(ys), 0), (max(xs), min(ys), 0),
                       max(xs) - min(xs)))

    if not checks:
        print("   （数据里没有可核对的墙/楼板）")
    for label, a, b, expect in checks:
        try:
            got = c.measure(a, b)["distance_mm"]
            flag = "✅" if abs(got - expect) < 1.5 else "⚠️"
            print(f"   {flag} {label}: 实测 {got}mm（按数据算 {expect}mm）")
        except BridgeError as e:
            print(f"   ❌ {label}: [{e.code}] {str(e)[:120]}")

    print()
    print("== 分组统计")
    try:
        i = c.info(scope="top", limit=200)
        from collections import Counter
        names = [e.get("name") or e["type"] for e in i["entities"]]
        pref = Counter(n.split("-")[0] for n in names)
        print(f"   顶层实体 {i['counts']['top_level']}（组 {i['counts']['groups']}）")
        print(f"   组名前缀分布: {dict(pref)}")
        print(f"   模型总范围: {i['model_bbox']['size_mm']} mm")
    except BridgeError as e:
        print(f"   ❌ [{e.code}]")

    if args.shot:
        print()
        print("== 截图")
        # 注意：文件名必须用 --shot 的值。我最早写死了 plan-34/plan-top，
        # 于是 --shot 参数完全失效（传什么都不变），排查时被文件名误导过一次。
        for name, cam in (
            (f"{args.shot}-34", {"eye": [9500, -8000, 7000], "target": [3000, 4000, 1200],
                                 "up": [0, 0, 1], "perspective": True, "fov": 45}),
            (f"{args.shot}-top", {"eye": [3000, 4000, 15000], "target": [3000, 4000, 0],
                                  "up": [0, 1, 0], "perspective": True, "fov": 35}),
            # 平行投影俯视：像一张平面图，便于核对布局
            (f"{args.shot}-plan", {"eye": [3000, 4000, 20000], "target": [3000, 4000, 0],
                                   "up": [0, 1, 0], "perspective": False}),
        ):
            try:
                s = c.shot(name, width=1400, height=1000, camera=cam, timeout=120)
                print(f"   ✅ {s['path']}")
            except BridgeError as e:
                print(f"   ❌ {name}: [{e.code}] {str(e)[:200]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
