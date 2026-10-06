#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""最小实验：房间地面 + 天花放进同一组后，组的 bounds 是否被拉大？

背景：全流程构建后 R-主卧 的 bounds 变成 y=4320..12200（应为 4320..7880），
即被拉伸了。怀疑是"天花面与地面面在同一个组里、共用边后被 SketchUp 合并/切割"。
这个实验把可能的原因一个个隔离开。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sk_client import SC, BridgeError  # noqa: E402

EXPERIMENT = r'''
m = Sketchup.active_model
e = m.entities
out = []

def mm(v); (v * 25.4).round; end

def show(out, tag, g)
  bb = g.bounds
  fs = g.definition.entities.grep(Sketchup::Face)
  out << format("%-26s x=%d..%d y=%d..%d z=%d..%d  面数=%d",
                tag, mm(bb.min.x), mm(bb.max.x), mm(bb.min.y), mm(bb.max.y),
                mm(bb.min.z), mm(bb.max.z), fs.length)
end

poly = [[120, 4320], [3440, 4320], [3440, 7880], [120, 7880]]

# 实验 A：只建地面（基准）
begin
  f = e.add_face(poly.map { |p| Geom::Point3d.new(p[0]/25.4, p[1]/25.4, 0) })
  g = e.add_group(f); g.name = 'EXP-A-仅地面'
  show(out, 'A 仅地面', g)
rescue => ex
  out << "A 失败: #{ex.class}: #{ex.message}"
end

# 实验 B：地面 + 在**同一组内**新建天花（当前实现的做法）
begin
  f = e.add_face(poly.map { |p| Geom::Point3d.new(p[0]/25.4, p[1]/25.4, 0) })
  g = e.add_group(f); g.name = 'EXP-B-同组天花'
  gents = g.definition.entities
  cf = gents.add_face(poly.map { |p| Geom::Point3d.new(p[0]/25.4, p[1]/25.4, 2800/25.4) })
  cf.reverse! if cf && cf.normal.z > 0
  show(out, 'B 同组内加天花', g)
rescue => ex
  out << "B 失败: #{ex.class}: #{ex.message}"
end

# 实验 C：地面 + 天花建在**两个独立组**里（对照组）
begin
  f = e.add_face(poly.map { |p| Geom::Point3d.new(p[0]/25.4, p[1]/25.4, 0) })
  g = e.add_group(f); g.name = 'EXP-C1-地面'
  cf = e.add_face(poly.map { |p| Geom::Point3d.new(p[0]/25.4, p[1]/25.4, 2800/25.4) })
  g2 = e.add_group(cf); g2.name = 'EXP-C2-天花'
  show(out, 'C1 独立组-地面', g)
  show(out, 'C2 独立组-天花', g2)
rescue => ex
  out << "C 失败: #{ex.class}: #{ex.message}"
end

# 实验 D：地面组的顶点坐标 —— 确认多边形本身没被改
begin
  g = e.grep(Sketchup::Group).find { |x| x.name == 'EXP-B-同组天花' }
  if g
    pts = g.definition.entities.grep(Sketchup::Face).flat_map { |f| f.vertices.map { |v| v.position } }
    xs = pts.map { |p| mm(p.x) }.uniq.sort
    ys = pts.map { |p| mm(p.y) }.uniq.sort
    zs = pts.map { |p| mm(p.z) }.uniq.sort
    out << "D B组的顶点 x=#{xs.inspect}"
    out << "        y=#{ys.inspect}"
    out << "        z=#{zs.inspect}"
  end
rescue => ex
  out << "D 失败: #{ex.class}: #{ex.message}"
end

# 清理
%w[EXP-A-仅地面 EXP-B-同组天花 EXP-C1-地面 EXP-C2-天花].each do |nm|
  e.grep(Sketchup::Group).select { |g| g.name == nm }.each { |g| g.erase! }
end
out << "已清理，剩余顶层 #{e.length}"
puts out.join(10.chr)
'''


def main() -> int:
    c = SC(timeout=60)
    try:
        r = c.ruby(EXPERIMENT, op_name="DSH 天花实验")
        print(r["output"].strip())
    except BridgeError as e:
        print(f"❌ [{e.code}] {str(e)[:600]}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
