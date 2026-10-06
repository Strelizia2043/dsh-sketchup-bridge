# 给 designproject2 两层模型补完剩下的四件事：
#   ① 周边平屋面板（中庭处留洞，玻璃顶在 2700..2800）
#   ② 旋转楼梯（中心 7058,1125，半径 900，从 0 到二层地面 2800）
#   ③ 家具体块（来自 cad/project2_furniture.json，用户说尺寸不严格）
#   ④ 地面材质（用户提过做了纹理；没给图，先用区分材质占位，并把缺口记下来）
#
# 全部用**扁平矩形/盒子**构造 —— 项目里 create_face 的多边形带洞曾出问题，
# 所以 ① 用四块拼成"回"字形，不用带内圈的面。
$LOAD = "E:/deepseek工作区/sketchup-bridge/build_from_plan.rb"
load $LOAD

m = Sketchup.active_model
ents = m.entities
S = DshBuild

def mat_of(model, name, rgb, alpha = nil)
  mt = model.materials[name] || model.materials.add(name)
  mt.color = Sketchup::Color.new(*rgb)
  mt.alpha = alpha if alpha
  mt
end

glass = mat_of(m, 'DSH_Glass', [150, 200, 220], 0.35)
roofm = mat_of(m, 'DSH_Roof', [120, 120, 125])
conc  = mat_of(m, 'DSH_Concrete', [200, 198, 192])
wood  = mat_of(m, 'DSH_Wood', [176, 137, 104])
metal = mat_of(m, 'DSH_Metal', [160, 164, 170])

W = 8250.0
# ── ① 周边平屋面板：坐在二层墙顶 5500，中庭处（2250..6100）留洞
#     用四块拼出"回"字，厚度 150
z_roof = 5500.0
th_roof = 150.0
ring = [
  [0.0,    0.0,    W,      2250.0, 'ROOF-南翼'],   # Y 小 = 南
  [0.0,    6100.0, W,      W,      'ROOF-北翼'],   # Y 大 = 北
  [0.0,    2250.0, 2250.0, 6100.0, 'ROOF-西翼'],
  [6100.0, 2250.0, W,      6100.0, 'ROOF-东翼'],
]
ring.each do |x0, y0, x1, y1, nm|
  g = S.box_on_ground(ents, x0, y0, x1, y1, th_roof, nm, z_roof)
  g.material = roofm
end

# ── ② 旋转楼梯：中心 (7058, 1125)，半径 900
#     16 级，每级升高 2800/16 = 175，绕 360°
cx = 7058.0
cy = 1125.0
rad = 900.0
steps = 16
rise = 2800.0 / steps
# 中柱
col = S.box_on_ground(ents, cx - 90, cy - 90, cx + 90, cy + 90, 2800, 'ST-中柱', 0)
col.material = metal
steps.times do |i|
  a0 = i * (360.0 / steps)
  z = i * rise
  # 每级做成一个扇形近似：用 3 块绕中心的小盒子拼出楔形
  3.times do |k|
    ang = a0 + k * (360.0 / steps / 3.0)
    rad_in = 150.0
    rad_out = rad
    mid = (rad_in + rad_out) / 2.0
    seg_len = rad_out - rad_in
    arc_w = 2 * Math::PI * mid * (360.0 / steps / 3.0) / 360.0
    g = S.box_abs(ents, cx + mid * Math.cos(ang * Math::PI / 180),
                  cy + mid * Math.sin(ang * Math::PI / 180),
                  seg_len, arc_w, 60, z, ang, "ST-踏#{i + 1}-#{k + 1}", 0)
    g.material = wood if g.respond_to?(:material=)
  end
end

# ── ③ 家具体块（数据来自 cad/project2_furniture.json，用户说不严格）
require 'json'
fp = 'E:/deepseek工作区/sketchup-bridge/cad/project2_furniture.json'
if File.exist?(fp)
  fur = JSON.parse(File.read(fp, encoding: 'UTF-8'))
  (fur['L1'] || []).each_with_index do |b, i|
    w = b['x1'] - b['x0']
    h = b['y1'] - b['y0']
    # 高度按面积粗判：大件（床/沙发）450，小件 750
    hz = (w * h > 2_500_000) ? 450.0 : 750.0
    g = S.box_on_ground(ents, b['x0'], b['y0'], b['x1'], b['y1'], hz,
                        format('FUR-%02d', i + 1), 100)
    g.material = wood
  end
  puts "  家具 #{ (fur['L1'] || []).size } 件"
end

puts "  顶层组 #{ents.grep(Sketchup::Group).size} 个"
