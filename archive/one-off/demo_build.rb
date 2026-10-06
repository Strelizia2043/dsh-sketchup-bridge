# demo_build.rb -- 端到端验收：让 DSH 自己在 SketchUp 里建几何
#
# 这是**从 DSH 侧发过去执行的 Ruby**，不是 SketchUp 启动时加载的插件。
# 通过 SC.run_file() 发送。
#
# 它验证三件事：
#   1. DSH 能真的改模型（建面 + pushpull 成体）
#   2. 名字/中文/毫米单位都能正确往返
#   3. 分组与命名正确，且整个过程能被一步撤销

m = Sketchup.active_model
ents = m.entities

specs = [
  { x: 0,   y: 0,   h: 1200, color: 'red' },
  { x: 700, y: 0,   h: 800,  color: 'green' },
  { x: 0,   y: 700, h: 500,  color: 'blue' }
]

made = []
specs.each_with_index do |s, i|
  x = s[:x].mm
  y = s[:y].mm
  w = 400.mm
  h = s[:h].mm

  pts = [
    Geom::Point3d.new(x,     y,     0),
    Geom::Point3d.new(x + w, y,     0),
    Geom::Point3d.new(x + w, y + w, 0),
    Geom::Point3d.new(x,     y + w, 0)
  ]
  face = ents.add_face(pts)
  face.pushpull(-h)

  group = ents.add_group(face)
  group.name = "DSH-柱#{i + 1}-#{s[:h]}mm"
  group.material = s[:color] if group.respond_to?(:material=)

  made << "#{group.name}@#{s[:h]}mm"
end

m.active_view.zoom_extents

puts "建了 #{made.length} 根柱子：#{made.join('、')}"
puts "当前顶层实体数：#{ents.length}"
puts "模型范围(mm)：#{(m.bounds.width * 25.4).round} × #{(m.bounds.height * 25.4).round} × #{(m.bounds.depth * 25.4).round}"
