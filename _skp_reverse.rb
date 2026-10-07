# 从 .skp 反推平面数据（墙轴线 / 房间 / 楼板）—— 验证"能不能学"
#
# 这是关键测试：
#   读名字和尺寸只是"看见"，**能反推成可重建的数据**才算"学到"。
#
# 反推逻辑：
#   ① 墙：`W-*` 组被洞口切成多块。同一道墙的各块共享轴线，
#      按"轴线 + 厚度"归组，取沿轴方向的并集 = 墙的实际跨度。
#   ② 房间：`R-*` 组是房间容器，外接范围就是房间轮廓。
#   ③ 楼板/屋顶：`F*/ROOF*` 组的外接范围 + 厚度。
#
# 反推结果可以直接喂回 build_from_plan.rb —— 如果重建出来的几何
# 和原模型对得上，就证明"学"这件事成立。

require 'json'
m = Sketchup.active_model
MM = 25.4
TOL = 30.0    # 轴线归并容差（mm）

def bb(g)
  b = g.bounds
  { x0: b.min.x * 25.4, x1: b.max.x * 25.4,
    y0: b.min.y * 25.4, y1: b.max.y * 25.4,
    z0: b.min.z * 25.4, z1: b.max.z * 25.4 }
end

groups = m.entities.grep(Sketchup::Group)
walls = groups.select { |g| g.name.to_s.start_with?('W-') }
rooms = groups.select { |g| g.name.to_s.start_with?('R-') }
slabs = groups.select { |g| g.name.to_s =~ /\A(F\d|ROOF|MZ)/ }

puts "══ ① 墙：从 #{walls.size} 个墙组反推轴线"

# 每块墙：判断是横墙还是竖墙（取长边方向），算出轴线位置
segs = walls.map do |g|
  b = bb(g)
  w = b[:x1] - b[:x0]
  h = b[:y1] - b[:y0]
  if w >= h            # 横墙：沿 x 展开，轴线在 y
    { axis: :y, at: (b[:y0] + b[:y1]) / 2.0, th: h, lo: b[:x0], hi: b[:x1],
      z0: b[:z0], z1: b[:z1], name: g.name.to_s }
  else                 # 竖墙：沿 y 展开，轴线在 x
    { axis: :x, at: (b[:x0] + b[:x1]) / 2.0, th: w, lo: b[:y0], hi: b[:y1],
      z0: b[:z0], z1: b[:z1], name: g.name.to_s }
  end
end

# 按"轴线 + 厚度 + 标高区间"归并（同一道墙被洞口切成的多块会归到一起）
merged = []
segs.each do |s|
  hit = merged.find do |t|
    t[:axis] == s[:axis] && (t[:at] - s[:at]).abs < TOL &&
      (t[:th] - s[:th]).abs < TOL &&
      (t[:z0] - s[:z0]).abs < TOL && (t[:z1] - s[:z1]).abs < TOL
  end
  if hit
    hit[:lo] = [hit[:lo], s[:lo]].min
    hit[:hi] = [hit[:hi], s[:hi]].max
    hit[:n] += 1
  else
    merged << s.merge(n: 1)
  end
end

puts "  #{segs.size} 块 → 归并成 #{merged.size} 道墙（同轴线的多块合并了）"
merged.sort_by { |t| [t[:z0], t[:axis].to_s, t[:at]] }.first(20).each do |t|
  puts "    %-3s 轴 %7.1f  厚 %5.1f  跨 %7.1f..%-7.1f  Z %5.0f..%-5.0f  由 %d 块" % [
    t[:axis].to_s, t[:at], t[:th], t[:lo], t[:hi], t[:z0], t[:z1], t[:n]]
end

puts
puts "══ ② 房间：从 #{rooms.size} 个 R-* 组反推轮廓"
rooms.sort_by { |g| g.name.to_s }.each do |g|
  b = bb(g)
  puts "  %-12s  X %7.0f..%-7.0f Y %7.0f..%-7.0f  高 %5.0f" % [
    g.name, b[:x0], b[:x1], b[:y0], b[:y1], b[:z1] - b[:z0]]
  # 房间组里还有子构件（地面/天花）
  kids = g.definition.entities.grep(Sketchup::Group).map { |k| k.name.to_s }
  puts "                子构件：#{kids.join(', ')}" unless kids.empty?
end

puts
puts "══ ③ 楼板 / 屋顶"
slabs.sort_by { |g| g.name.to_s }.each do |g|
  b = bb(g)
  puts "  %-14s X %7.0f..%-7.0f Y %7.0f..%-7.0f  Z %5.0f..%-5.0f (厚 %.0f)" % [
    g.name, b[:x0], b[:x1], b[:y0], b[:y1], b[:z0], b[:z1], b[:z1] - b[:z0]]
end

puts
puts "══ ④ 反推的标高体系"
zs = (merged.map { |t| t[:z0] } + merged.map { |t| t[:z1] }).uniq.sort
puts "  出现过的标高：#{zs.map { |z| z.round }.inspect}"
puts "  墙高（去重）：#{merged.map { |t| (t[:z1] - t[:z0]).round }.uniq.sort.inspect}"
