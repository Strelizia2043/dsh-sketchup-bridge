# designproject2 —— 按用户四条纠正重建（整模型一次建完）
#
# 用户纠正：
#   1. 家具没加全           → 归并阈值改 30mm，8 件 → 24 件
#   2. 窗户得做出来         → 玻璃要真的做（框 + 玻璃），不是留个洞
#   3. 开口太多             → 只保留 2 处：北墙 3200..6750、西墙 2250..6000
#                            东墙/南墙那两个是我误判的，删掉
#   4. 二层没屋顶、没中间墙 → 二层只留"单独突出来的小房间"
# 保留：周边平屋顶 + 中庭玻璃顶（前一轮已确认）
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

W = 8250.0          # 外轮廓
T = 100.0           # 墙厚
H1 = 2700.0         # 层高
FT = 100.0          # 楼板厚
Z2 = H1 + FT        # 二层楼面 = 2800
ZR = Z2 + H1        # 二层墙顶 = 屋顶下皮 = 5500
COURT = [2250.0, 2250.0, 6100.0, 6100.0]   # 中庭洞口

def box(ents, x0, y0, x1, y1, z0, h, name, mat = nil)
  g = DshBuild.box_on_ground(ents, x0, y0, x1, y1, h, name, z0)
  g.material = mat if mat
  g
end

# ── 楼板（中庭挖空：拆成 4 块绕开）
def slab_with_void(ents, name, z, th, mat)
  x0, y0, x1, y1 = COURT
  box(ents, 0, 0, W, y0, z, th, "#{name}-01", mat)
  box(ents, 0, y1, W, W, z, th, "#{name}-02", mat)
  box(ents, 0, y0, x0, y1, z, th, "#{name}-03", mat)
  box(ents, x1, y0, W, y1, z, th, "#{name}-04", mat)
end
slab_with_void(ents, 'F1-地板', 0, FT, nil)
slab_with_void(ents, 'F2-楼板', H1, FT, nil)

# ── 一层外墙：只开 2 个玻璃洞
#    洞口做成"窗"：上下框 + 中间玻璃
def wall_with_glass(ents, name, axis, at, z0, h, holes)
  th = T
  lo, hi = 0.0, W
  segs, cur = [], lo
  holes.sort_by { |a, _| a }.each do |a, b|
    segs << [cur, a] if a - cur > 1
    cur = b
  end
  segs << [cur, hi] if hi - cur > 1
  segs.each_with_index do |(a, b), i|
    if axis == 'h'
      box(ents, a, at - th / 2, b, at + th / 2, z0, h, "#{name}-#{format('%02d', i + 1)}")
    else
      box(ents, at - th / 2, a, at + th / 2, b, z0, h, "#{name}-#{format('%02d', i + 1)}")
    end
  end
  holes.each_with_index do |(a, b), i|
    if axis == 'h'
      box(ents, a, at - th / 2, b, at + th / 2, z0, 60, "#{name}-窗台框#{i + 1}", FRAME)
      box(ents, a, at - th / 2, b, at + th / 2, z0 + h - 60, 60, "#{name}-窗顶框#{i + 1}", FRAME)
      box(ents, a, at - 25, b, at + 25, z0 + 60, h - 120, "#{name}-玻璃#{i + 1}", GLASS)
    else
      box(ents, at - th / 2, a, at + th / 2, b, z0, 60, "#{name}-窗台框#{i + 1}", FRAME)
      box(ents, at - th / 2, a, at + th / 2, b, z0 + h - 60, 60, "#{name}-窗顶框#{i + 1}", FRAME)
      box(ents, at - 25, a, at + 25, b, z0 + 60, h - 120, "#{name}-玻璃#{i + 1}", GLASS)
    end
  end
end

wall_with_glass(ents, 'W-南外墙', 'h', 50.0,   0, H1, [[250.0, 2100.0]])
wall_with_glass(ents, 'W-北外墙', 'h', W - 50, 0, H1, [[3200.0, 6750.0]])
wall_with_glass(ents, 'W-西外墙', 'v', 50.0,   0, H1, [[2250.0, 6000.0]])
wall_with_glass(ents, 'W-东外墙', 'v', W - 50, 0, H1, [])

# ── 一层内墙：中庭四壁
box(ents, 2200, 100, 2300, 8150, 0, H1, 'W-中庭西壁')
box(ents, 6000, 100, 6100, 8150, 0, H1, 'W-中庭东壁')
box(ents, 100, 2200, 8150, 2300, 0, H1, 'W-中庭南壁')
box(ents, 100, 6000, 8150, 6100, 0, H1, 'W-中庭北壁')

# ── 屋顶：用户明确「二层没有屋顶」——只有那个小房间凸起来。
# 所以这里**不建周边平屋面板、也不建中庭玻璃顶**。
# 中庭上方是敞开的（这正是从侧面看二层只有一个凸起的意思）。
#
# ⚠️ 踩过：我上一版用「从 # ── 中庭玻璃顶 切到 # ── 旋转楼梯」来删屋顶，
# 结果**把小房间那一段也一起切掉了**（它夹在中间），房间根本没建出来，
# 而我没检查，直到量模型才发现 z 2700 以上只有楼板。
# **按下标区间删代码很危险——边界里可能夹着别的东西。**

# ── 二层小房间：**贴齐建筑的东南角**，只有它凸出在二层
#    东墙内皮对齐 8150（建筑东内皮），南墙内皮对齐 0（建筑南内皮）
RMX0, RMX1 = 5967.0, 8150.0
RMY0, RMY1 = 0.0, 2150.0
box(ents, RMX0, RMY0, RMX0 + T, RMY1, Z2, H1, 'L2-小房间-西墙')
box(ents, RMX1 - T, RMY0, RMX1, RMY1, Z2, H1, 'L2-小房间-东墙')
box(ents, RMX0, RMY0, RMX1, RMY0 + T, Z2, H1, 'L2-小房间-南墙')
box(ents, RMX0, RMY1 - T, RMX1, RMY1, Z2, H1, 'L2-小房间-北墙')
# 小房间自己的顶（只有它上面有盖，二层其余部分敞开）
box(ents, RMX0, RMY0, RMX1, RMY1, Z2 + H1, 150, 'L2-小房间-顶', ROOF)

# ── 旋转楼梯：中心 (7058,1125)，半径 900，16 级，共 420°
cx, cy, R = 7058.0, 1125.0, 900.0
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

# ── 家具（24 件体块，来自 cad/project2_furniture.json）
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
  puts "  家具 #{(fur['L1'] || []).size} 件"
end

puts "  顶层组 #{ents.grep(Sketchup::Group).size} 个"
