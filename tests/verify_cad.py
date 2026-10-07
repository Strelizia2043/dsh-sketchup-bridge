#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CAD 直读路径的回归测试 —— 把"真实图纸暴露出来的 bug"钉死。

为什么单独一条测试：
前 33 轮我只有"合成图"这条测试线。那张合成图**内外墙厚度接近**、
**墙厚都是整数**、**尺寸都在同一个量级**，于是三个真缺陷一直藏着：

  1. 顶板外扩用"最厚墙的半厚"统一加到四边
     → 外墙 50 / 内墙 100 时，四周各多 25，顶板 5000 变 5100
  2. 墙端延伸用"自身半厚"
     → 那条注释"这样外表面刚好交于角点"**只在两墙等厚时成立**；
       内墙 100 接外墙 50 时会伸出去 50
  3. ACI 0/256 是 BYBLOCK/BYLAYER 哨兵值，不是颜色
     → 当成黑色报出去，报告里出现 93 个"黑实体"（其实是黄色标注）

**这三个都是"真实图纸才暴露、合成图永远测不出"的。**
把它们变成断言，是为了让以后任何改动都不能悄悄改回去。
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


from dsh_paths import tool as _tool, tool_rel as _tool_rel, ROOT
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

# 店面测试数据：外墙 50 / 内墙 100（**内墙比外墙厚**，正是触发 bug 2 的配置）
SHOP = os.path.join(ROOT, "examples", "cad_map_example.json")
# 真值（全部来自 Drawing1.dxf 的实体坐标，已在文档中记录）
SHOP_TRUTH = {
    "envelope": (0.0, 0.0, 5000.0, 5000.0),
    "slab": (5000.0, 5000.0),
    "outer_t": 50.0,
    "inner_t": 100.0,
    "openings": {
        "西-门": ("y", 3050.00, 4531.53),
        "东-落地窗": ("y", 1704.83, 4259.65),
        "南-门": ("x", 1009.24, 2490.77),
    },
}


TOUCHING_MODEL = "--touching-model" in sys.argv


def sh(*args, timeout=900):
    # 第一个参数若是裸脚本名，解析成相对根目录的路径（脚本已搬到 tools/*）
    argv = list(args)
    if argv and isinstance(argv[0], str) and argv[0].endswith('.py'):
        full = _tool(argv[0])
        if full:
            argv[0] = os.path.relpath(full, ROOT).replace('\\', '/')
    r = subprocess.run([PY, *argv], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return r.returncode, r.stdout or "", r.stderr or ""


def ruby(code: str):
    """在运行中的 SketchUp 里执行 Ruby，返回 stdout。"""
    src = ("import sys; sys.path.insert(0, r'%s')\n"
           "from sk_client import SC\n"
           "print(SC(timeout=180).ruby(%r, undo=False).get('output',''))" % (ROOT, code))
    r = subprocess.run([PY, "-c", src], cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=600)
    return (r.stdout or "").strip()


class Check:
    def __init__(self):
        self.items = []

    def ok(self, name, cond, detail=""):
        self.items.append((name, bool(cond), detail))

    def report(self, title):
        print(f"\n== {title}")
        bad = 0
        for n, good, d in self.items:
            print(f"   {'✅' if good else '❌'} {n}" + (f"   {d}" if d else ""))
            if not good:
                bad += 1
        return bad


def main() -> int:
    total = 0

    # ── 1. 配置驱动的 plan 生成：洞口位置必须与 DXF 真值一致
    c1 = Check()
    out = os.path.join(ROOT, "cad", "_reg_plan.json")
    rc, o, e = sh("cad_to_plan.py", SHOP, "--out", out)
    c1.ok("cad_to_plan.py 能生成 plan", rc == 0 and os.path.exists(out),
          f"退出码 {rc}")
    if os.path.exists(out):
        d = json.load(open(out, encoding="utf-8"))
        got = {}
        for w in d["walls"]:
            f = w["from"]
            horiz = abs(w["to"][0] - f[0]) > abs(w["to"][1] - f[1])
            for op in (w.get("openings") or []):
                base = f[0] if horiz else f[1]
                got[op["label"]] = (("x" if horiz else "y"),
                                    base + op["u"], base + op["u"] + op["width"])
        for lab, (ax, t0, t1) in SHOP_TRUTH["openings"].items():
            g = got.get(lab)
            good = g and g[0] == ax and abs(g[1] - t0) < 0.02 and abs(g[2] - t1) < 0.02
            c1.ok(f"洞口「{lab}」位置与 DXF 真值一致", good,
                  f"实测 {g}，真值 ({ax}, {t0}, {t1})" if g else "没提取到")
        # 洞口的 u 必须从**当前**中线基准量起（防"坑 2：u 漂移"复发）
        for w in d["walls"]:
            if not (w.get("openings")):
                continue
            f = w["from"]
            horiz = abs(w["to"][0] - f[0]) > abs(w["to"][1] - f[1])
            base = f[0] if horiz else f[1]
            env_lo = SHOP_TRUTH["envelope"][0 if horiz else 1]
            c1.ok(f"{w['name']} 的 from 端已按中线约定内缩",
                  abs(base - (env_lo + w["thickness"] / 2)) < 0.02,
                  f"from={'x' if horiz else 'y'} {base}，应为 {env_lo + w['thickness'] / 2}")
    total += c1.report("1. 洞口定位（防「u 随墙端漂移」复发）")

    # ── 2. 顶板尺寸：必须等于建筑外轮廓，不能是"最厚墙"外扩的结果
    c2 = Check()
    if TOUCHING_MODEL:
        # ⚠️ 先把文档清空再建。
        #
        # `build_from_json.py` 有一条**刻意的安全门**：文档里已有东西时
        # 拒绝清空（退出码 3），除非显式加 `--discard`。这是防误删用户模型。
        # 但本测试第 1 步自己就建过一次模型 → 文档不空了 →
        # 第二次调用被拦 → "能建出模型"**假失败**。
        #
        # 这里不改成 `--discard`（那等于测试自己绕过安全门，万一它作用在
        # 用户真在意的文档上就真删了）。改成**测试自己负责清场**：
        # 反正加了 --touching-model 就代表"当前文档可以被动"。
        ruby("Sketchup.active_model.entities.clear!")
        rc, o, e = sh("build_from_json.py", out, "--confirm")
        c2.ok("能建出模型", rc == 0 and "构件" in o,
              f"退出码 {rc}" + (f"，{e.strip()[:110]}" if rc else ""))
    else:
        print("\n   \u23ed  跳过建模与几何检查（未加 --touching-model）："
              "这几步会重建当前模型")
        rc, o = 1, ""
    if rc == 0:
        # ⚠️ 排除"水平大板"来算建筑外轮廓：顶板/屋顶/房檐都会**出挑**，
        # 算进去的话轮廓会变大，楼梯之类就被误判成越界。
        #
        # 判据别再用"名字含顶板" —— 屋顶已按分组契约改名为 `RF-屋顶`，
        # 不再含"顶板"两字，于是这个排除失效（实测：楼梯 4 块被误报越界）。
        # 现在按**前缀**排除，和 DshParts::CATEGORIES 的命名对齐。
        g = ruby('''
m = Sketchup.active_model
xs=[]; ys=[]
SLAB = %w[RF- EV- CE- MZ- FL-]
m.entities.grep(Sketchup::Group).each do |gr|
  next if SLAB.any? { |p| gr.name.to_s.start_with?(p) }
  b = gr.bounds
  xs << b.min.x*25.4; xs << b.max.x*25.4
  ys << b.min.y*25.4; ys << b.max.y*25.4
end
slab = m.entities.grep(Sketchup::Group).find { |x| x.name.to_s.start_with?("RF-") }
sb = slab.bounds
puts "BODY %.2f %.2f %.2f %.2f" % [xs.min, xs.max, ys.min, ys.max]
puts "SLAB %.2f %.2f %.2f %.2f" % [sb.min.x*25.4, sb.max.x*25.4, sb.min.y*25.4, sb.max.y*25.4]
''')
        vals = {}
        for line in g.splitlines():
            p = line.split()
            if len(p) == 5 and p[0] in ("BODY", "SLAB"):
                vals[p[0]] = [float(v) for v in p[1:]]
        x0, y0, x1, y1 = SHOP_TRUTH["envelope"]
        if "BODY" in vals:
            b = vals["BODY"]
            c2.ok("墙+地板的整体范围 = 外轮廓",
                  abs(b[0] - x0) < 0.5 and abs(b[1] - x1) < 0.5 and
                  abs(b[2] - y0) < 0.5 and abs(b[3] - y1) < 0.5,
                  f"实测 X {b[0]:.1f}..{b[1]:.1f} Y {b[2]:.1f}..{b[3]:.1f}"
                  f"，应为 X {x0}..{x1} Y {y0}..{y1}")
        else:
            c2.ok("墙+地板的整体范围 = 外轮廓", False, "没读到")
        if "SLAB" in vals:
            s = vals["SLAB"]
            c2.ok("★ 顶板尺寸 = 外轮廓（防「最厚墙外扩」复发）",
                  abs(s[0] - x0) < 0.5 and abs(s[1] - x1) < 0.5 and
                  abs(s[2] - y0) < 0.5 and abs(s[3] - y1) < 0.5,
                  f"实测 X {s[0]:.1f}..{s[1]:.1f} Y {s[2]:.1f}..{s[3]:.1f}"
                  f"，应为 X {x0}..{x1} Y {y0}..{y1}")
        else:
            c2.ok("★ 顶板尺寸 = 外轮廓", False, "没读到")
    total += c2.report("2. 整层顶板（防「用最厚墙外扩」复发）")

    # ── 3. 墙端延伸：内墙不许伸出外墙外皮
    #
    # ⚠️ 这一步**必须在 TOUCHING_MODEL 里**：它量的是当前模型里的墙，
    # 如果跳过建模却仍跑它，读到的就是**上一次遗留的模型**——
    # 实测报出"越界：F1-楼板 X 0..6000"（那是合成住宅，不是被测对象）。
    # **检查错对象比不检查更糟**：它给出的是假失败。
    c3 = Check()
    if TOUCHING_MODEL and os.path.exists(out):
        g = ruby('''
m = Sketchup.active_model
m.entities.grep(Sketchup::Group).each do |gr|
  next if gr.name.to_s.include?("顶板") || gr.name.to_s.include?("地板")
  b = gr.bounds
  puts "PART %s %.2f %.2f %.2f %.2f" % [gr.name, b.min.x*25.4, b.max.x*25.4,
                                        b.min.y*25.4, b.max.y*25.4]
end
''')
        x0, y0, x1, y1 = SHOP_TRUTH["envelope"]
        over = []
        for line in g.splitlines():
            p = line.split()
            if len(p) == 6 and p[0] == "PART":
                nm = p[1]
                bx0, bx1, by0, by1 = (float(v) for v in p[2:])
                if bx0 < x0 - 0.5 or bx1 > x1 + 0.5 or by0 < y0 - 0.5 or by1 > y1 + 0.5:
                    over.append(f"{nm}(X {bx0:.1f}..{bx1:.1f} Y {by0:.1f}..{by1:.1f})")
        c3.ok("★ 没有任何墙伸出建筑外轮廓", not over,
              "越界的：" + "; ".join(over[:4]) if over else f"共检查到位")
        # 额外：内墙（厚 100）不得穿到外墙（厚 50）外面
        g2 = ruby('''
m = Sketchup.active_model
m.entities.grep(Sketchup::Group).each do |gr|
  next unless gr.name.to_s.include?("纵隔墙")
  b = gr.bounds
  puts "INNER %.2f %.2f" % [b.min.y*25.4, b.max.y*25.4]
end
''')
        for line in g2.splitlines():
            p = line.split()
            if len(p) == 3 and p[0] == "INNER":
                iy0, iy1 = float(p[1]), float(p[2])
                c3.ok("内墙与外墙内皮齐平（不穿出去）",
                      iy0 >= y0 - 0.5 and iy1 <= y1 + 0.5,
                      f"纵隔墙 Y {iy0:.1f}..{iy1:.1f}，外轮廓 Y {y0}..{y1}")
    total += c3.report("3. 墙端延伸（防「自身半厚」复发）")

    # ── 4. 颜色解析：ACI 0/256 必须回落到图层颜色
    c4 = Check()
    sys.path.insert(0, ROOT)
    import dxf_import as DI  # noqa: E402
    layers = {"L1": 70, "L2": 50}
    c4.ok("ACI 0（BYBLOCK）回落到图层颜色",
          DI.aci_of({"color": 0, "layer": "L1"}, layers) == 70)
    c4.ok("ACI 256（BYLAYER）回落到图层颜色",
          DI.aci_of({"color": 256, "layer": "L2"}, layers) == 50)
    c4.ok("color=None 回落到图层颜色",
          DI.aci_of({"color": None, "layer": "L2"}, layers) == 50)
    c4.ok("显式颜色不被覆盖",
          DI.aci_of({"color": 3, "layer": "L1"}, layers) == 3)
    total += c4.report("4. 颜色解析（防「把哨兵值当颜色」复发）")

    print()
    print("=" * 66)
    print("✅ CAD 直读回归全部通过" if total == 0 else f"❌ 有 {total} 项未通过")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
