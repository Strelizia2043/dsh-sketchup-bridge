#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""完整工作流测试：图纸 → 进件评估 → 提取 → 疑问清单 → 建模 → 几何自检。

为什么单独做这一条（而不是只测各环节）：
前 27 轮我一直在测**各环节**（提取精度、退化鲁棒性、建模几何），
但**从没端到端跑过一次真实工作流**——即"用户发图 → 我判断 → 提取 →
把疑问清单给他 → 他确认 → 建模 → 自检"。

本测试的核心断言是一条**政策性**的、而不是数值性的：

    **凡是标了 confidence=low 的构件，必须出现在疑问清单里。**

因为目标里写着"遇到图纸上无法识别的符号或尺寸必须询问用户而非猜测"。
如果某个低级项没有进清单，那就是**在静默猜测**——
数值可能碰巧对，但流程已经违反了要求。
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
WORK = os.path.join(HERE, "flow_out")
TOL = 60.0


def sh(*args, timeout=600) -> tuple[int, str, str]:
    # 第一个参数若是**裸脚本名**，先解析成相对根目录的路径。
    # 重组目录后脚本搬到了 tools/img|build/，直接 `python extract_plan.py` 会
    # 报 can't open file（而且不产生 Traceback）。
    argv = list(args)
    if argv and isinstance(argv[0], str) and argv[0].endswith('.py'):
        _f = _tool(argv[0])
        if _f:
            argv[0] = os.path.relpath(_f, ROOT).replace('\\', '/')
    r = subprocess.run([PY, *argv], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return r.returncode, r.stdout or "", r.stderr or ""


def sh_abs(*args, timeout=600) -> tuple[int, str, str]:
    """同 sh()，但把路径参数（可能出现的位置）也转成绝对路径。

    需要它是因为：cwd 改成了 ROOT，而调用方仍传相对路径的**产物路径**
    （如 "flow_out/s1.png"）。那会写到根目录下，与断言用的 HERE/flow_out 不一致。
    """
    argv = [a for a in args]
    if argv and isinstance(argv[0], str) and argv[0].endswith('.py'):
        _f = _tool(argv[0])
        if _f:
            argv[0] = _f
    fixed = []
    for a in argv:
        if isinstance(a, str) and not a.startswith('-') and os.sep in a.replace('/', os.sep) \
                and not os.path.isabs(a):
            fixed.append(os.path.join(ROOT, a))
        else:
            fixed.append(a)
    r = subprocess.run([PY, *fixed], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return r.returncode, r.stdout or "", r.stderr or ""


class Check:
    def __init__(self):
        self.items = []

    def ok(self, name, cond, detail=""):
        self.items.append((name, bool(cond), detail))

    def report(self, title):
        print()
        print(f"== {title}")
        bad = 0
        for name, good, detail in self.items:
            print(f"   {'✅' if good else '❌'} {name}" + (f"   {detail}" if detail else ""))
            if not good:
                bad += 1
        return bad


def main() -> int:
    os.makedirs(WORK, exist_ok=True)
    total_bad = 0

    # ── 场景 1：干净图纸（正常路径）
    img = os.path.join(WORK, "s1.png")
    rc, out, err = sh("make_test_drawing.py", img)
    if rc != 0:
        print("❌ 造图失败：" + (err or out)[-200:])
        return 1

    c1 = Check()

    # 步骤 1 进件评估
    rc, out, err = sh("intake_check.py", img, "--calib-mm", "6000")
    c1.ok("步骤1 进件评估通过", rc == 0, f"退出码 {rc}")
    c1.ok("进件评估给出标定基准", "--calib-px" in out)

    # 步骤 2 提取
    plan = os.path.join(WORK, "s1.json")
    rc, out, err = sh("extract_plan.py", img, "--calib", "6000", "--calib-px", "453.5",
                      "--unit", "mm", "--outer-t", "240", "--inner-t", "120",
                      "--out", plan)
    c1.ok("步骤2 提取成功", rc == 0 and os.path.exists(plan))
    if not os.path.exists(plan):
        print("❌ 提取失败：" + (out or err)[-300:])
        return 1
    data = json.load(open(plan, encoding="utf-8"))

    # 数值精度
    walls = data.get("walls") or []
    xs = [w["from"][0] for w in walls] + [w["to"][0] for w in walls]
    ys = [w["from"][1] for w in walls] + [w["to"][1] for w in walls]
    W = max(xs) - min(xs)
    H = max(ys) - min(ys)
    c1.ok("建筑宽度在容差内", abs(W - 6000) <= TOL, f"{W:.0f} vs 6000（差 {W - 6000:+.0f}）")
    c1.ok("建筑高度在容差内", abs(H - 4800) <= TOL, f"{H:.0f} vs 4800（差 {H - 4800:+.0f}）")

    # 步骤 3 疑问清单
    rc, out, err = sh("build_from_json.py", plan, "--questions-only")
    c1.ok("步骤3 疑问清单可生成", rc == 0)
    qtext = out

    # ★ 核心政策性断言：low 置信度的构件必须出现在疑问清单里
    lows = []
    for w in walls:
        for o in w.get("openings") or []:
            if o.get("confidence") == "low":
                lows.append(o.get("label") or f"{w['name']}-洞")
        if w.get("confidence") == "low":
            lows.append(w.get("name"))
    missing = [lab for lab in lows if lab.split("/")[-1].strip() not in qtext and lab not in qtext]
    c1.ok("所有 low 置信度项都进了疑问清单", not missing,
          f"共 {len(lows)} 项，漏 {len(missing)}" + (f"：{missing}" if missing else ""))

    # 疑问清单必须提到墙厚（墙厚不可量，必须问）
    c1.ok("疑问清单提到了墙厚", "墙厚" in qtext)

    # ★ 契约的**行为验证**：提取器写进 note 的说明，必须原样到达用户。
    #
    # 静态字段检查（场景 6）只能证明"字段存在"；这条证明"内容被用上了"。
    # 如果 build_from_plan.rb 哪天不再读 note，疑问清单会变成一句空洞的
    # "我推算出来的"，用户拿不到任何可核对的理由——而字段检查仍然全绿。
    #
    # 取每个 low 洞口 note 里的一段特征文字，验证它出现在清单里。
    low_open = [o for w in walls for o in (w.get("openings") or [])
                if o.get("confidence") == "low" and o.get("note")]
    if low_open:
        # note 常以"⚠️ "或"判为X："开头，取中间一段实词来比对
        probes = []
        for o in low_open[:2]:
            nt = o["note"]
            seg = nt.split("。")[0][:18].strip()
            if len(seg) >= 8:
                probes.append(seg)
        hit = [p for p in probes if p in qtext]
        c1.ok("★ 低置信度洞口的 note 原文到达了疑问清单",
              bool(probes) and len(hit) == len(probes),
              f"抽查 {len(probes)} 段，命中 {len(hit)}")
    else:
        c1.ok("★ 低置信度洞口的 note 到达了疑问清单", True, "本例没有 low 洞口，跳过")

    # 步骤 4 建模
    #
    # ⚠️ 必须显式加 --confirm：Round 30 起 `build_from_json.py` **默认只审查不建模**
    # （按工作政策「先向用户展示数据与疑问清单确认，再建模」）。
    # 以前默认就建，等于**默认绕过确认环节**。
    rc, out, err = sh("build_from_json.py", plan, "--confirm", "--discard")
    c1.ok("步骤4 建模成功", rc == 0 and "构件" in out)
    c1.ok("建模无报错", "❌" not in out, "")

    # 步骤 5 几何自检
    rc, out, err = sh("check_geometry.py", plan)
    c1.ok("步骤5 几何自检通过", rc == 0, f"退出码 {rc}")

    total_bad += c1.report("场景 1：干净图纸（1:50 mm）")

    # ── 场景 2：带"被合并洞口"的图纸（不确定路径）
    img2 = os.path.join(WORK, "s2.png")
    rc, out, err = sh("make_test_drawing.py", img2, "--m1", "2000", "--c1", "2000",
                      "--m1-u", "200", "--c1-u", "2400")
    if rc == 0:
        plan2 = os.path.join(WORK, "s2.json")
        rc2, out2, _ = sh("extract_plan.py", img2, "--calib", "6000", "--calib-px", "453.5",
                          "--unit", "mm", "--outer-t", "240", "--inner-t", "120",
                          "--out", plan2)
        c2 = Check()
        c2.ok("带窄墙垛的图纸能提取", rc2 == 0 and os.path.exists(plan2))
        if os.path.exists(plan2):
            d2 = json.load(open(plan2, encoding="utf-8"))
            merged = [o for w in d2.get("walls") or []
                      for o in (w.get("openings") or []) if o.get("merged_piers")]
            c2.ok("检测到墙垛合并并留了记录", bool(merged),
                  f"{len(merged)} 个洞口带 merged_piers")
            c2.ok("被合并的洞口标为 low", all(o.get("confidence") == "low" for o in merged))
            c2.ok("被合并的洞口带说明", all("核对" in (o.get("note") or "") for o in merged))
            rc3, out3, _ = sh("build_from_json.py", plan2, "--questions-only")
            c2.ok("★ 被合并的洞口进了疑问清单",
                  any((o.get("label") or "") in out3 for o in merged),
                  "这一条是政策性断言：不确定必须问用户，不许静默猜")
        total_bad += c2.report("场景 2：含窄墙垛 / 洞口可能被合并（不确定路径）")

    # ── 场景 4：合并警告必须**只落在真正受影响的洞口**上
    #
    # 我第一版把"这面墙合并过几次"当成整面墙的属性，
    # 于是同墙上所有洞口都被打警告。实测：南墙 1 处合并，却有 2 个洞口被标
    # "可能实际是两个洞口"——其中一个完全没问题。
    # **过量警告会让用户怀疑正确的项，也会削弱警告本身的可信度。**
    c4 = Check()
    allops = [o for w in walls for o in (w.get("openings") or [])]
    flagged = [o for o in allops if o.get("merged_piers")]
    c4.ok("有洞口被标记为合并过", bool(flagged),
          f"{len(flagged)}/{len(allops)} 个洞口带 merged_piers")
    # 若同墙上有多个洞口，不能全部被标记（除非确实都合并过）
    for w in walls:
        ops = w.get("openings") or []
        if len(ops) >= 2:
            n_flag = sum(1 for o in ops if o.get("merged_piers"))
            c4.ok(f"{w['name']} 上的合并警告没有波及全部洞口",
                  n_flag < len(ops),
                  f"{len(ops)} 个洞口中有 {n_flag} 个被标记")
    total_bad += c4.report("场景 4：合并警告的归属精度")

    # ── 场景 3：不给墙厚 → 必须打回（这是最硬的边界）
    #
    # 墙厚只占图上 9~20px，量图的相对误差 5~10%，**不可用**。
    # 所以"不给墙厚就打回"是设计上的硬约束，必须测到。
    # 顺带测单位：不给 --unit 时也应当走到默认值而不是崩掉。
    c3 = Check()
    rc, out, err = sh("extract_plan.py", img, "--calib", "6000", "--calib-px", "453.5",
                      "--unit", "mm", "--out", os.path.join(WORK, "s3.json"))
    c3.ok("不给墙厚时打回", rc != 0, f"退出码 {rc}")
    c3.ok("打回理由说明了墙厚不可量", "墙厚" in out and ("标注" in out or "不可用" in out))
    total_bad += c3.report("场景 3：不给墙厚（硬边界：墙厚不可量图）")

    # ── 场景 6：提取输出的**契约检查**
    #
    # 为什么需要：整条工作流是靠多个脚本间的**字段约定**串起来的
    # （`source` / `confidence` / `basis` / `note` / `merged_piers`）。
    # 如果哪天提取器改了字段名，`build_from_plan.rb` 会**静默读不到**，
    # 疑问清单就少问了——**而没有任何东西会报警**。
    #
    # 所以把约定变成可验证的检查：提取结果必须带上游走整条链路所需的字段。
    c6 = Check()
    all_open = [o for w in walls for o in (w.get("openings") or [])]
    c6.ok("每个洞口都有 confidence", all("confidence" in o for o in all_open),
          f"共 {len(all_open)} 个洞口")
    c6.ok("每个洞口都有 source", all("source" in o for o in all_open))
    c6.ok("每个洞口都有 note（低置信度时必须能解释原因）",
          all(o.get("note") for o in all_open))
    c6.ok("标为 low 的洞口必须带 note",
          all(o.get("note") for o in all_open if o.get("confidence") == "low"))
    c6.ok("每面墙都有 thickness（不可量，必须显式存在）",
          all("thickness" in w for w in walls))
    c6.ok("每面墙都有 height", all("height" in w for w in walls))
    meta = data.get("meta") or {}
    c6.ok("meta 里有 scale_basis（标定依据要可追溯）", bool(meta.get("scale_basis")))
    c6.ok("meta 里有 assumptions（假定必须写下来）", bool(meta.get("assumptions")))
    # 单位闸门：数据里必须能看出单位
    c6.ok("meta 声明了单位", bool(meta.get("units")), str(meta.get("units")))
    total_bad += c6.report("场景 6：提取输出的字段契约")

    # ── 场景 5：**不加 --confirm 时绝不能动模型**
    #
    # 这是"先确认后建模"这条工作政策的**行为测试**。
    # Round 30 之前 `build_from_json.py` 默认就建几何，只在末尾打印疑问清单——
    # 等于**默认绕过了确认环节**。现在默认只审查。
    #
    # 怎么测"没动模型"：先记住顶层实体数，跑一次不带 --confirm 的调用，
    # 再比对。数字变了就说明它偷偷建了。
    c5 = Check()

    def top_count() -> int | None:
        r = subprocess.run([PY, "-c",
                            "import sys; sys.path.insert(0, r'%s')\n"
                            "from sk_client import SC\n"
                            "print(SC(timeout=30).info(scope='top', limit=1)['counts']['top_level'])" % HERE],
                           cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
        try:
            return int((r.stdout or "").strip().splitlines()[-1])
        except (ValueError, IndexError):
            return None

    n0 = top_count()
    rc, out, err = sh("build_from_json.py", plan)          # 故意不加 --confirm
    n1 = top_count()
    c5.ok("不带 --confirm 时调用成功返回", rc == 0, f"退出码 {rc}")
    if n0 is not None and n1 is not None:
        c5.ok("★ 不带 --confirm 时**模型未被改动**", n0 == n1,
              f"顶层实体 {n0} → {n1}（这条是「先确认后建模」的行为测试）")
    else:
        c5.ok("★ 不带 --confirm 时模型未被改动", False, "读不到模型实体数")
    c5.ok("提示了如何继续", "--confirm" in out)

    # 而带 --confirm 时应当真的建（说明参数有效，不是被忽略）
    #
    # ⚠️ 断言怎么选：不能用"实体数变了"来判断"带 --confirm 时建了"——
    # 建的是**同一个模型**，先清空再建，数字自然回到同一个值（实测 14 → 14），
    # 于是断言失败，而其实是参数生效了。我第一版就写错了这条。
    # 改用 **--keep**（不先清空，所以会叠加到现有模型上）：
    # 真的建了 → 数字必然变大。
    if os.path.exists(plan):
        rc, out, err = sh("build_from_json.py", plan, "--confirm", "--keep", "--discard")
        n2 = top_count()
        c5.ok("带 --confirm 时确实建模了", rc == 0 and n1 is not None and n2 is not None and n2 > n1,
              f"顶层实体 {n1} → {n2}（用 --keep 叠加，真建了才会变多）")
        c5.ok("建模输出里有构件统计", "构件" in out)
    total_bad += c5.report("场景 5：先确认后建模（政策的行为测试）")

    print()
    print("=" * 66)
    print("✅ 完整工作流通过" if total_bad == 0 else f"❌ 有 {total_bad} 项未通过")
    return 0 if total_bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
