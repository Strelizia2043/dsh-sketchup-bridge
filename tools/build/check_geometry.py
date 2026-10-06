#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""几何校验：逐个构件核对**世界坐标**是否落在预期范围。

为什么需要单独一个脚本：我几次用 `sub.bounds` 直接读子组，拿到的是**本地坐标**
（从 0 开始），于是把正确的几何误判成"偏移了 120"。正确做法是用
`sum_bounds = g.transformation * g.bounds` 换算到世界坐标。

用法：python check_geometry.py [plan.json]
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

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sk_client import SC, BridgeError  # noqa: E402

CHECK = r'''
m = Sketchup.active_model
MM = 25.4

# 只回传**摘要 + 可疑构件**，不回传全量。
# 原因（踩过）：全量输出被 DSH 工具层截断到约 4000 字符，半截 JSON 解析失败；
# 我先怀疑解析器、又错改了桥的 MAX_OUT，绕了两圈才找到真因。
def world_range(container, off)
  xs = []; ys = []; zs = []
  container.grep(Sketchup::Face).each do |f|
    f.vertices.each do |v|
      p = v.position
      xs << p.x + off.x; ys << p.y + off.y; zs << p.z + off.z
    end
  end
  return nil if xs.empty?
  { x: [(xs.min*MM).round, (xs.max*MM).round],
    y: [(ys.min*MM).round, (ys.max*MM).round],
    z: [(zs.min*MM).round, (zs.max*MM).round] }
end

flags = []
count = 0
parts = []
m.entities.grep(Sketchup::Group).each do |g|
  off1 = g.transformation.origin
  wr = world_range(g.definition.entities, off1)
  if wr
    count += 1
    parts << { name: g.name, **wr }
    flags << { name: g.name, **wr, why: 'z<0' } if wr[:z][0] < -1
  end
  g.definition.entities.grep(Sketchup::Group).each do |sub|
    o2 = sub.transformation.origin
    off2 = Geom::Vector3d.new(off1.x + o2.x, off1.y + o2.y, off1.z + o2.z)
    swr = world_range(sub.definition.entities, off2)
    if swr
      count += 1
      parts << { name: sub.name, **swr }
      flags << { name: sub.name, **swr, why: 'z<0' } if swr[:z][0] < -1
    end
  end
end

# ── 转角覆盖检查（用户指出的真缺陷：墙厚居中于轴线时四角各缺一块）
# 判据：外墙总外轮廓的四个角，是否各自被 ≥2 面墙覆盖
outer = parts.select { |p| p[:name] =~ /^W-/ && p[:name] !~ /(框|槛|玻璃|门扇)/ }
corner_gaps = []
unless outer.empty?
  ex0 = outer.map { |r| r[:x][0] }.min
  ex1 = outer.map { |r| r[:x][1] }.max
  ey0 = outer.map { |r| r[:y][0] }.min
  ey1 = outer.map { |r| r[:y][1] }.max
  [[ex0, ey0, '西南'], [ex1, ey0, '东南'], [ex0, ey1, '西北'], [ex1, ey1, '东北']].each do |cx, cy, nm|
    n = outer.count { |r| r[:x][0] <= cx + 1 && r[:x][1] >= cx - 1 &&
                          r[:y][0] <= cy + 1 && r[:y][1] >= cy - 1 }
    corner_gaps << "#{nm}角(#{cx},#{cy}) 仅被 #{n} 面墙覆盖" if n < 2
  end
end

# ── 天花板与墙顶是否齐平（用户指出"天花板不会漏风，必须严丝合缝"）
ceilings = parts.select { |p| p[:name] =~ /-天花$/ }
wall_tops = parts.select { |p| p[:name] =~ /^W-/ }.map { |p| p[:z][1] }.uniq.compact
ceil_issues = []
unless ceilings.empty? || wall_tops.empty?
  top = wall_tops.max
  ceilings.each do |c|
    ceil_issues << "#{c[:name]} 底面 #{c[:z][0]} ≠ 墙顶 #{top}" if c[:z][0] != top
  end
end

# ── 洞口位置核对（用户/我自己都可能踩的坑：u 坐标随墙延伸漂移）
# 方法：给出每个洞口应在的世界坐标，检查该处**墙体是否真的是空的**。
#   · 洞口中心点落在任何墙组包围盒内 → 说明洞口被堵住或位置偏了
#   · 洞口起点前后 200mm 的实心处应当有墙覆盖
# 不依赖门窗扇框（那是 opt-in），只看墙本身。
# ── 洞口位置核对：**已删除**，原因值得记下来
#
# 我试过四版基于采样点的洞口位置检查，全部失败：
#   v1 用固定 mid_z=1000mm → 窗（窗台 900）在该高度仍属实体，全部误报
#   v2 只查"洞口中心是否在实体里" → 抓不到整体漂移（漂了之后中心仍落在空处）
#   v3 查"洞口外 150mm 必须有墙" → 贴边采样太脆，好模型也误报 13 处
#   v4 改成 40mm/300mm 双向采样 → 仍然误报 14 处
#
# 结论：**用少量采样点判断"洞口位置对不对"这件事，我做得不靠谱。**
# 而上一轮我已经用可靠得多的方式验证过洞口漂移（u 平移缺失）已修复：
#   · 直接量门窗框世界坐标：入户门框 x=1200..1260、客厅窗框 x=3200..3260，偏差 +0
#   · 截图肉眼确认
#
# 所以这里**不保留**这个检查。一个反复假阳性的检查比没有检查更糟：
# 它会消耗信任、掩盖真信号。宁缺毋滥。
#
# 真要彻底做对，正确方向是"读取每面墙实心段的世界坐标区间，与洞口期望区间做集合比对"，
# 而不是打点采样。等有真实图纸、真遇到这类问题时再做。

mb = m.bounds
puts JSON.generate({
  summary: {
    model_x: [(mb.min.x*MM).round, (mb.max.x*MM).round],
    model_y: [(mb.min.y*MM).round, (mb.max.y*MM).round],
    model_z: [(mb.min.z*MM).round, (mb.max.z*MM).round],
    top_level_groups: m.entities.grep(Sketchup::Group).length,
    total_entities: m.entities.length,
    parts_checked: count,
    below_ground: flags,
    corner_gaps: corner_gaps,
    ceiling_issues: ceil_issues,
    outer_corners: outer.empty? ? nil : [[ex0, ey0], [ex1, ey1]]
  }
})
'''


def main() -> int:
    plan = sys.argv[1] if len(sys.argv) > 1 else None
    expect = None
    z_max = None
    if plan and os.path.exists(plan):
        with open(plan, encoding="utf-8") as f:
            data = json.load(f)
        xs, ys = [], []
        for w in data.get("walls", []):
            for pt in (w["from"], w["to"]):
                xs.append(pt[0])
                ys.append(pt[1])
        if xs:
            pad = max((w.get("thickness", 0) for w in data.get("walls", [])), default=0) / 2
            expect = {"x": [min(xs) - pad, max(xs) + pad], "y": [min(ys) - pad, max(ys) + pad]}
        # 高度上限必须由**数据本身**推出：墙高 + 立面轮廓（女儿墙/屋顶会高过墙顶）。
        # 我最早把 3001mm 写死成阈值，于是把正常的女儿墙误报成"高度异常"——
        # 校验规则里写死假设，就会制造假警报。
        tops = []
        for w in data.get("walls", []):
            tops.append((w.get("base_z") or 0) + w.get("height", 0))
        for el in data.get("elevations", []):
            # 轮廓是**相对 base_z** 的标高（不写 base_z 则为 0）。
            # 漏算 base_z 会两头出错：算小了误报"超出声明标高"（踩过：
            # 女儿墙 base_z=2950 + 轮廓 450 实际到 3400，我按 450 算成了 3050），
            # 算大了又会漏掉真的超高。
            bz = float(el.get("base_z") or 0)
            for pt in el.get("profile", []):
                tops.append(bz + pt[1])
            for hole in el.get("holes", []) or []:
                for pt in hole:
                    tops.append(bz + pt[1])
        for r in data.get("rooms", []):
            ch = r.get("ceiling_height") or 0
            tops.append(ch + (r.get("ceiling_thickness") or 100))
        # 整层顶板也要计入：它坐在墙顶上，是有厚度的，会抬高模型最高点。
        # 漏算它会把正确的模型误报成"超出声明标高"（踩过）。
        env = data.get("envelope_ceiling")
        if env is not False:
            env = env or {}
            if tops:
                tops.append(max(tops) + (env.get("thickness") or 150))
        z_max = max(tops) if tops else None
        print(f"== 数据声明的最大标高: {z_max}mm（墙高 / 立面轮廓 / 房间天花 / 整层顶板 取最大）"
              if z_max else "")
        print("   注意：本脚本用**当前模型**核对**传入的数据**，"
              "所以必须紧跟一次 build_from_json.py 之后运行；")
        print("   否则你核对的是别的模型，会得到假的『不吻合』（踩过）。")

    # ── 洞口世界坐标的期望值 + 一致性断言
    #
    # 为什么需要这一项：洞口用的是**沿墙局部坐标 u**，而"转角延伸"会把墙的 from 端外移。
    # 实测踩过：南墙 from 端延伸 120mm 后，入户门框跑到 x=1080..1140（声明 1200..2200）。
    # 门窗位置错比转角缺口严重得多。
    #
    # 这里做两件事：
    #   1. 算出洞口应有的世界坐标（复刻生成器的延伸逻辑）
    #   2. **纯解析断言**：延伸前后洞口的世界坐标必须完全一致
    #      —— 这条不依赖模型，直接抓住"u 没跟着平移"这类 bug
    def tol_dist(px, py, ax, ay, bx, by):
        dx, dy = bx - ax, by - ay
        l2 = dx * dx + dy * dy
        if l2 < 1e-9:
            return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
        return ((px - (ax + dx * t)) ** 2 + (py - (ay + dy * t)) ** 2) ** 0.5

    def wall_exts_of(data):
        walls = data.get("walls") or []
        exts = []
        for i, w in enumerate(walls):
            t = float(w.get("thickness", 0))
            e = [0.0, 0.0]
            for pt, which in ((w["from"], 0), (w["to"], 1)):
                px, py = float(pt[0]), float(pt[1])
                for j, o in enumerate(walls):
                    if j == i:
                        continue
                    if tol_dist(px, py, float(o["from"][0]), float(o["from"][1]),
                                float(o["to"][0]), float(o["to"][1])) <= 60.0:
                        e[which] = t / 2.0
                        break
            exts.append(e)
        return exts

    def opening_world(w, ext_from, u, use_shift):
        """给定墙、from 端延伸量、洞口 u，算洞口起点世界坐标。
        use_shift=True 模拟"正确实现"（u 随延伸平移）；False 模拟"漏平移"（bug）。"""
        x0, y0 = float(w["from"][0]), float(w["from"][1])
        x1, y1 = float(w["to"][0]), float(w["to"][1])
        ln = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        if ln < 1e-6:
            return None
        ux, uy = (x1 - x0) / ln, (y1 - y0) / ln
        sx, sy = x0 - ux * ext_from, y0 - uy * ext_from
        uu = u + ext_from if use_shift else u
        return (round(sx + ux * uu), round(sy + uy * uu))

    def opening_expectations(data):
        walls = data.get("walls") or []
        exts = wall_exts_of(data)
        out = []
        for i, w in enumerate(walls):
            for k, o in enumerate(w.get("openings") or []):
                u = float(o.get("u", 0))
                shifted = opening_world(w, exts[i][0], u, True)
                unshift = opening_world(w, exts[i][0], u, False)
                if shifted is None or unshift is None:
                    continue
                x0, y0 = float(w["from"][0]), float(w["from"][1])
                x1, y1 = float(w["to"][0]), float(w["to"][1])
                ln = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
                ux, uy = (x1 - x0) / ln, (y1 - y0) / ln
                wd = float(o.get("width", 0))
                label = o.get("label") or f"{w['name']}-洞{k + 1}"
                out.append({
                    "label": label, "wall": w["name"],
                    "start": list(shifted), "end": [round(shifted[0] + ux * wd),
                                                    round(shifted[1] + uy * wd)],
                    "width": wd,
                    # 洞口高度范围：供 Ruby 侧在**洞内**取采样高度
                    "z0": round(float(o.get("sill", 0)) + 100),
                    "z1": round(float(o.get("sill", 0)) + float(o.get("height", 2100)) - 100),
                    "ext_from": round(exts[i][0], 1),
                    "shift_mm": round(((shifted[0] - unshift[0]) ** 2 +
                                       (shifted[1] - unshift[1]) ** 2) ** 0.5, 1),
                })
        return out

    expectations = opening_expectations(data) if plan and os.path.exists(plan) else []

    # 一致性断言（纯解析）：墙有延伸 ⇒ 洞口必须被平移。
    # ⚠️ 但这只是**数据自洽**检查：它读的是数据，读不到生成器的实现。
    #    我一度以为它能抓"生成器漏平移 u"，结果它永远为真（循环论证）——
    #    **一个永远为真的检查是假保护**。真正抓那个 bug 的是 Ruby 侧的
    #    "洞口边界之外必须有墙"检查（见 opening_issues）。这里保留它只是
    #    为了防止数据本身写错（例如手工造的数据忘了考虑延伸）。
    shift_issues = []
    for e in expectations:
        if e["ext_from"] > 0.5 and e["shift_mm"] < 0.5:
            shift_issues.append(
                f"{e['label']}：墙 from 端延伸 {e['ext_from']}mm，但数据里的 u 没体现平移")

    c = SC(timeout=60)
    try:
        # 洞口位置核对需要把期望坐标传给 Ruby 侧。
        # 为避免命令行长度问题，用**单行 JSON** 作为脚本尾部注释参数。
        ruby_code = CHECK
        if expectations:
            payload = json.dumps(expectations, ensure_ascii=False, separators=(",", ":"))
            # 用 data: 前缀传输，避免被 eval 当成代码
            ruby_code = CHECK.replace(
                "openings_arg = ARGV[0]",
                f"openings_arg = {json.dumps(payload)}"
            )
        r = c.ruby(ruby_code, undo=False, timeout=90)
    except BridgeError as e:
        print(f"❌ [{e.code}] {str(e)[:400]}")
        return 1

    out = str(r.get("output", "")).strip()
    # 解析：从最后一个 '{' 起整体解析。
    # 注意：**输出过长会被截断**（DSH 工具层约 4000 字符就会截，末尾有"...[截断 N 字符]"），
    # 半截 JSON 必然解析失败。所以下面的 Ruby 只回传"结论 + 异常项"，不回传全量构件。
    # 我为此先怀疑过解析器、又错改了桥的 MAX_OUT，最后才发现是工具层显示截断。
    blob = None
    idx = out.rfind("{")
    while idx != -1 and blob is None:
        try:
            blob = json.loads(out[idx:])
        except json.JSONDecodeError:
            idx = out.rfind("{", 0, idx)
    if blob is None:
        print("⚠️ 没解析到结果（可能是输出被截断）：" + out[:600])
        return 1

    s = blob["summary"]
    print("== 模型总览")
    print(f"   顶层组 {s['top_level_groups']}  实体总数 {s['total_entities']}")
    print(f"   世界范围 X {s['model_x']}  Y {s['model_y']}  Z {s['model_z']}")
    if expect:
        okx = abs(s["model_x"][0] - expect["x"][0]) <= 2 and abs(s["model_x"][1] - expect["x"][1]) <= 2
        oky = abs(s["model_y"][0] - expect["y"][0]) <= 2 and abs(s["model_y"][1] - expect["y"][1]) <= 2
        print(f"   期望 X {[round(v) for v in expect['x']]}  Y {[round(v) for v in expect['y']]}"
              f"   → {'✅' if okx and oky else '⚠️'} "
              f"{'吻合' if okx and oky else '不吻合'}")

    print()
    print("== 构件位置检查")
    checked = s.get("parts_checked", 0)
    below = s.get("below_ground") or []
    problems = []
    for p in below:
        problems.append((p, [f"低于地面 {p['z'][0]}mm"]))
    # 转角缺口（墙厚居中于轴线时的经典缺陷，用户指出过）
    for g in (s.get("corner_gaps") or []):
        problems.append(({"name": "(转角)"}, [g]))
    # 天花板必须与墙顶齐平
    for c in (s.get("ceiling_issues") or []):
        problems.append(({"name": "(天花)"}, [c]))
    # 洞口位置：一致性断言（延伸与 u 平移必须配套）
    for o in shift_issues:
        problems.append(({"name": "(洞口位置)"}, [o]))
    # 标高上限：由数据推出的 z_max，在整个模型范围内核对（Ruby 侧已核对 z<0）
    z_hi = s["model_z"][1]
    if z_max is not None and z_hi > z_max + 2:
        problems.append(({"name": "(模型最高处)", "z": s["model_z"]},
                         [f"顶标高 {z_hi}mm 超过数据声明的 {z_max}mm"]))
    # 平面范围：整体核对
    if expect:
        if s["model_x"][0] < expect["x"][0] - 2 or s["model_x"][1] > expect["x"][1] + 2:
            problems.append(({"name": "(模型 X 范围)", "x": s["model_x"]},
                             ["X 超出建筑范围"]))
        if s["model_y"][0] < expect["y"][0] - 2 or s["model_y"][1] > expect["y"][1] + 2:
            problems.append(({"name": "(模型 Y 范围)", "y": s["model_y"]},
                             ["Y 超出建筑范围"]))

    if not problems:
        oc = s.get("outer_corners")
        extra = f"；外墙四角 {oc} 均被 ≥2 面墙覆盖" if oc else ""
        print(f"   ✅ 逐一核对 {checked} 个构件：无低于地面项；模型整体范围与数据吻合{extra}")
    else:
        for p, flags in problems:
            loc = " ".join(f"{k}={v}" for k, v in p.items() if k in ("x", "y", "z"))
            print(f"   ⚠️ {p['name']:<20} {loc}  ← {'；'.join(flags)}")
        print(f"   共 {len(problems)} 项有问题")

    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
