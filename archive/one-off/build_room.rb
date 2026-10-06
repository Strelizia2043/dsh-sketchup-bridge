# build_room.rb -- 3m×4m 房间，墙高 2.8m，一侧开 900×2100mm 门洞
#
# 这份是**实验之后的正确版本**。上一版有两个致命错误，都记在这里：
#
#   错误 1：pushpull 的方向
#     它是**沿面法线**推的，不是沿世界坐标轴。我以为 pushpull(+d) 总是向上，
#     结果门头被推到了 z=-700（地面以下）。实测数据：
#       地面矩形法线 z=-1，pushpull(+300mm) → 盒子落在 z=-300..0
#     所以必须**先问法线方向，再决定推拉的正负**（下面 rect_group / push 就是干这个的）。
#
#   错误 2：成组时抓错实体
#     我用了 `e.to_a.last(10)` 收集"刚建的实体"——这是**任意**实体，不是"我的"。
#     结果 102 个顶层实体：只有右垛进了组，左垛和门头散在顶层。
#     正确做法：**先把面收进组，再在组内推拉**（实验 C 验证：6 个面、一次成功）。

m = Sketchup.active_model
e = m.entities

W    = 3000.mm   # 房间宽度（X）
D    = 4000.mm   # 房间长度（Y）
H    = 2800.mm   # 墙高
T    = 100.mm    # 墙厚
DW   = 900.mm    # 门洞宽
DH   = 2100.mm   # 门洞高
DX   = 1100.mm   # 门洞左侧位置

out = []

# 建一个竖直墙段：底面矩形 [x0,x1] × [y0,y1]，向上拉起 h
# 做法：先把面收进组，再沿**面法线的反方向**推 h
#
# 为什么是反方向：地面矩形（从上方看是逆时针点序）的法线朝下（z=-1，实验 A 实测），
# 所以 pushpull(+h) 会把它推到地面以下。实验 A 的数据：
#     地面矩形 法线 z=-1，pushpull(+300mm) → 盒子落在 z=-300..0
# 因此要 pushpull(-h) 才能向上长。这里不硬写符号，而是按法线判断，最稳。
def wall_segment(ents, x0, y0, x1, y1, h, name)
  face = ents.add_face(
    Geom::Point3d.new(x0, y0, 0),
    Geom::Point3d.new(x1, y0, 0),
    Geom::Point3d.new(x1, y1, 0),
    Geom::Point3d.new(x0, y1, 0)
  )
  raise 'add_face 返回 nil（点可能共线）' if face.nil?
  group = ents.add_group(face)          # ← 先收进组（错误 2 的修法）
  # 先收进组，所以 face 现在在组内坐标里；法线仍在组坐标系中，符号判断依然成立
  face.pushpull(face.normal.z >= 0 ? h : -h)
  group.name = name
  group
end

# 门头（门洞上方那段墙）：底面矩形一样，但**立起来**到 DH..H
# 用竖直面推：先在 y=0 平面画一个 (x, z) 矩形，再沿 +Y 推到厚度 T
def door_header(ents, x0, x1, z0, z1, t, name)
  face = ents.add_face(
    Geom::Point3d.new(x0, 0, z0),
    Geom::Point3d.new(x1, 0, z0),
    Geom::Point3d.new(x1, 0, z1),
    Geom::Point3d.new(x0, 0, z1)
  )
  raise '门头 add_face 返回 nil' if face.nil?
  group = ents.add_group(face)
  n = face.normal
  # 沿 +Y 推 t：按法线方向决定正负
  face.pushpull(n.y >= 0 ? t : -t)
  group.name = name
  group
end

# ── 地板（单独成组，法线朝下，所以要往上推）
floor_face = e.add_face(
  Geom::Point3d.new(0, 0, 0),
  Geom::Point3d.new(W, 0, 0),
  Geom::Point3d.new(W, D, 0),
  Geom::Point3d.new(0, D, 0)
)
floor_group = e.add_group(floor_face)
floor_group.name = 'DSH-地板'
out << "地板 #{W.to_mm.round}×#{D.to_mm.round}mm"

# ── 四面墙：每面都是"底面矩形 → 收进组 → 组内按法线推 H"
front = wall_segment(e, 0, 0, W, T, H, 'DSH-前墙')
back  = wall_segment(e, 0, D - T, W, D, H, 'DSH-后墙')
left  = wall_segment(e, 0, T, T, D - T, H, 'DSH-左墙')
right = wall_segment(e, W - T, T, W, D - T, H, 'DSH-右墙')
out << '四面墙各成一个组（前/后/左/右）'

# ── 门洞：把前墙那一组"打开"——先删掉前墙组，改用 左垛 + 门头 + 右垛 三段重建
front.erase!
pieces = []
pieces << wall_segment(e, 0, 0, DX, T, H, 'DSH-前墙-左垛')
pieces << door_header(e, DX, DX + DW, DH, H, T, 'DSH-前墙-门头')
pieces << wall_segment(e, DX + DW, 0, W, T, H, 'DSH-前墙-右垛')
out << "前墙拆成 左垛 + 门头(#{DW.to_mm.round}宽) + 右垛，留出 #{DW.to_mm.round}×#{DH.to_mm.round}mm 门洞"

m.active_view.zoom_extents
out << "顶层实体 #{e.length} 个"
out << "净空(mm)：#{(W - 2 * T).to_mm.round} × #{(D - 2 * T).to_mm.round} × #{H.to_mm.round}"

# 自检：确认墙体世界高度真的是 2800（bounds 已经是世界坐标，不要再乘 25.4——
# 我上一版就是多乘了一次，于是自检把正确的墙报成 0mm）
def mm(v)
  (v * 25.4).round
end

groups = e.grep(Sketchup::Group)
bad = groups.reject do |g|
  next true if g.name == 'DSH-地板'
  mm(g.bounds.min.z).between?(-1, 1) && mm(g.bounds.max.z).between?(2799, 2801)
end
if bad.empty?
  out << '✅ 自检通过：所有墙体都从 z=0 长到 z=2800mm'
else
  out << "⚠️ 自检异常：#{bad.map { |g| "#{g.name}(z=#{mm(g.bounds.min.z)}..#{mm(g.bounds.max.z)})" }.join(', ')}"
end
out << "组清单：#{groups.map { |g| "#{g.name}[z #{mm(g.bounds.min.z)}..#{mm(g.bounds.max.z)}]" }.join(' / ')}"

puts out.join("\n")
