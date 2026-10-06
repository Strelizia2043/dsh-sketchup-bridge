# 按用户四条新纠正重建
#   1. 「我刚才让你加的那扇门好像变成窗户了」→ 南墙那个是**门**，不该有玻璃和窗框
#   2. 「从1楼上旋转楼梯上来，上面总不能被撞头」→ **二层楼板在楼梯处要开洞**（楼梯井）
#   3. 「小房间也要开门啊，要不然我怎么去2楼」→ 小房间墙上开门
#
# 关键几何：旋转楼梯中心 (7058,1125)、半径 900 —— **它整个落在小房间范围内**
# （小房间 X 5967..8150，Y 0..2150）。所以：
#   · 楼梯井洞开在楼板上，范围要盖住梯段
#   · 小房间的入口开在朝楼梯的那面墙（西墙），人从梯段平台进房间
load 'E:/deepseek工作区/sketchup-bridge/build_from_plan.rb'

S = DshBuild
m = Sketchup.active_model
m.entities.clear!
ents = m.entities

def mt(model, name, rgb, alpha = nil)
  x = model.materials[name] || model.materials.add(name)
  x.color = Sketchup::Color.new(*rgb)
  x.alpha = alpha if alpha
  x
end
GLASS = mt(m, 'DSH_Glass', [150, 200, 220], 0.35)
FRAME = mt(m, 'DSH_Frame', [62, 62, 66])
ROOF  = mt(m, 'DSH_Roof',  [118, 118, 124])
WOOD  = mt(m, 'DSH_Wood',  [176, 137, 104])

W, T, H1, FT = 8250.0, 100.0, 2700.0, 100.0
Z2 = H1 + FT          # 2800
COURT = [2250.0, 2250.0, 6100.0, 6100.0]

def box(ents, x0, y0, x1, y1, z0, h, name, mat = nil)
  g = DshBuild.box_on_ground(ents, x0, y0, x1, y1, h, name, z0)
  g.material = mat if mat
  g
end

# ── 楼板：通用"挖洞"版本（中庭 + 楼梯井）
def slab_holes(ents, name, z, th, holes)
  # 用 cad_to_plan 里验证过的 floor_with_holes 思路：拆成无重叠矩形
  xs = ([0.0, W] + holes.flat_map { |h| [h[0], h[2]] }).uniq.sort
  ys = ([0.0, W] + holes.flat_map { |h| [h[1], h[3]] }).uniq.sort
  n = 0
  ys.each_cons(2) do |ya, yb|
    next if yb - ya < 1
    xs.each_cons(2) do |xa, xb|
      next if xb - xa < 1
      mx, my = (xa + xb) / 2.0, (ya + yb) / 2.0
      inhole = holes.any? { |h| h[0] <= mx && mx <= h[2] && h[1] <= my && my <= h[3] }
      next if inhole
      n += 1
      box(ents, xa, ya, xb, yb, z, th, "#{name}-#{format('%02d', n)}")
    end
  end
  n
end

# 楼梯井 = **小房间的整个内空**（用户原话：「楼梯井就是房间，不另留平台」）
#
# 为什么不做成"半径 950 的方形"：实测那样四周只剩 142mm 楼板边，
# **站不下人**——西墙开门出去直接是洞。用户明确不要平台，
# 所以把洞放大到房间内空，人从楼梯顶直接进房间。
SC = [7058.0, 1125.0]
RMX0, RMX1 = 5967.0, 8150.0
RMY0, RMY1 = 0.0, 2150.0
STAIR_WELL = [RMX0 + T, RMY0 + T, RMX1 - T, RMY1 - T]
n1 = slab_holes(ents, 'F1-地板', 0, FT, [COURT])
puts "  F1 地板 #{n1} 块（挖中庭）"
n2 = slab_holes(ents, 'F2-楼板', H1, FT, [COURT, STAIR_WELL])
puts "  F2 楼板 #{n2} 块（挖中庭 + 楼梯井）"

# ── 外墙：区分"门"和"窗"
#    door   → 只留洞，不装玻璃不装框
#    window → 窗台框 + 窗顶框 + 玻璃
def wall(ents, name, axis, at, z0, h, ops)
  op = ->(a, b, z, hh, i, tag, mat) do
    if axis == 'h'
      box(ents, a, at - T / 2, b, at + T / 2, z, hh, "#{name}-#{tag}#{i}", mat)
    else
      box(ents, at - T / 2, a, at + T / 2, b, z, hh, "#{name}-#{tag}#{i}", mat)
    end
  end
  segs, cur = [], 0.0
  ops.sort_by { |o| o[:a] }.each do |o|
    segs << [cur, o[:a]] if o[:a] - cur > 1
    cur = o[:b]
  end
  segs << [cur, W] if W - cur > 1
  segs.each_with_index { |(a, b), i| op.call(a, b, z0, h, i + 1, '', nil) }
  ops.each_with_index do |o, i|
    next if o[:kind] == 'door'
    op.call(o[:a], o[:b], z0, 60, i + 1, '窗台框', FRAME)
    op.call(o[:a], o[:b], z0 + h - 60, 60, i + 1, '窗顶框', FRAME)
    g = (axis == 'h') ? box(ents, o[:a], at - 25, o[:b], at + 25, z0 + 60, h - 120, "#{name}-玻璃#{i + 1}", GLASS) :
                        box(ents, at - 25, o[:a], at + 25, o[:b], z0 + 60, h - 120, "#{name}-玻璃#{i + 1}", GLASS)
  end
end

wall(ents, 'W-南外墙', 'h', 50.0,   0, H1, [{ a: 250.0,  b: 2100.0, kind: 'door' }])
wall(ents, 'W-北外墙', 'h', W - 50, 0, H1, [{ a: 3200.0, b: 6750.0, kind: 'window' }])
wall(ents, 'W-西外墙', 'v', 50.0,   0, H1, [{ a: 2250.0, b: 6000.0, kind: 'window' }])
wall(ents, 'W-东外墙', 'v', W - 50, 0, H1, [])

# ── 一层内墙：中庭四壁
box(ents, 2200, 100, 2300, 8150, 0, H1, 'W-中庭西壁')
box(ents, 6000, 100, 6100, 8150, 0, H1, 'W-中庭东壁')
box(ents, 100, 2200, 8150, 2300, 0, H1, 'W-中庭南壁')
box(ents, 100, 6000, 8150, 6100, 0, H1, 'W-中庭北壁')

# ── 二层小房间：贴东南角，**西墙开门**（朝楼梯井）
DOOR_A, DOOR_B = 300.0, 1200.0        # 西墙上的门洞（沿 y）
# 西墙拆两段，中间留门
box(ents, RMX0, RMY0, RMX0 + T, DOOR_A, Z2, H1, 'L2-小房间-西墙-01')
box(ents, RMX0, DOOR_B, RMX0 + T, RMY1, Z2, H1, 'L2-小房间-西墙-02')
box(ents, RMX0, DOOR_A, RMX0 + T, DOOR_B, Z2 + H1 - 2100, 2100 - (H1 - 2100) + 0, 'L2-小房间-西墙-门楣')
box(ents, RMX1 - T, RMY0, RMX1, RMY1, Z2, H1, 'L2-小房间-东墙')
box(ents, RMX0, RMY0, RMX1, RMY0 + T, Z2, H1, 'L2-小房间-南墙')
box(ents, RMX0, RMY1 - T, RMX1, RMY1, Z2, H1, 'L2-小房间-北墙')
box(ents, RMX0, RMY0, RMX1, RMY1, Z2 + H1, 150, 'L2-小房间-顶', ROOF)

# ── 旋转楼梯
cx, cy, R = SC[0], SC[1], 900.0
steps = 16
rise = Z2 / steps
sweep = 420.0 / steps
box(ents, cx - 90, cy - 90, cx + 90, cy + 90, 0, Z2, 'ST-中柱')
steps.times do |i|
  a0 = i * sweep
  a1 = a0 + sweep + 4.0
  z = i * rise
  pts = [Geom::Point3d.new(DshBuild.mm(cx), DshBuild.mm(cy), DshBuild.mm(z + rise))]
  12.times do |k|
    ang = (a0 + (a1 - a0) * k / 11.0) * Math::PI / 180.0
    pts << Geom::Point3d.new(DshBuild.mm(cx + R * Math.cos(ang)),
                             DshBuild.mm(cy + R * Math.sin(ang)),
                             DshBuild.mm(z + rise))
  end
  face = ents.add_face(pts)
  next if face.nil?
  g = ents.add_group(face)
  g.name = "ST-踏#{format('%02d', i + 1)}"
  face.pushpull(-DshBuild.mm(70))
  g.material = WOOD
end

# ── 家具
require 'json'
fp = 'E:/deepseek工作区/sketchup-bridge/cad/project2_furniture.json'
if File.exist?(fp)
  fur = JSON.parse(File.read(fp, encoding: 'UTF-8'))
  (fur['L1'] || []).each_with_index do |b, i|
    w = b['x1'] - b['x0']
    d = b['y1'] - b['y0']
    hz = (w * d > 2_000_000) ? 450.0 : 750.0
    box(ents, b['x0'], b['y0'], b['x1'], b['y1'], FT, hz, format('FUR-%02d', i + 1), WOOD)
  end
end

puts "  顶层组 #{ents.grep(Sketchup::Group).size} 个"
puts "  楼梯井范围 X #{STAIR_WELL[0].round}..#{STAIR_WELL[2].round}  Y #{STAIR_WELL[1].round}..#{STAIR_WELL[3].round}"
