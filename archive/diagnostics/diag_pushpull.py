#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测准 pushpull 的力学语义，以及"面→成组→组内推拉"的正确写法。

要回答三个问题：
  A) 竖直面（法线沿 ±Y）用 pushpull(+d) 到底往哪边推？
  B) 到底该"先成组再在组内推拉"，还是"先推拉再成组"？
  C) 怎么可靠地把"我新建的实体"收集起来成组（不能再用 e.to_a.last(n) 这种脆弱写法）？

每个实验都在独立命名组里做，测完即删，不污染模型。
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

def report(out, tag, g)
  bb = g.bounds
  out << format("%-34s min=(%.0f,%.0f,%.0f) max=(%.0f,%.0f,%.0f) 体积实体=%d",
                tag,
                bb.min.x * 25.4, bb.min.y * 25.4, bb.min.z * 25.4,
                bb.max.x * 25.4, bb.max.y * 25.4, bb.max.z * 25.4,
                g.definition.entities.grep(Sketchup::Face).length)
end

# ── 实验 A：水平地面上的矩形，正距离推拉
begin
  f = e.add_face(Geom::Point3d.new(0, 0, 0), Geom::Point3d.new(500.mm, 0, 0),
                 Geom::Point3d.new(500.mm, 500.mm, 0), Geom::Point3d.new(0, 500.mm, 0))
  nz = f.normal.z
  f.pushpull(300.mm)
  g = e.add_group(e.to_a.last)
  g.name = 'EXP-A'
  out << "A) 地面矩形 法线z=#{nz.round(3)} pushpull(+300mm)："
  report(out, '   结果', g)
rescue => ex
  out << "A) 失败: #{ex.class}: #{ex.message}"
end

# ── 实验 B：竖直面（沿 Y 方向），正距离推拉
begin
  f = e.add_face(Geom::Point3d.new(0, 0, 0), Geom::Point3d.new(500.mm, 0, 0),
                 Geom::Point3d.new(500.mm, 0, 500.mm), Geom::Point3d.new(0, 0, 500.mm))
  ny = f.normal.y
  f.pushpull(200.mm)
  g = e.add_group(e.to_a.last)
  g.name = 'EXP-B'
  out << "B) 竖直面 法线y=#{ny.round(3)} pushpull(+200mm)："
  report(out, '   结果', g)
rescue => ex
  out << "B) 失败: #{ex.class}: #{ex.message}"
end

# ── 实验 C：先成组，再在组内推拉（推荐写法）
begin
  f = e.add_face(Geom::Point3d.new(1000.mm, 0, 0), Geom::Point3d.new(1500.mm, 0, 0),
                 Geom::Point3d.new(1500.mm, 500.mm, 0), Geom::Point3d.new(1000.mm, 0, 0) + Geom::Vector3d.new(0, 500.mm, 0))
  g = e.add_group(f)          # 先把面收进组
  inside = g.definition.entities
  nz = f.normal.z
  f.pushpull(400.mm)          # 在组内推拉（f 仍有效吗？）
  g.name = 'EXP-C'
  out << "C) 先成组再推拉：面法线z=#{nz.round(3)}，组内面数=#{inside.grep(Sketchup::Face).length}"
  report(out, '   结果', g)
rescue => ex
  out << "C) 失败: #{ex.class}: #{ex.message}"
end

# ── 清理所有实验组
%w[EXP-A EXP-B EXP-C].each do |nm|
  e.grep(Sketchup::Group).select { |g| g.name == nm }.each { |g| g.erase! }
end
out << "实验组已清理，当前顶层实体 #{e.length}"
puts out.join("\n")
'''


def main() -> int:
    c = SC(timeout=60)
    try:
        r = c.ruby(EXPERIMENT, op_name="DSH pushpull 实验")
        print(r["output"].strip())
        print()
        print(f"changed={r['changed']} delta={r['delta']}")
    except BridgeError as e:
        print(f"❌ [{e.code}] {str(e)[:600]}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
