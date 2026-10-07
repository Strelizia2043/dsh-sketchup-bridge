# .skp 模型指纹提取
#
# 回答"给你一个 skp 能不能学"：看**能读出来什么**。
# 读的是几何与元数据，不是设计意图 —— 但很多东西是能反推的。
#
# 输出一份结构化指纹，用来：
#   ① 学命名约定（前缀、分层、编号规则）
#   ② 学材质用法（名字、颜色、刷在谁身上）
#   ③ 学组织方式（组嵌套、图层、组件复用）
#   ④ 反推平面数据（墙的中线/厚度/高度、房间轮廓）

m = Sketchup.active_model
MM = 25.4

def mmv(v) = (v * MM).round(1)

puts "══ 1. 文档元数据"
puts "  标题        #{m.title}"
puts "  路径        #{m.path}"
puts "  单位        #{m.options['UnitsOptions']['LengthUnit']}（4=mm）"
puts "  模型范围    X %.0f..%.0f  Y %.0f..%.0f  Z %.0f..%.0f" % [
  m.bounds.min.x*MM, m.bounds.max.x*MM,
  m.bounds.min.y*MM, m.bounds.max.y*MM,
  m.bounds.min.z*MM, m.bounds.max.z*MM]

puts
puts "══ 2. 实体统计"
top = m.entities
puts "  顶层：组 #{top.grep(Sketchup::Group).size}  组件 #{top.grep(Sketchup::ComponentInstance).size}"
puts "  定义表：组件定义 #{m.definitions.size}"
puts "  材质 #{m.materials.size}   图层 #{m.layers.size}   页面 #{m.pages.size}"

allf = 0; alle = 0; allg = 0
walk = lambda do |ents, depth|
  ents.each do |e|
    if e.is_a?(Sketchup::Group) || e.is_a?(Sketchup::ComponentInstance)
      allg += 1
      walk.call(e.definition.entities, depth + 1) if depth < 8
    elsif e.is_a?(Sketchup::Face)
      allf += 1
    elsif e.is_a?(Sketchup::Edge)
      alle += 1
    end
  end
end
walk.call(top.to_a, 0)
puts "  递归统计：容器 #{allg}  面 #{allf}  边 #{alle}"

puts
puts "══ 3. 命名约定（按前缀归类）"
names = []
collect = lambda do |ents, prefix, depth|
  ents.grep(Sketchup::Group).each do |g|
    nm = g.name.to_s
    names << [prefix + nm, depth, g] unless nm.empty?
    collect.call(g.definition.entities, "#{prefix}#{nm}/", depth + 1) if depth < 4
  end
  ents.grep(Sketchup::ComponentInstance).each do |c|
    nm = c.name.to_s
    names << [prefix + nm + " ⟨组件⟩", depth, c] unless nm.empty?
  end
end
collect.call(top, "", 0)
pre = Hash.new(0)
names.each { |n, _, _| pre[n.split(/[-_]/).first] += 1 }
puts "  共 #{names.size} 个有名字的容器"
puts "  前缀分布："
pre.sort_by { |_, v| -v }.first(14).each { |k, v| puts "    %-14s %d" % [k, v] }

puts
puts "══ 4. 命名样例（含尺寸，能看出尺度体系）"
sz = lambda do |g|
  b = g.bounds
  [mmv(b.width), mmv(b.height), mmv(b.depth)]
end
names.sort_by { |n, d, _| [d, n] }.first(18).each do |n, d, g|
  s = sz.call(g)
  puts "  %s%-34s %8.0f × %8.0f × %8.0f" % ["  " * d, n, s[0], s[1], s[2]]
end

puts
puts "══ 5. 材质"
m.materials.each do |mat|
  c = mat.color
  puts "  %-22s RGBA(%3d,%3d,%3d,%3d)" % [mat.name, c.red, c.green, c.blue, mat.alpha]
end

puts
puts "══ 6. 图层"
m.layers.each { |l| puts "  #{l.name}#{l.visible? ? '' : '（隐藏）'}" }

puts
puts "══ 7. 组嵌套深度分布"
dep = Hash.new(0)
names.each { |_, d, _| dep[d] += 1 }
dep.sort.each { |d, n| puts "  深度 #{d}：#{n} 个" }

puts
puts "══ 8. 上材质的容器数"
painted = 0
walk2 = lambda do |ents|
  ents.each do |e|
    next unless e.is_a?(Sketchup::Group) || e.is_a?(Sketchup::ComponentInstance)
    painted += 1 if e.material
    walk2.call(e.definition.entities)
  end
end
walk2.call(top.to_a)
puts "  有材质的容器 #{painted} / #{allg}"

puts
puts "══ 9. 是否做过实体化（manifold）检查"
solid = 0; checked = 0
top.grep(Sketchup::Group).first(40).each do |g|
  checked += 1
  solid += 1 if (g.manifold? rescue false)
end
puts "  顶层组里 #{solid} / #{checked} 是封闭实体"
