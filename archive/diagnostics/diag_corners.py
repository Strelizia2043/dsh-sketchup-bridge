#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断外墙转角与天花板配合——针对用户指出的两个问题。

问题 1：外墙不是直角、缺了一块
    怀疑：墙厚**居中于轴线**时，两面成直角的外墙会在转角留下一个 t/2 × t/2 的空洞，
          同时又在 t/2 × t 的范围重叠。
问题 2：天花板与墙不严丝合缝，而且模型之间有重叠
    怀疑：天花板的 z 区间与墙体顶部的 z 区间重叠；天花板的平面范围又只到房间轮廓。

这个脚本把实测坐标打出来，不猜。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sk_client import SC, BridgeError  # noqa: E402

PROBE = r'''
m = Sketchup.active_model
K = 25.4
rows = []

# 注意 K 要当常量或参数传进去：方法内部看不到 main 的局部变量
# （Ruby 的作用域规则，我第一版就踩了这个，报 undefined local variable 'k'）
def rng(container, off)
  xs = []; ys = []; zs = []
  container.grep(Sketchup::Face).each do |f|
    f.vertices.each do |v|
      p = v.position
      xs << p.x + off.x; ys << p.y + off.y; zs << p.z + off.z
    end
  end
  return nil if xs.empty?
  { x: [(xs.min*K).round, (xs.max*K).round],
    y: [(ys.min*K).round, (ys.max*K).round],
    z: [(zs.min*K).round, (zs.max*K).round] }
end

groups = m.entities.grep(Sketchup::Group)

# ── 1) 外墙转角：看四面外墙端部的实际坐标
rows << "── 外墙各段（世界坐标，mm）"
groups.select { |g| g.name =~ /^W-/ && g.name !~ /(框|槛|玻璃|门扇)/ }
      .group_by { |g| g.name.split("-")[0..1].join("-") }
      .each do |wall, gs|
  all = gs.map { |g| rng(g.definition.entities, g.transformation.origin) }.compact
  next if all.empty?
  x0 = all.map { |r| r[:x][0] }.min; x1 = all.map { |r| r[:x][1] }.max
  y0 = all.map { |r| r[:y][0] }.min; y1 = all.map { |r| r[:y][1] }.max
  z1 = all.map { |r| r[:z][1] }.max
  rows << format("%-14s x=%5d..%5d  y=%5d..%5d  顶=%d", wall, x0, x1, y0, y1, z1)
end

# ── 2) 房间地面/天花 与 墙 的 z 关系
rows << ""
rows << "── 房间构件的 z 区间"
groups.select { |g| g.name =~ /^R-/ }.each do |g|
  g.definition.entities.grep(Sketchup::Group).each do |s|
    r = rng(s.definition.entities, s.transformation.origin)
    rows << format("  %-20s z=%s", s.name, r[:z].inspect) if r
  end
end

# ── 3) 具体检查：南墙与西墙在转角 (0,0) 处的覆盖情况
rows << ""
rows << "── 转角检查（以 (0,0) 为西南角轴线交点，墙厚 240）"
t = 240.0
rows << "  墙厚 #{t.to_i}，半厚 #{t/2}"
rows << "  若墙厚居中于轴线：南墙占 y=-120..120，西墙占 x=-120..120"
rows << "  → 外角 (0,0) 附近的 x<0 且 y<0 区域需要一面墙覆盖"
south = groups.select { |g| g.name.start_with?("W-南") }
west  = groups.select { |g| g.name.start_with?("W-西") }
sr = south.map { |g| rng(g.definition.entities, g.transformation.origin) }.compact
wr = west.map  { |g| rng(g.definition.entities, g.transformation.origin) }.compact
rows << format("  南墙范围 x=%d..%d y=%d..%d", sr.map { |r| r[:x][0] }.min, sr.map { |r| r[:x][1] }.max,
               sr.map { |r| r[:y][0] }.min, sr.map { |r| r[:y][1] }.max) unless sr.empty?
rows << format("  西墙范围 x=%d..%d y=%d..%d", wr.map { |r| r[:x][0] }.min, wr.map { |r| r[:x][1] }.max,
               wr.map { |r| r[:y][0] }.min, wr.map { |r| r[:y][1] }.max) unless wr.empty?

# ── 4) 转角缺口量化：每个角的"外表面是否连续"
rows << ""
rows << "── 转角缺口检查（判断标准：该角处是否有任何墙覆盖到建筑外轮廓角点）"
# 建筑外轮廓角点（由各墙最外侧坐标推出）
allw = groups.select { |g| g.name =~ /^W-/ && g.name !~ /(框|槛|玻璃|门扇|内墙)/ }
        .map { |g| rng(g.definition.entities, g.transformation.origin) }.compact
unless allw.empty?
  ex0 = allw.map { |r| r[:x][0] }.min
  ex1 = allw.map { |r| r[:x][1] }.max
  ey0 = allw.map { |r| r[:y][0] }.min
  ey1 = allw.map { |r| r[:y][1] }.max
  rows << format("  外墙总范围 x=%d..%d y=%d..%d", ex0, ex1, ey0, ey1)
  # 对四个角点，检查"该点周围 1mm 内是否有墙覆盖"
  [[ex0, ey0, "西南"], [ex1, ey0, "东南"], [ex0, ey1, "西北"], [ex1, ey1, "东北"]].each do |cx, cy, nm|
    cover = allw.count do |r|
      r[:x][0] <= cx + 1 && r[:x][1] >= cx - 1 && r[:y][0] <= cy + 1 && r[:y][1] >= cy - 1
    end
    rows << format("  %s角 (%d,%d)：被 %d 面墙的包围盒覆盖 %s", nm, cx, cy, cover,
                   cover.zero? ? "← ❌ 缺口！" : "")
  end
end

# ── 5) 天花板与墙的关系
rows << ""
rows << "── 天花板检查"
ceil = groups.select { |g| g.name =~ /-天花$/ }
        .map { |g| rng(g.definition.entities, g.transformation.origin) }.compact
ceil.each do |r|
  rows << format("  天花 z=%d..%d  x=%d..%d y=%d..%d", r[:z][0], r[:z][1], r[:x][0], r[:x][1], r[:y][0], r[:y][1])
end
walls_top = allw.map { |r| r[:z][1] }.uniq
rows << "  墙体顶面 z = #{walls_top.inspect}"
if !ceil.empty? && !walls_top.empty?
  rows << "  天花底面 #{ceil[0][:z][0]} vs 墙顶 #{walls_top.max} → " +
          (ceil[0][:z][0] == walls_top.max ? "✅ 齐平（天花坐在墙上）" : "⚠️ 不齐平")
end

puts rows.join(10.chr)
'''


def main() -> int:
    c = SC(timeout=60)
    try:
        r = c.ruby(PROBE, undo=False, timeout=60)
    except BridgeError as e:
        print(f"❌ [{e.code}] {str(e)[:400]}")
        return 1
    print(r["output"].strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
