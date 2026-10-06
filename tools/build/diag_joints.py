#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐类接口量化：找出"缝"和"重叠"。

用户强调的通则：**构件之间要么严丝合缝，要么合理搭接，不能有缝。**
（原话："天花板不会漏风的，它一定是和墙严丝合缝或者盖在上面的"）

⚠️ 教训：分析必须在 **Ruby 侧**算完再回传结论。
我第一版把 86 个构件的坐标全传回来，撞上 DSH 工具层约 4000 字符的输出截断，
半截 JSON 解析失败。上一轮刚踩过同一个坑（几何校验的全量回传）。
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

PROBE = r'''
m = Sketchup.active_model
K = 25.4

def rng(container, off)
  xs = []; ys = []; zs = []
  container.grep(Sketchup::Face).each do |f|
    f.vertices.each do |v|
      p = v.position
      xs << p.x + off.x; ys << p.y + off.y; zs << p.z + off.z
    end
  end
  return nil if xs.empty?
  { x: [xs.min*K, xs.max*K], y: [ys.min*K, ys.max*K], z: [zs.min*K, zs.max*K] }
end

parts = []
m.entities.grep(Sketchup::Group).each do |g|
  r = rng(g.definition.entities, g.transformation.origin)
  parts << { name: g.name, **r } if r
  g.definition.entities.grep(Sketchup::Group).each do |s|
    o1 = g.transformation.origin; o2 = s.transformation.origin
    o = Geom::Vector3d.new(o1.x + o2.x, o1.y + o2.y, o1.z + o2.z)
    sr = rng(s.definition.entities, o)
    parts << { name: s.name, **sr } if sr
  end
end

def ov(a, b, ax) = [a[ax][1], b[ax][1]].min - [a[ax][0], b[ax][0]].max
def gp(a, b, ax)
  return b[ax][0] - a[ax][1] if a[ax][1] < b[ax][0]
  return a[ax][0] - b[ax][1] if b[ax][1] < a[ax][0]
  -ov(a, b, ax)
end

out = { issues: [], sections: {} }

# ── 1) 内墙 ↔ 外墙
inner = parts.select { |p| p[:name].include?("内墙") }
outer = parts.select { |p| p[:name].start_with?("W-") && !p[:name].include?("内墙") }
sec1 = []
inner.each do |iw|
  outer.each do |ew|
    next unless ov(iw, ew, :z) > 100
    dx = gp(iw, ew, :x); dy = gp(iw, ew, :y)
    next unless dx <= 1 && dy <= 1
    kind = (dx < -1 || dy < -1) ? "搭接" : "齐平"
    sec1 << format("%-16s ↔ %-12s X缝%7.1f Y缝%7.1f → %s", iw[:name], ew[:name], dx, dy, kind)
    out[:issues] << "#{iw[:name]} 与 #{ew[:name]} 之间有缝 X=#{dx.round(1)} Y=#{dy.round(1)}" if dx > 1 || dy > 1
  end
end
out[:sections][:inner_outer] = sec1

# ── 2) 门窗料按洞口归组，给出整体范围
join = parts.select { |p| p[:name] =~ /(框\d|上槛|下槛|玻璃|门扇)/ }
by = {}
join.each do |j|
  # 归组键必须含**墙名**：不同墙上可能有同名洞口（本模型里北墙和东墙都有"卧室窗"），
  # 只按洞口名归组会把它们合并成一组，坐标范围就荒唐了（x=800..6120）。
  # 另外洞口名要取"墙名之后、构件后缀之前"那一段——简单取第三段是错的：
  # `W-内墙-横-卧室门-框1` 的第三段是"横"（墙名的一部分）。
  seg = j[:name].split("-")
  wall = seg[0..1].join("-")          # W-南外墙 / W-内墙-横 …（前两段基本够用）
  label = seg[2..-2].join("-")
  label = seg[2] if label.empty?
  (by["#{wall}/#{label}"] ||= []) << j
end
sec2 = by.map do |key, gs|
  format("%-22s x=%7.0f..%-7.0f z=%6.0f..%-6.0f %d 块",
         key, gs.map { |g| g[:x][0] }.min, gs.map { |g| g[:x][1] }.max,
         gs.map { |g| g[:z][0] }.min, gs.map { |g| g[:z][1] }.max, gs.length)
end.sort
out[:sections][:joinery] = sec2

# ── 3) 楼梯 ↔ 楼板
st = parts.select { |p| p[:name].start_with?("ST") }.sort_by { |p| p[:name] }
fl = parts.select { |p| p[:name].start_with?("F") }
sec3 = []
if st.any?
  top = st.last
  sec3 << format("楼梯末级 %s  z=%.0f..%.0f（共 %d 级）", top[:name], top[:z][0], top[:z][1], st.length)
  fl.each do |f|
    zg = gp(top, f, :z)
    hit = ov(top, f, :x) > 1 && ov(top, f, :y) > 1
    sec3 << format("%-12s z=%.0f..%.0f  与末级 Z缝%7.1f  平面相交=%s", f[:name], f[:z][0], f[:z][1], zg, hit ? "是" : "否")
    out[:issues] << "楼梯末级与 #{f[:name]} 之间有 #{zg.round(1)}mm 竖向缝" if hit && zg > 1
  end
end
out[:sections][:stair] = sec3

# ── 4) 楼板 ↔ 外墙（应当搭接或齐平，不能有缝）
sec4 = []
fl.first(2).each do |f|
  outer.first(4).each do |ew|
    dx = gp(f, ew, :x); dy = gp(f, ew, :y)
    next unless dx <= 1 && dy <= 1
    sec4 << format("%-12s ↔ %-12s X缝%7.1f Y缝%7.1f  Z缝%7.1f", f[:name], ew[:name], dx, dy, gp(f, ew, :z))
  end
end
out[:sections][:slab_wall] = sec4

# ── 5) 非预期重叠检查
#
# 用户说过"要么直接把两面墙做重叠，要么好好算好，严丝合缝"——所以**合理的搭接是允许的**。
# 但两个**主体构件**（楼板/夹层/楼梯/立面轮廓之间）互相穿模就是错的。
# 这里检查：两个主体在三个轴上都相交超过 10mm → 报告体积重叠。
def vol_overlap(a, b)
  ox = ov(a, b, :x); oy = ov(a, b, :y); oz = ov(a, b, :z)
  return nil unless ox > 10 && oy > 10 && oz > 10
  { ox: ox, oy: oy, oz: oz }
end

# 主体 = 楼板/夹层/楼梯级/立面轮廓/顶板
main = parts.select { |p| p[:name] =~ /^(F\d|ST|E-|ROOF)/ }
sec5 = []
# 已知的合理支座关系（不算缺陷）：
#   · 楼梯各级 ↔ 楼板：楼梯落在楼板上，是支座搭接，**合理**
#   · 女儿墙 ↔ 顶板：女儿墙坐在顶板上，若 base_z 用对则只该有微量搭接
#   · 家具 ↔ 家具：椅子推进桌下是有意搭接（真实使用状态），**合理**
def bearing_ok?(a, b)
  sa = a[:name]; sb = b[:name]
  return true if sa.start_with?("ST") && sb.start_with?("F")
  return true if sb.start_with?("ST") && sa.start_with?("F")
  return true if sa.start_with?("ST") && sb.start_with?("ST")
  return true if (sa.start_with?("E-") && sb.start_with?("ROOF")) ||
                 (sb.start_with?("E-") && sa.start_with?("ROOF"))
  # 家具之间的搭接（椅子推进桌下）
  return true if a[:furn] && b[:furn]
  false
end

main.combination(2).each do |a, b|
  v = vol_overlap(a, b)
  next unless v
  if bearing_ok?(a, b)
    sec5 << format("%-16s ∩ %-16s  重叠 X%.0f Y%.0f Z%.0f  （支座搭接，合理）",
                   a[:name], b[:name], v[:ox], v[:oy], v[:oz])
    next
  end
  # 转角接头 vs 真穿模：
  #   两个**竖向**构件（墙/立面）在平面内相交、且沿全长重叠 —— 那是 L 形接头，
  #   垂直构件本来就靠互相穿透来接头。特征是"平面小重叠 + Z 向几乎全高重叠"。
  #   真穿模则是三个方向都有可观的重叠（比如夹层撞顶板 2500×3700×120）。
  az = a[:z][1] - a[:z][0]
  bz = b[:z][1] - b[:z][0]
  z_full = v[:oz] > [az, bz].min * 0.9
  if z_full && v[:ox] < 400 && v[:oy] < 400
    sec5 << format("%-16s ∩ %-16s  重叠 X%.0f Y%.0f Z%.0f  （转角接头，垂直构件互相穿透，合理）",
                   a[:name], b[:name], v[:ox], v[:oy], v[:oz])
    next
  end
  sec5 << format("%-16s ∩ %-16s  重叠 X%.0f Y%.0f Z%.0f  ← ⚠️ 非预期",
                 a[:name], b[:name], v[:ox], v[:oy], v[:oz])
  out[:issues] << "#{a[:name]} 与 #{b[:name]} 体积重叠 X#{v[:ox].round}Y#{v[:oy].round}Z#{v[:oz].round}"
end
out[:sections][:overlaps] = sec5

# ── 6) 楼梯不该挡门（数据层面的专业错误）
#
# 实测踩过：楼梯起点设在 x=200，而入户门洞在 x=1200..2200 —— 出门就是踏步。
# 这类错误代码不会报，只有懂行的人一眼看出。所以做成检查。
# 判据：楼梯的**平面足迹**（只看 x/y，不看 z——楼梯从地面起，必然与门同高）
#       与任一门的洞口平面范围相交超过 100mm，就报。
doors = parts.select { |p| p[:name] =~ /门-框1$/ }
stairs_all = parts.select { |p| p[:name].start_with?("ST") }
sec6 = []
stairs_all.each do |st|
  doors.each do |d|
    # 由门框1推门洞起点；门洞宽度取同组框1与框2的跨度
    grp = parts.select { |p| p[:name].sub(/-框1$/, "") == d[:name].sub(/-框1$/, "") }
    next if grp.empty?
    x0 = grp.map { |g| g[:x][0] }.min; x1 = grp.map { |g| g[:x][1] }.max
    y0 = grp.map { |g| g[:y][0] }.min; y1 = grp.map { |g| g[:y][1] }.max
    ox = [x1, st[:x][1]].min - [x0, st[:x][0]].max
    oy = [y1, st[:y][1]].min - [y0, st[:y][0]].max
    next unless ox > 100 && oy > 100
    sec6 << format("%-10s 的平面足迹 x=%.0f..%.0f y=%.0f..%.0f 与 %s 的洞口 x=%.0f..%.0f 重叠 %.0fmm",
                   st[:name], st[:x][0], st[:x][1], st[:y][0], st[:y][1],
                   d[:name].sub(/-框1$/, ""), x0, x1, ox)
    out[:issues] << "#{st[:name]} 挡住 #{d[:name].sub(/-框1$/, '')}（平面重叠 #{ox.round}mm）——楼梯不该挡门"
  end
end
out[:sections][:stair_door] = sec6

out[:part_count] = parts.length
puts JSON.generate(out)
'''


def main() -> int:
    c = SC(timeout=90)
    try:
        r = c.ruby(PROBE, undo=False, timeout=90)
    except BridgeError as e:
        print(f"❌ [{e.code}] {str(e)[:400]}")
        return 1
    out = str(r.get("output", "")).strip()
    idx = out.rfind("{")
    blob = None
    while idx != -1 and blob is None:
        try:
            blob = json.loads(out[idx:])
        except json.JSONDecodeError:
            idx = out.rfind("{", 0, idx)
    if blob is None:
        print("⚠️ 没解析到结果：" + out[:500])
        return 1

    sec = blob.get("sections") or {}
    print(f"构件总数 {blob.get('part_count')}")
    print()
    print("== 1) 内墙 ↔ 外墙接头")
    for line in sec.get("inner_outer") or ["   （无相接的内外墙）"]:
        print("   " + line)
    print()
    print("== 2) 门窗料按洞口归组")
    for line in sec.get("joinery") or ["   （无门窗料）"]:
        print("   " + line)
    print()
    print("== 3) 楼梯 ↔ 楼板")
    for line in sec.get("stair") or ["   （无楼梯）"]:
        print("   " + line)
    print()
    print("== 4) 楼板 ↔ 外墙")
    for line in sec.get("slab_wall") or ["   （无）"]:
        print("   " + line)
    print()
    print("== 5) 主体构件之间的非预期重叠（墙体转角搭接不在此列，那是设计）")
    for line in sec.get("overlaps") or ["   （无重叠）"]:
        print("   " + line)
    print()
    print("== 6) 楼梯是否挡门（专业一致性）")
    for line in sec.get("stair_door") or ["   ✅ 楼梯足迹与所有门洞无重叠"]:
        print("   " + line)
    print()
    print("=" * 66)
    issues = blob.get("issues") or []
    if issues:
        print(f"发现 {len(issues)} 处缝：")
        for s in issues:
            print(f"  ⚠️ {s}")
    else:
        print("✅ 以上四类接口未发现缝")
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
