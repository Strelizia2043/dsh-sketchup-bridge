# 三件事（用户原话）：
#   1.「把1楼房顶中间的玻璃窗给我加回来」→ 中庭（楼板正中间那个洞）上方补玻璃顶
#   2.「墙面全部涂成银色」              → 所有墙组（含窗框之外的部分）
#   3.「地面给我涂成棕色」              → F1 地板 / F2 楼板
#
# ⚠️ 一个要把握的分寸：楼梯的踏面不该被当成"地面"刷成棕色后失去木质感，
#    但地板确实是棕色。这里只刷名字里是楼板/地板的组，不碰楼梯。
load 'E:/deepseek工作区/sketchup-bridge/build_from_plan.rb'

m = Sketchup.active_model
ents = m.entities
T, H1, FT = 100.0, 2700.0, 100.0
COURT = [2250.0, 2250.0, 6100.0, 6100.0]

# ⚠️ 这里必须用 lambda 而不是 def：
# Ruby 的 `def` **看不见外层的局部变量**，写成 `def mat(...)` 会报
# `undefined local variable or method 'm'`（刚踩过）。
# lambda 是闭包，能捕获上面的 m。
mat = lambda do |name, rgb, alpha = nil|
  x = m.materials[name] || m.materials.add(name)
  x.color = Sketchup::Color.new(*rgb)
  x.alpha = alpha if alpha
  x
end
GLASS  = mat.call('DSH_Glass', [165, 210, 225], 0.35)
SILVER = mat.call('DSH_Silver', [176, 180, 186])
BROWN  = mat.call('DSH_FloorBrown', [138, 96, 62])

# ── 1. 中庭玻璃顶加回来（坐在一层墙顶 2700，厚 100）
g = DshBuild.box_on_ground(ents, COURT[0], COURT[1], COURT[2], COURT[3], FT,
                           'ROOF-中庭玻璃顶', H1)
g.material = GLASS
puts "  已加中庭玻璃顶 X #{COURT[0].round}..#{COURT[2].round} Y #{COURT[1].round}..#{COURT[3].round} Z #{H1.round}..#{(H1 + FT).round}"

# ── 2/3. 上材质
gs = ents.grep(Sketchup::Group)
n_wall = 0
n_floor = 0
gs.each do |grp|
  nm = grp.name.to_s
  # 地板/楼板 → 棕色
  if nm.start_with?('F1-') || nm.start_with?('F2-')
    grp.material = BROWN
    n_floor += 1
    next
  end
  # 玻璃、窗框、屋顶板、楼梯、家具、玻璃顶 → 各自保留，不刷银
  next if nm.include?('玻璃') || nm.include?('窗台框') || nm.include?('窗顶框')
  next if nm.include?('ROOF') || nm.start_with?('ST-') || nm.start_with?('FUR-')
  # 其余（各种墙）→ 银色
  if nm.start_with?('W-') || nm.include?('墙')
    grp.material = SILVER
    n_wall += 1
  end
end
puts "  墙面刷银 #{n_wall} 组；地板刷棕 #{n_floor} 组"
puts "  顶层组 #{gs.size} 个"
