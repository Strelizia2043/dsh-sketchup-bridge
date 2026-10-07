# 通用构件库（墙开门窗 / 楼板挖洞 / 螺旋楼梯 / 材质）
# 放在同一目录，用绝对路径加载，避免依赖 
_parts = File.join(File.dirname(File.expand_path(__FILE__)), 'dsh_parts.rb')
load _parts if File.exist?(_parts)

# build_from_plan.rb -- 从"建筑描述数据"生成 SketchUp 模型
#
# 输入：一个 JSON 对象（通常由 DSH 读图后生成，也可手写），字段见 plan_schema.md
# 输出：SketchUp 里的分组几何 + 一份自检报告
#
# 设计原则（都是前面踩坑换来的）：
#   1. 一切都用**毫米**描述，内部转英寸
#   2. 每个构件独立成组并命名 → 你能单独选中、单独改
#   3. 墙体开洞**不用布尔运算**，而是把墙拆成互不重叠的矩形块
#      （SketchUp 免费版没有可靠的布尔 API，拆块是确定性的，且结果干净）
#   4. 每个构件建完立刻自检位置与尺寸，错了当场报，不留给眼睛去发现
#   5. pushpull 一律按面法线方向判断正负（地面矩形法线朝下，这是实测过的）

module DshBuild
  MM = 25.4 # 1 毫米 = 1/25.4 英寸

  module_function

  def mm(v)
    (v.to_f / MM)
  end

  def to_mm(v)
    (v.to_f * MM).round(1)
  end

  # ---------------------------------------------------------------- 基础几何

  # 在地面（z=0）建一个矩形实体块 [x0,x1] × [y0,y1]，高度 h，向上长
  # 返回 group。名字用 name。
  def box_on_ground(ents, x0, y0, x1, y1, h, name, z0 = 0)
    face = ents.add_face(
      Geom::Point3d.new(mm(x0), mm(y0), mm(z0)),
      Geom::Point3d.new(mm(x1), mm(y0), mm(z0)),
      Geom::Point3d.new(mm(x1), mm(y1), mm(z0)),
      Geom::Point3d.new(mm(x0), mm(y1), mm(z0))
    )
    raise "add_face 返回 nil：矩形可能退化 (#{x0},#{y0})-(#{x1},#{y1})" if face.nil?
    group = ents.add_group(face)
    # 按法线判断方向：地面矩形法线朝下，所以要取反才能向上长
    face.pushpull(face.normal.z >= 0 ? mm(h) : -mm(h))
    group.name = name
    group
  end

  # ---------------------------------------------------------------- 墙体开洞
  #
  # 把一段墙沿长度方向拆成互不重叠的"竖直条"，每条的 z 区间由洞口分布决定。
  # 返回 [[u0, u1, z0, z1], ...]，单位为毫米（u 是沿墙长度方向的局部坐标）。
  #
  # 算法：把所有洞口的左右边界收集成关键 u 点，切成若干 u 区间；
  #       每个区间内，洞口集合固定，于是该区间的 z 覆盖 = [0,wall_h] 减去洞口 z 区间。
  # 这样天然无重叠、无缝隙，也不需要布尔运算。
  def slab_decomposition(wall_len, wall_h, openings)
    cuts = [0.0, wall_len.to_f]
    openings.each do |o|
      u0 = o['u'].to_f
      u1 = u0 + o['width'].to_f
      cuts << u0 << u1
    end
    cuts = cuts.map(&:to_f).uniq.sort
    slabs = []

    cuts.each_cons(2) do |a, b|
      next if (b - a).abs < 0.5 # 小于 0.5mm 的碎片忽略
      mid = (a + b) / 2.0
      # 覆盖这一段的洞口
      covering = openings.select do |o|
        u0 = o['u'].to_f
        u1 = u0 + o['width'].to_f
        mid > u0 && mid < u1
      end
      blocked = covering.map do |o|
        z0 = (o['sill'] || 0).to_f
        [z0, z0 + o['height'].to_f]
      end.sort
      # 从 [0, wall_h] 里挖掉 blocked，得到若干竖直区间
      cursor = 0.0
      blocked.each do |(z0, z1)|
        slabs << [a, b, cursor, z0] if z0 - cursor > 0.5
        cursor = [cursor, z1].max
      end
      slabs << [a, b, cursor, wall_h.to_f] if wall_h.to_f - cursor > 0.5
    end
    slabs
  end

  # 建一面墙（含洞口）。
  # wall = {
  #   "name" => "W1", "from" => [x,y], "to" => [x,y], "thickness" => 240, "height" => 2800,
  #   "base_z" => 0,
  #   "openings" => [ {"type"=>"door","u"=>900,"width"=>900,"height"=>2100,"sill"=>0}, ... ]
  # }
  #
  # 墙厚**居中于中心线**（from→to 是轴线）：这样无论墙朝哪个方向，
  # 结果都对称、不用纠结法线朝向。轴线两侧各偏 t/2。
  def build_wall(ents, wall)
    x0, y0 = wall['from'].map(&:to_f)
    x1, y1 = wall['to'].map(&:to_f)
    t = wall['thickness'].to_f
    h = wall['height'].to_f
    base_z = (wall['base_z'] || 0).to_f
    openings = wall['openings'] || []
    name = wall['name'] || 'W'

    dx = x1 - x0
    dy = y1 - y0
    len = Math.sqrt(dx * dx + dy * dy)
    raise "墙 #{name} 长度为 0" if len < 1

    ux = dx / len
    uy = dy / len
    # 墙厚方向的单位法向（逆时针 90°）
    nx = -uy
    ny = ux
    half = t / 2.0

    slabs = slab_decomposition(len, h, openings)
    raise "墙 #{name} 拆分后没有任何可建块（洞口是否覆盖了整面墙？）" if slabs.empty?

    built = []
    slabs.each_with_index do |(u0, u1, z0, z1), i|
      ax = x0 + ux * u0
      ay = y0 + uy * u0
      bx = x0 + ux * u1
      by = y0 + uy * u1
      g = box_on_ground(
        ents,
        ax + nx * half, ay + ny * half,
        bx - nx * half, by - ny * half,
        (z1 - z0),
        format('%s-%02d', name, i + 1),
        base_z + z0
      )
      built << g
    end

    top = built.map { |g| to_mm(g.bounds.max.z) }.max
    bottom = built.map { |g| to_mm(g.bounds.min.z) }.min
    expect_top = base_z + h
    warn = nil
    warn = "顶面 #{top}mm ≠ 期望 #{expect_top}mm" if (top - expect_top).abs > 1
    warn ||= "底面 #{bottom}mm ≠ 期望 #{base_z}mm" if (bottom - base_z).abs > 1

    # ── 门窗扇/框（opt-in："joinery": true 才建）
    joineries = []
    if wall['joinery']
      openings.each_with_index do |o, i|
        begin
          joineries << build_joinery(ents, x0, y0, ux, uy, nx, ny, t, o, name, i)
        rescue => e
          joineries << { name: "#{name}-#{o['label'] || i + 1}", error: "#{e.class}: #{e.message}" }
        end
      end
    end

    { name: name, slabs: slabs.length, length: len.round(1), openings: openings.length,
      top_mm: top, bottom_mm: bottom, warning: warn,
      joineries: joineries }
  end

  # ---------------------------------------------------------------- 房间
  #
  # rooms 原来只在 schema 里定义了、文档也承诺了"生成地面/天花"，但生成器里根本没实现
  # （搜不到 rooms/ceiling 任何一处）。这是文档与实现不符，现在补上。
  #
  # 设计取舍：房间**不**自动从墙推算轮廓，而是要求图纸/数据里明确给出 polygon。
  # 原因：自动从墙推开房间需要判断"哪面墙属于这个房间"，在墙相交、有洞口时容易出错；
  # 而我们已经有校验手段（下方 validate_room）来抓 room 与 wall 对不上的情况。

  def room_bounds(poly)
    xs = poly.map { |p| p[0].to_f }
    ys = poly.map { |p| p[1].to_f }
    { x0: xs.min, x1: xs.max, y0: ys.min, y1: ys.max }
  end

  def boxes_overlap?(a, b, tol = 0.5)
    !(a[:x1] <= b[:x0] + tol || b[:x1] <= a[:x0] + tol ||
      a[:y1] <= b[:y0] + tol || b[:y1] <= a[:y0] + tol)
  end

  # 校验房间轮廓是否与墙体自洽。这是"平面图与数据冲突就停下问用户"的落点。
  #
  # overlapping_with: 预先算好的"与哪些房间重叠"列表。必须传入——
  # 我第一版把它漏了，结果重叠的房间在逐项明细里被标成 ✅（问题只记在另一条警告里），
  # 这正是"指标说没问题、其实有问题"的老毛病。
  def validate_room(room, all_walls, overlapping_with = [])
    poly = room['polygon']
    return { ok: false, issues: ['缺少 polygon'], size_mm: nil } if poly.nil? || poly.length < 3

    b = room_bounds(poly)
    issues = []
    w = (b[:x1] - b[:x0])
    h = (b[:y1] - b[:y0])
    issues << "房间尺寸过小（#{w.round}×#{h.round}mm），可能读错" if w < 500 || h < 500

    unless overlapping_with.empty?
      issues << "与房间「#{overlapping_with.join('」「')}」的外接矩形重叠，请核对轮廓或隔墙位置"
    end

    # 与已有房间重叠？（重叠说明我读图时把两个房间的轮廓画错了）
    # 这里只检查自身是否自交（外轮廓的凹多边形不算错，所以不做凸性检查）
    if poly.length >= 4
      # 简易自交检查：任两条不相邻边是否相交
      edges = poly.each_with_index.map { |p, i| [p, poly[(i + 1) % poly.length]] }
      edges.each_with_index do |(a1, a2), i|
        edges.each_with_index do |(b1, b2), j|
          next if j <= i + 1 || (i == 0 && j == edges.length - 1)
          if segments_cross?(a1, a2, b1, b2)
            issues << "轮廓自交（第 #{i + 1} 段与第 #{j + 1} 段相交），请核对房间轮廓"
            break
          end
        end
        break if issues.any? { |s| s.include?('自交') }
      end
    end

    # 是否落在建筑外轮廓内（用所有墙的像素范围近似）
    unless all_walls.empty?
      wx = []
      wy = []
      all_walls.each do |w2|
        [w2['from'], w2['to']].each do |pt|
          wx << pt[0].to_f
          wy << pt[1].to_f
        end
      end
      pad = 200.0 # 允许房间贴到墙内侧，给 200mm 容差（墙厚/标注习惯）
      if b[:x0] < wx.min - pad || b[:x1] > wx.max + pad ||
         b[:y0] < wy.min - pad || b[:y1] > wy.max + pad
        issues << format('房间范围 (%.0f,%.0f)-(%.0f,%.0f) 超出建筑外轮廓 (%.0f,%.0f)-(%.0f,%.0f)',
                         b[:x0], b[:y0], b[:x1], b[:y1], wx.min, wy.min, wx.max, wy.max)
      end
    end

    { ok: issues.empty?, issues: issues,
      size_mm: [w.round(1), h.round(1)],
      min_mm: [b[:x0].round(1), b[:y0].round(1)],
      max_mm: [b[:x1].round(1), b[:y1].round(1)] }
  end

  def segments_cross?(a1, a2, b1, b2)
    d = lambda do |p, q, r|
      (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    end
    d1 = d.call(a1, a2, b1)
    d2 = d.call(a1, a2, b2)
    d3 = d.call(b1, b2, a1)
    d4 = d.call(b1, b2, a2)
    ((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) && ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0))
  end

  # 建一个房间：地面板 + 可选天花板。
  #
  # 为什么用"实体板"而不是零厚度平面（这是实测踩出来的）：
  #   在同一个组里先 add_face 地面、再 add_face 天花时，组的**世界 bounds 会被算错**
  #   （本地顶点是对的，但顶层组的 transformation 出错）：
  #       实验：地面 120..3440 × 4320..7880 正确
  #             同组内加天花后 → x=120..3560  y=4320..12200（被拉伸）
  #             把天花建成独立组 → 两个都正确
  #   实心板走的是 box_on_ground（已被大量验证的 pushpull 路径），既绕开这个问题，
  #   几何也更像真的楼板/天花。
  def build_room(ents, room, base_z = 0)
    poly = room['polygon']
    name = room['name'] || '房间'
    z = (room['base_z'] || base_z).to_f
    b = room_bounds(poly)
    t = (room['floor_thickness'] || 100).to_f
    ceiling = (room['ceiling_height'] || 0).to_f
    ct = (room['ceiling_thickness'] || 100).to_f

    parts = []
    # 地面板：**占 [z, z+t]**，也就是完成面在 z、板体在 z 以上（室内方向）。
    # 这里曾经写成 z - t，导致整块地板挂到地面以下 —— render 图上不易察觉，
    # 靠 check_geometry.py 逐个核对世界坐标才抓出来。
    parts << box_on_ground(ents, b[:x0], b[:y0], b[:x1], b[:y1], t,
                           "R-#{name}-地面", z)
    # 天花板：占 [z+ceiling, z+ceiling+ct]
    if ceiling > 0
      parts << box_on_ground(ents, b[:x0], b[:y0], b[:x1], b[:y1], ct,
                             "R-#{name}-天花", z + ceiling)
    end

    # 把这些板再收进一个同名父组，方便你在 SketchUp 里整体选中"这个房间"
    parent = ents.add_group(parts)
    parent.name = "R-#{name}"
    parent
  end

  # 建一个长方体，用**真实三维点**表达，因此轴对齐和斜交都能用。
  #
  # 参数：
  #   p0  = 长方体一角的底面点（世界坐标，毫米）
  #   ea  = "沿长度方向"的单位向量与长度  → [ex, ey, len]
  #   eb  = "沿厚度方向"的单位向量与厚度  → [ex, ey, th]
  #   z0, z1 = 底、顶标高（毫米）
  #
  # 四个底角 = p0, p0+ea, p0+ea+eb, p0+eb；沿 Z 推 (z1-z0)。
  # 推拉方向按面法线判断——这条规矩是被 pushpull 坑过之后定下的。
  def box_plate(ents, p0, ea, eb, z0, z1, name)
    ax, ay, alen = ea
    bx, by, blen = eb
    corners = [
      [p0[0], p0[1]],
      [p0[0] + ax * alen, p0[1] + ay * alen],
      [p0[0] + ax * alen + bx * blen, p0[1] + ay * alen + by * blen],
      [p0[0] + bx * blen, p0[1] + by * blen]
    ]
    pts = corners.map { |(x, y)| Geom::Point3d.new(mm(x), mm(y), mm(z0)) }
    face = ents.add_face(pts)
    raise "box_plate(#{name}) 无法成面：参数退化" if face.nil?
    g = ents.add_group(face)
    face.pushpull(face.normal.z >= 0 ? mm(z1 - z0) : -mm(z1 - z0))
    g.name = name
    g
  end

  # ---------------------------------------------------------------- 门窗扇/框
  #
  # 为什么这件事不是"可选装饰"：
  #   不做的話几何本身就是错的——窗洞只是墙上一个矩形缺口，没有玻璃；
  #   门洞直接透过去。而且门窗符号是读图时的**识别线索**（窗中线 vs 门开启弧）。
  #
  # 但按用户政策（"不做图外的东西、润色要用户发话"），
  # 所以做成 **opt-in**：墙数据里写 "joinery": true 才建，默认不建。

  JOINERY_STANDARD = { 'frame' => 60, 'glass' => 20, 'leaf' => 40, 'gap' => 20 }.freeze

  # 建一个洞口内的门/窗。
  #   cx, cy  = 墙轴线起点的世界坐标（毫米）
  #   ux, uy  = 沿墙长度方向的单位向量
  #   nx, ny  = 墙厚方向的单位向量
  #   t       = 墙厚
  # 返回 { kind:, name:, panels: } 之类的摘要，供报告使用。
  def build_joinery(ents, cx, cy, ux, uy, nx, ny, t, opening, wall_name, idx)
    o = opening
    type = (o['type'] || 'door').to_s
    u0 = o['u'].to_f
    width = o['width'].to_f
    sill = (o['sill'] || 0).to_f
    height = o['height'].to_f
    z0 = sill
    z1 = sill + height
    label = o['label'] || "#{type}#{idx + 1}"
    base = "#{wall_name}-#{label}"

    std = JOINERY_STANDARD.merge(o['joinery_spec'] || {})
    f = std['frame'].to_f          # 框料截面
    glass = std['glass'].to_f      # 玻璃厚
    leaf = std['leaf'].to_f        # 门扇厚
    gap = std['gap'].to_f          # 门扇底部离地/离框缝

    # 局部 (u, tc) → 世界平面坐标。
    # 基准点是墙体的 -t/2 侧（也就是 wall corner 起点），
    # 这样 tc=0 就是墙面一侧、tc=t 是另一侧，与"墙厚居中于轴线"一致。
    base_x = cx + nx * (-t / 2.0)
    base_y = cy + ny * (-t / 2.0)
    place = lambda { |u, tc| [base_x + ux * u + nx * tc, base_y + uy * u + ny * tc] }

    # 造一根料：u ∈ [a,b]，厚度方向 ∈ [ta,tb]，标高 ∈ [za,zb]
    member = lambda do |a, b, za, zb, ta, tb, name|
      p0 = place.call(a, ta)
      box_plate(ents, p0, [ux, uy, b - a], [nx, ny, tb - ta], za, zb, name)
    end

    panels = []
    # 两侧竖梃（门叫门框边梃）
    [[u0, u0 + f], [u0 + width - f, u0 + width]].each_with_index do |(a, b), k|
      panels << member.call(a, b, z0, z1, 0, t, "#{base}-框#{k + 1}")
    end
    # 上槛
    panels << member.call(u0, u0 + width, z1 - f, z1, 0, t, "#{base}-上槛")
    # 下槛：窗有，门没有（门要过人）
    if type == 'window'
      panels << member.call(u0, u0 + width, z0, z0 + f, 0, t, "#{base}-下槛")
    end

    if type == 'window'
      # 玻璃：居中于墙厚，四周离框各留 gap/2。
      # 高度基准用**框内开口**（上槛下沿 → 下槛上沿），不是洞口边。
      # 实测：框内开口 970×1200，玻璃正好 970×1200，四周 10mm —— 符合常见做法。
      tc = t / 2.0 - glass / 2.0
      p0 = place.call(u0 + f + gap / 2.0, tc)
      panels << box_plate(ents, p0,
                          [ux, uy, width - 2 * f - gap],
                          [nx, ny, glass],
                          z0 + f + gap / 2.0, z1 - f - gap / 2.0,
                          "#{base}-玻璃")
    else
      # 门扇：贴一侧，厚度 leaf。
      #
      # 踩过的坑：原来高度写成 `z0 + gap .. z1 - f - gap/2`，
      # 其中 z1 是**洞口顶**而不是**上槛下沿**，于是门扇顶上留了 70mm 的洞
      # （实测：门扇 z=20..2030，而上槛下沿在 2040）。
      # 正确基准是框内开口：上槛下沿 = z1 - f，门扇顶 = z1 - f - gap/2。
      tc = o['hinge_side'] == 'far' ? (t - leaf - gap) : gap
      p0 = place.call(u0 + f + gap / 2.0, tc)
      panels << box_plate(ents, p0,
                          [ux, uy, width - 2 * f - gap],
                          [nx, ny, leaf],
                          z0 + gap, z1 - f - gap / 2.0,
                          "#{base}-门扇")
    end

    { name: base, type: type, panels: panels.length, label: label,
      size: [width, height, sill] }
  end

  # ---------------------------------------------------------------- 转角处理
  #
  # 问题（用户指出的真缺陷）：墙厚**居中于轴线**时，两面成直角的外墙
  # 会在转角各缺一个 (t/2)² 的空洞，从外侧能看见一个方槽。
  # 实测证据（修之前）：
  #     南墙 x=0..6000，西墙 x=-120..120  →  西南角 (-120,-120) 被 0 面墙覆盖
  #     四个角全部如此。
  #
  # 修法：把墙在**与其他墙相接**的端部沿轴线延伸半个自身墙厚。
  #   · 只在"确有别的墙接在这里"时才延伸，避免无谓地把墙捅出去
  #   · 延伸后相邻两墙在转角互相搭接，外表面连续，内部也无缝
  #     （两端各延伸半厚 ⇒ 合计恰好覆盖到外角，是标准的 L 形接头）
  #   · 用户明确说"要么做重叠、要么好好算好严丝合缝都行"——这里两者都满足：
  #     接头处有搭接（实体意义上无缝），而外轮廓精确。

  def point_seg_distance(px, py, ax, ay, bx, by)
    dx = bx - ax
    dy = by - ay
    len2 = dx * dx + dy * dy
    return Math.sqrt((px - ax)**2 + (py - ay)**2) if len2 < 1e-9
    t = ((px - ax) * dx + (py - ay) * dy) / len2
    t = 0.0 if t < 0
    t = 1.0 if t > 1
    Math.sqrt((px - (ax + dx * t))**2 + (py - (ay + dy * t))**2)
  end

  # 返回每面墙在 from/to 两端各应延伸多少毫米。
  #
  # 判据：**该端点到其它墙轴线的距离**，若落在对方体内（距离 ≤ 对方半厚 + tol），
  # 就把这一端延伸到对方外皮（即延伸对方半厚）。再与自身半厚取 max。
  #
  # 为什么不用"point_seg_distance <= tol 就算相接"：
  # 实测那个函数在角部会返回 25（正确答案 4775），判据不可靠；
  # 而且角上两端点本来就几乎重合，"相接"会把不需要延伸的也算进来。
  # 这里自己算点到线段的距离，不依赖它。
  def wall_end_extensions(walls, tol = 60.0)
    # 点到线段最短距离（自算，不用 point_seg_distance）
    dist = lambda do |px, py, ax, ay, bx, by|
      vx = bx - ax
      vy = by - ay
      ll = vx * vx + vy * vy
      t = ll < 1e-9 ? 0.0 : ((px - ax) * vx + (py - ay) * vy) / ll
      t = 0.0 if t < 0.0
      t = 1.0 if t > 1.0
      cx = ax + t * vx
      cy = ay + t * vy
      Math.sqrt((px - cx)**2 + (py - cy)**2)
    end

    walls.map { |_w| [0.0, 0.0] }.tap do |ext|
      walls.each_with_index do |w, i|
        t = w['thickness'].to_f
        [[w['from'], 0], [w['to'], 1]].each do |pt, which|
          px = pt[0].to_f
          py = pt[1].to_f
          reach = 0.0
          walls.each_with_index do |o, j|
            next if j == i
            h_o = o['thickness'].to_f / 2.0
            d = dist.call(px, py, o['from'][0].to_f, o['from'][1].to_f,
                           o['to'][0].to_f, o['to'][1].to_f)
            # 该端点落在对方体内（含容差）→ 至少要够到对方外皮
            reach = [reach, h_o].max if d <= h_o + tol
          end
          ext[i][which] = [t / 2.0, reach].max
        end
      end
    end
  end

  # 按延伸量改出新的 from/to（不改原数据）。
  #
  # ⚠️ 关键：洞口用的是**沿墙局部坐标 u**（从 from 端量起）。
  # 延伸把 from 端点往外挪了 ext_from，如果不同步平移 u，
  # **门窗会跟着墙一起漂**。
  # 实测踩过：南墙 from 端延伸 120mm 后，入户门框跑到 x=1080..1140
  # （数据声明洞口在 1200..2200），客厅窗同样偏了 −120。
  # 门窗位置错比转角缺口严重得多，所以这里必须同步补偿。
  def wall_with_extensions(w, ext_from, ext_to)
    x0, y0 = w['from'].map(&:to_f)
    x1, y1 = w['to'].map(&:to_f)
    len = Math.sqrt((x1 - x0)**2 + (y1 - y0)**2)
    return w.dup if len < 1e-6
    ux = (x1 - x0) / len
    uy = (y1 - y0) / len
    nw = w.dup
    nw['from'] = [x0 - ux * ext_from, y0 - uy * ext_from]
    nw['to'] = [x1 + ux * ext_to, y1 + uy * ext_to]
    nw['_extended'] = [ext_from.round(1), ext_to.round(1)]
    # 洞口 u 同步平移：from 端外移多少，u 就加多少
    if ext_from.abs > 0.01 && w['openings'].is_a?(Array)
      nw['openings'] = w['openings'].map do |o|
        o2 = o.dup
        o2['u'] = (o['u'].to_f + ext_from)
        o2['_u_shifted'] = ext_from.round(1)
        o2
      end
    end
    nw
  end

  # ---------------------------------------------------------------- 楼梯
  #
  # 表示法：楼梯间按轴线描述——起点、走向、宽度、总高、踏步数。
  # 每一级踏步是**一级台阶板**，从地面一直长到该级顶面（不是薄薄一片踏板），
  # 这样各级自然堆叠成实心梯段，不需要布尔运算，也不会有悬空面。
  #
  # 关键推导（riser/tread 一律从数据推，不写死假设）：
  #   rise  = 总高 / 踏步数
  #   tread = 水平投影长 / 踏步数
  # 如果数据里同时给了总高和踏步数，我按它们算 rise；
  # 若还给了 target_riser，则核对差值并在偏差过大时报警——**不偷偷改数据**。

  def stair_geometry(s)
    h = s['height'].to_f                       # 总高（层高）
    width = (s['width'] || 900).to_f
    warnings = []

    # ── 双跑（带休息平台）
    #
    # 什么时候需要它：单跑按住宅踏面宽 260 算，需要 n×260 + 起步平台 900 的沿墙长度；
    # 现场放不下时就得折返。实测踩过：6×8m 住宅扣掉门洞只剩 3560mm，
    # 16 级单跑需要约 5060mm —— 根本放不下。
    #
    # 堆叠规则（避免穿模，这是关键）：
    #   · 第一跑占用 [0, 1×h1] 的竖向区间（各级从地面长起，是实心梯段）
    #   · 平台占用 [h1, h1+landing_t]（**坐在第一跑顶面上**，不是与之同高）
    #   · 第二跑从 h1+landing_t 起，逐级到 H
    # 第一跑一级、平台、第二跑之间的竖向关系因此不重叠。
    if s['flights'].is_a?(Array) && !s['flights'].empty?
      fl = s['flights']
      # 踏步数 = **所有**跑的级数之和，不是"前两跑"。
      # 踩过的坑：原来写 `n = n1 + n2`，四跑时只算 4 级 → rise = 2800/4 = 350，
      # 总高变成 6050（应为 2800）。
      n = fl.reduce(0) { |acc, f| acc + (f['steps'] || 0).to_i }
      raise '楼梯 flights[0] 缺少 steps' if (fl[0]['steps'] || 0).to_i < 1
      lt = ((s['landing'] || {})['thickness'] || 150).to_f
      ld = ((s['landing'] || {})['depth'] || width).to_f
      # 唯一自洽的竖向关系：
      #     H = Σ(各级踏面高) + (跑数−1) × 平台厚
      # 因为平台在剖面上是"插入"的实体，它必然占掉总高的一部分。
      # 所以 踏面高 = (H − 平台厚×(跑数−1)) / 总级数，末级正好到 H。
      #
      # 踩过的坑：我先后试过 rise = H/n（末级差一个平台厚）、
      # 以及把平台顶面放在 arrive 处（多出一个平台厚），两种都不自洽。
      # 这条关系一写出来，两跑和四跑同时对。
      n_land = fl.length - 1
      rise = (h - lt * n_land) / n
      warnings << format('平台厚度占去 %.0fmm，调整后踏面高 %.1fmm', lt * n_land, rise) if n_land > 0
      treads = fl.map { |f|
        s_i = (f['steps'] || 0).to_i
        s_i > 0 ? ((f['run'] || 0).to_f / s_i) : 0
      }
      treads.each_with_index do |td, i|
        warnings << format('第 %d 跑踏面宽 %.1fmm 偏窄（建议 ≥260mm）', i + 1, td) if td > 0 && td < 260
      end
      warnings << format('踏面高 %.1fmm 偏大（建议 ≤180mm）', rise) if rise > 200
      return { rise: rise, steps: n, width: width, warnings: warnings,
               mode: 'multi_flight', flights: fl.length,
               n1: (fl[0]['steps'] || 0).to_i,
               n2: (fl[1] ? (fl[1]['steps'] || 0).to_i : 0),
               rise1: 0, landing_t: lt, landing_d: ld,
               tread1: treads[0] || 0, tread2: treads[1] || 0,
               run1: (fl[0]['run'] || 0).to_f,
               run2: (fl[1] ? (fl[1]['run'] || 0).to_f : 0),
               total_run: fl.reduce(0.0) { |a, f| a + (f['run'] || 0).to_f } + ld * (fl.length - 1) }
    end

    n = (s['steps'] || 0).to_i                 # 踏步数（级数）
    raise '楼梯缺少 steps（踏步数）' if n < 1
    run = (s['run'] || 0).to_f                 # 水平投影总长
    tread = run > 0 ? run / n : (s['tread'] || 280).to_f
    run = tread * n if run <= 0
    rise = h / n

    if s['target_riser']
      tr = s['target_riser'].to_f
      if (rise - tr).abs > 10
        warnings << format('实际踏面高 %.1fmm 与目标 %.1fmm 差 %.1fmm（踏步数 %d 定死了层高分配）',
                           rise, tr, (rise - tr).abs, n)
      end
    end
    warnings << format('踏面高 %.1fmm 偏大（住宅建议 ≤180mm），可增加踏步数', rise) if rise > 200
    if tread < 260
      warnings << format(
        '踏面宽 %.1fmm 偏窄（住宅建议 ≥260mm）。' \
        '单跑楼梯要满足此宽度需要 %d 级 × 260 + 起步平台 900 ≈ %dmm 的沿墙长度；' \
        '若现场放不下，请改用**双跑**：在 stairs 里加 flights + landing，' \
        '例如 "flights": [{"steps": %d, "run": %d}, {"steps": %d, "run": %d}]',
        tread, n, n * 260 + 900, (n / 2.0).ceil, ((n / 2.0).ceil * 260).to_i,
        (n / 2.0).floor, ((n / 2.0).floor * 260).to_i
      )
    end

    # 最小净高检查：最后一级上方是否还有足够空间（粗略：总高 - 一级）
    { rise: rise, tread: tread, run: run, width: width, steps: n,
      mode: 'single', warnings: warnings }
  end

  # 建楼梯。局部坐标：u 沿走向，v 沿梯段宽度，z 为标高（全部毫米）。
  #   {"name","from":[x,y],"to":[x,y],"width","height","steps","run",
  #    "target_riser","material"}
  def build_stair(ents, s)
    name = s['name'] || 'ST'
    x0, y0 = s['from'].map(&:to_f)
    x1, y1 = s['to'].map(&:to_f)
    dx = x1 - x0
    dy = y1 - y0
    len = Math.sqrt(dx * dx + dy * dy)
    raise "楼梯 #{name} 的 from/to 长度为 0" if len < 1
    ux = dx / len
    uy = dy / len
    # 梯段宽度方向（逆时针 90°）
    vx = -uy
    vy = ux

    g = stair_geometry(s)
    width = g[:width]
    made = []

    # 一共几跑/几块平台：
    #   · 双跑（"flights" + "landing"）→ 2 段梯跑 + 1 块平台
    #   · 四跑等价拆分（"flights" 给 4 条）→ 4 段梯跑 + 3 块平台
    #     用它表达双跑的好处：**"中间梯段承接上一跑"是数据结构本身说的**，
    #     而不是我加的隐式参数（我上一版就是这么干的，写成了承接上一级的顶面）。
    # 两条路径共用同一段循环代码，所以规则只写一次。
    flights = s['flights'].is_a?(Array) && !s['flights'].empty? ? s['flights'] : nil
    n_seg = flights ? flights.length : 1
    n_land = n_seg - 1

    if flights
      lt = ((s['landing'] || {})['thickness'] || 150).to_f
      ld = ((s['landing'] || {})['depth'] || width).to_f
      slab_t = [g[:rise], 150].max
      along = 1                        # 沿 ux/uy 的正向
      base = 0.0
      cursor_x = x0
      cursor_y = y0

      flights.each_with_index do |f, si|
        n_i = (f['steps'] || 0).to_i
        t_i = n_i > 0 ? (f['run'] || 0).to_f / n_i : 0
        t_i = (f['tread'] || 280).to_f if t_i <= 0
        last = (si == flights.length - 1)

        # 本跑的起点标高由上文给出（首跑为 0；之后每跑 = 上一跑到达标高 − 平台厚），
        # 到达标高 = 起点 + 级数 × 踏面高。
        #
        # 平台"嵌入总高之内"：平台顶面 = 本跑到达标高，下一跑从 arrive − lt 起，
        # 所以平台厚度**不会**被加进总高。
        #
        # 踩过的坑：我先写成 start = arrive - (last ? 0 : lt)，
        # 而 base 里已经扣过一次，于是又扣一遍 —— 第二跑从 2600 起，
        # 末级顶面飙到 4200（目标 2800）。**同一件事扣两次**。
        arrive = base + n_i * g[:rise]

        n_i.times do |i|
          z_top = base + (i + 1) * g[:rise]
          # 第一级的板底不能低于本跑起点：
          # 板厚取 max(踏面高, 150)，当踏面高小于 150 时（四跑时 146.9），
          # 第一级板底会落到起点以下（实测 −3.1mm）。
          z_bot = [z_top - slab_t, base].max
          sx = cursor_x + ux * along * (i * t_i)
          sy = cursor_y + uy * along * (i * t_i)
          box_plate(ents, [sx, sy], [ux * along, uy * along, t_i], [vx, vy, width],
                    z_bot, z_top,
                    format('%s-%d-%02d', name, si + 1, i + 1))
          made << z_top
        end

        cursor_x += ux * along * (n_i * t_i)
        cursor_y += uy * along * (n_i * t_i)

        if !last
          # 平台：底面在本跑到达标高，板体向上（下一跑从它的顶面起）
          # 于是 arrive_next = arrive + lt，正好补上被平台占掉的那一段高度。
          box_plate(ents, [cursor_x, cursor_y], [ux, uy, ld], [vx, vy, width],
                    arrive, arrive + lt, format('%s-平台%d', name, si + 1))
          made << (arrive + lt)
          cursor_x += ux * ld
          cursor_y += uy * ld
          along = -along
          base = arrive + lt
        else
          base = arrive
        end
      end

      total_steps = flights.reduce(0) { |acc, f| acc + (f['steps'] || 0).to_i }
      total_run = flights.reduce(0.0) { |acc, f| acc + (f['run'] || 0).to_f } +
                  ld * (flights.length - 1)
      return { name: name, mode: (n_seg == 2 ? 'two_flight' : "#{n_seg}_flight"),
               steps: total_steps,
               rise: g[:rise].round(1),
               tread1: (flights[0]['run'].to_f / flights[0]['steps']).round(1),
               tread2: (flights[1] ? (flights[1]['run'].to_f / flights[1]['steps']).round(1) : nil),
               width: width, run: total_run.round(1),
               height: made.max.round(1),
               pieces: made.length, warnings: g[:warnings] }
    end

    # ── 单跑
    g[:steps].times do |i|
      u_a = i * g[:tread]
      u_b = (i + 1) * g[:tread]
      z_top = (i + 1) * g[:rise]
      p0 = [x0 + ux * u_a, y0 + uy * u_a]        # 级前缘
      box_plate(ents, p0,
                [ux, uy, u_b - u_a],             # 沿走向
                [vx, vy, width],                 # 沿梯宽
                0, z_top,                        # 从地面长到该级顶面
                format('%s-%02d', name, i + 1))
      made << z_top
    end

    { name: name, mode: 'single', steps: g[:steps], rise: g[:rise].round(1),
      tread: g[:tread].round(1),
      width: width, run: g[:run].round(1), height: (g[:steps] * g[:rise]).round(1),
      warnings: g[:warnings], pieces: made.length }
  end

  # ---------------------------------------------------------------- 楼板

  # 把"带洞的矩形"拆成**若干无重叠矩形**（不用布尔运算）。
  #
  # 为什么需要：采光中庭、楼梯井这类地方楼板是空的。
  # 原来的 build_floor 只取 polygon 的包围盒，会把洞填实。
  #
  # 算法：把所有洞口的 y 边界当切线 → 切成若干水平带；
  #       每带内按洞口的 x 区间再切 → 得到实心矩形。
  # 这个思路和墙体开洞的 slab_decomposition 是同一套，已被反复验证。
  def floor_with_holes(x0, y0, x1, y1, holes)
    hs = Array(holes).map do |h|
      [h['x0'].to_f, h['y0'].to_f, h['x1'].to_f, h['y1'].to_f]
    end.reject { |a, b, c, d| c <= x0 || a >= x1 || d <= y0 || b >= y1 }
    return [[x0, y0, x1, y1]] if hs.empty?

    ys = ([y0, y1] + hs.flat_map { |_, b, _, d| [b, d] })
         .select { |v| v >= y0 - 1e-6 && v <= y1 + 1e-6 }.sort.uniq
    out = []
    ys.each_cons(2) do |ya, yb|
      next if yb - ya < 1e-6
      mid = (ya + yb) / 2.0
      # 该带内横跨的洞
      xs = ([x0, x1] + hs.select { |_, b, _, d| b <= mid && mid <= d }
                          .flat_map { |a, _, c, _| [a, c] })
           .select { |v| v >= x0 - 1e-6 && v <= x1 + 1e-6 }.sort.uniq
      xs.each_cons(2) do |xa, xb|
        next if xb - xa < 1e-6
        mx = (xa + xb) / 2.0
        inside = hs.any? { |a, b, c, d| a <= mx && mx <= c && b <= mid && mid <= d }
        out << [xa, ya, xb, yb] unless inside
      end
    end
    out
  end

  def build_floor(ents, slab, grouped: true)
    name = slab['name'] || 'F'
    poly = slab['polygon']
    z = (slab['z'] || 0).to_f
    raise "楼板 #{name} 缺少 polygon" if poly.nil? || poly.length < 3
    th = (slab['thickness'] || 0).to_f
    b = room_bounds(poly)
    holes = Array(slab['holes'])

    # ── 推荐做法：**轮廓推拉，一次成型**
    #
    # 用户要求"大整体要分组、要用推拉，不能一个一个建盒子堆出来"。
    # 老做法（下面那段）把带洞楼板拆成多个矩形平铺成 F-板-01/02/03/04，
    # 组数多、接缝多。现在合成一个实体：
    #   外轮廓 = 楼板底面矩形，洞 = slab['holes']，一次 add_face + pushpull
    #
    # ⚠️ 老做法里有个**静默失败**的坑：为把多块塞进一个母组用了 `move_to`，
    # 结果母组建出来了但里面是空的（实测"子组 0 个"）。
    # 轮廓推拉从根上避免了这个问题 —— 只有一个实体，不需要母组。
    if grouped && th > 0 && defined?(DshParts)
      begin
        rects = if holes.any?
                  hh = holes.map { |h| [h[0].to_f, h[1].to_f, h[2].to_f, h[3].to_f] }
                  [[b[:x0], b[:y0], hh[0][0], b[:y1]],
                   [hh[0][2], b[:y0], b[:x1], b[:y1]],
                   [hh[0][0], b[:y0], hh[0][2], hh[0][1]],
                   [hh[0][0], hh[0][3], hh[0][2], b[:y1]]]
                else
                  [[b[:x0], b[:y0], b[:x1], b[:y1]]]
                end
        r = DshParts.extrude_profile(ents, name, rects, z, th)
        if r[:group]
          want = DshParts.rect_area(rects) / 1e6 * th / 1000.0
          r[:group].set_attribute('dsh', 'self_check', format('%.4f/%.4f', r[:volume_m3].to_f, want))
          return r[:group]
        end
        warn_floor = "楼板 #{name} 轮廓推拉失败（#{r[:error]}），回退到逐块做法"
      rescue StandardError => e
        warn_floor = "楼板 #{name} 轮廓推拉异常（#{e.class}），回退到逐块做法"
      end
    end

    # ── 老做法（回退用）：拆成无重叠矩形，逐个建
    if holes.any?
      rects = floor_with_holes(b[:x0], b[:y0], b[:x1], b[:y1], holes)
      if rects.length == 1
        box_on_ground(ents, rects[0][0], rects[0][1], rects[0][2], rects[0][3],
                      th, name, z)
      else
        # 多个矩形 → **平铺**成同名的兄弟组（F-板-01 / F-板-02 …）。
        #
        # 为什么不套一个母组：我试过 `sub.move_to(parent)`，**它静默失败**——
        # 母组建出来了但里面是空的（实测"子组 0 个"），地板只剩第一块。
        # 项目里也没有别处用过 move_to，没有先例可循。
        # 平铺符合项目一贯的顶层组结构，`check_geometry.py` 也能逐个核对。
        #
        # ⚠️ 教训：**静默失败比报错危险**。这里如果不去量总面积，
        # 就会以为"带洞地板做成了"，其实只做了一块。
        first = nil
        rects.each_with_index do |(rx0, ry0, rx1, ry1), i|
          sub = box_on_ground(ents, rx0, ry0, rx1, ry1, th,
                              "#{name}-#{format('%02d', i + 1)}", z)
          first ||= sub
        end
        first
      end
    elsif th > 0
      # 用 box_on_ground：方向由法线判断统一处理，不会像直接 pushpull 那样
      # 可能把板推到 z 以下（我第一版就是这样，F1-地板 长到了 z=-100）。
      #
      # 关于标高语义：楼板**顶面在 z**（z 就是楼面完成面标高），板体向"室内方向"长，
      # 也就是 z..z+th。早先写成 z-th 会让整块地板挂在地面以下 —— 那只是把错误
      # 从 z=-100 换个方向，仍然是错的。
      box_on_ground(ents, b[:x0], b[:y0], b[:x1], b[:y1], th, name, z)
    else
      pts = poly.map { |p| Geom::Point3d.new(mm(p[0]), mm(p[1]), mm(z)) }
      face = ents.add_face(pts)
      raise "楼板 #{name} 无法成面（点可能共线或自交）" if face.nil?
      g = ents.add_group(face)
      g.name = name
      g
    end
  end

  # ---------------------------------------------------------------- 疑问清单
  #
  # 这一块是"遇到不确定就问用户"的**自动化落点**。
  # 规则（来自工作政策.md）：
  #   source: "dim"     = 图上直接标注 → 不用问
  #   source: "derived" = 数学推算     → 附上算式让用户核一眼
  #   source: "assumed" = 我按常规假定 → 必须问
  #   没有 source 字段的 → 视为"没交代来源"，也要问（不能默默当成已确认）
  #   confidence: "low"/"medium" → 必须问
  #
  # 输出是给用户看的清单，每条都带上"我的推测答案"，让他能一句话确认。
  def questions_for(data)
    qs = []

    # 屋面形式：按工作政策必须问，绝不自选。
    # roof 可以是单个对象或数组；数组时逐个检查。
    rf_list = data['roof'].is_a?(Array) ? data['roof'] : [data['roof']]
    if data['roof'].nil?
      qs << { at: '屋顶', why: '你没有给屋顶图纸，我也不替你选形式',
              ask: '屋顶要做哪种形式？平屋顶 / 单坡（shed）/ 双坡（gable）/ 四坡（hip）？' \
                   '坡屋顶还需要坡度和屋脊方向（我可以按坡度比、度数或百分比接收）' }
    end
    rf_list.compact.each do |rf|
      next unless rf.is_a?(Hash)
      if rf['form'].nil?
        qs << { at: "屋顶 #{rf['name'] || ''}".strip, why: '数据里给了 roof 但没写 form',
                ask: '屋顶形式是什么？（flat / shed / gable / hip）' }
        next
      end
      next unless rf['source'] == 'assumed' || rf['confidence'] == 'low' || rf['pitch'].nil?

      why = [rf['source'] == 'assumed' ? '我按常规做法假定' : nil,
             rf['confidence'] == 'low' ? '置信度低，我没把握' : nil,
             rf['pitch'].nil? && rf['form'] != 'flat' ? '坡度是我取的默认 30°' : nil].compact
      why << '没有标注尺寸来源' if rf['source'].nil? && rf['confidence'].nil?
      qs << { at: "屋顶 #{rf['name'] || rf['form']}",
              why: why.join('；'),
              ask: "屋顶形式取 #{rf['form']}#{rf['pitch'] ? "、坡度 #{rf['pitch']}" : ''}，" \
                   '请确认形式、坡度与屋脊方向' }
    end

    # 统一的"来源/置信度"判断。任何构件都走这一条，避免漏掉某一类
    # （我加 elevations 时就漏过一次：立面的 assumed 项没进清单）。
    #
    # `skip_derived`：source=derived 时**是否单独构成一条问题**。
    # 为什么要这个开关：对**洞口**来说"这是我推算的 + 推算依据"值得让用户核对
    # （宽度确实可能量偏）；但对**墙**来说，"墙线位置由探针测得、墙厚由你给定"
    # 这句话**不构成用户能回答的问题**——他只能核对数值，
    # 而数值已经写在标题里了。实测：4 面外墙各生成一条"我推算出来的"，
    # 疑问清单从 4 条有用的膨胀到 8 条，其中 4 条是纯噪声。
    # 噪声会稀释注意力，让我真正想问的那几条（洞口宽度、合并警告）被淹没。
    ask_source = lambda do |item, at, ask_default, skip_derived = false|
      why = []
      if item['source'].nil?
        why << '没有标注尺寸来源'
      elsif item['source'] == 'assumed'
        why << '我按常规做法假定'
      elsif item['source'] == 'derived' && !skip_derived
        why << '我推算出来的'
      end
      why << '置信度低，我没把握' if item['confidence'] == 'low'
      # 洞口类型判别的结论也让用户过一眼：
      #   · 判为窗（洞口内有贯穿线，有正向证据）→ 让用户确认窗高/窗台高
      #   · 判为门（没有窗的线特征）→ 门与净洞口在图像层面无法区分，必须问
      if item['cross_lines']
        why << (item['type'] == 'window' ?
                "判为窗（洞口内 #{item['cross_lines']} 条贯穿线）" :
                "判为门，但门与净洞口无法区分（洞口内只有 #{item['cross_lines']} 条线）")
      end
      return nil if why.empty?
      ask = if item['confidence'] == 'low' && item['note']
              item['note']
            elsif item['basis']
              "推算依据：#{item['basis']}"
            elsif item['note']
              "取值依据：#{item['note']}"
            else
              ask_default
            end
      { at: at, why: why.join('；'), ask: ask }
    end

    # 把一条洞口规格写成用户能直接核对的短句（带具体数值）。
    # **只放数值**——长说明属于"为什么问"和"怎么回答"，挤在标题里会难读。
    opening_spec = lambda do |o|
      parts = []
      parts << "宽 #{o['width']}" if o['width']
      parts << "高 #{o['height']}" if o['height']
      parts << (o['sill'].to_f.zero? ? '落地' : "窗台高 #{o['sill']}") if o.key?('sill')
      parts.join('、')
    end

    # 墙厚问题按**厚度值**合并：同一厚度的墙只问一次，并列出涉及哪些墙。
    #
    # 为什么要合并：4 面墙各问一次"墙厚 240 对吗？"就是 4 条重复问题，
    # 而用户只需回答一次。噪声会稀释注意力。
    # （同时也说明为什么不能简单 `uniq`——问题的 at 里带墙名，所以 4 条的
    #  at 各不相同，uniq 去不掉。必须按**内容**合并。）
    thickness_groups = {}
    height_groups = {}

    (data['walls'] || []).each do |w|
      loc = "墙 #{w['name']}"
      # 墙的"来源=derived"不单独构成问题（依据已写在数据里，
      # 用户无法回答"是不是推算的"，只能核对数值）。
      # 但 **skip_derived 不等于不问墙厚**——墙厚不可量图（误差 5~10%），
      # 数值必须让用户确认。所以这里用一条**有针对性的**问题。
      #
      # 踩过：我一开始把 skip_derived 一路传下去，连墙厚确认也删掉了，
      # 是 `verify_flow.py` 里"疑问清单提到了墙厚"这条断言把它抓出来的。
      # **依据的来源**和**数值的核对**是两件事，不能一起删。
      #
      # ⚠️ 但**数据来源不同，该问的问题也不同**：
      #   · 从照片/截图量的 → 墙厚只占 9~20px，误差 5~10%，**必须问**
      #   · 从 CAD（DXF/DWG）读的 → 坐标是精确值，墙厚是**读出来的**，不用问
      # 我一开始没区分，于是拿"量图误差 5~10%"去质疑一个 DXF 精确读出的 50mm，
      # 那条质问在 CAD 场景下是**错误信息**，会让人以为我不确定。
      # 判据用 `basis` 里是否提到 CAD/DXF/DWG。
      from_cad = (w['basis'].to_s =~ /dxf|dwg|cad|实体几何/i)
      if w['thickness'] && !from_cad
        key = w['thickness'].to_f.round(1)
        (thickness_groups[key] ||= []) << w['name']
      end
      q = ask_source.call(w, "#{loc}（墙厚 #{w['thickness']}、墙高 #{w['height']}）",
                          "请确认墙厚 #{w['thickness']}、墙高 #{w['height']}", true)
      qs << q if q

      # 墙高：图上几乎不会标，是"假定"级别，**必须问**
      if w['height']
        hkey = w['height'].to_f.round(1)
        (height_groups[hkey] ||= []) << w['name']
      end

      # 每个洞口只问一次：来源问题与置信度问题合并，避免同一处被问两遍
      (w['openings'] || []).each_with_index do |o, i|
        label = o['label'] || "#{o['type']}##{i + 1}"
        q = ask_source.call(o, "#{loc} / #{label}（#{opening_spec.call(o)}）", '请核对以上几个数值')
        qs << q if q
      end
    end

# 墙高：平面图上**不会标注**墙高（那属立面/剖面信息），所以它是"假定"级别。
# 按高度值合并后问一次，别每面墙问一遍。
height_groups.sort_by { |h, _| -h }.each do |h, names|
  qs.unshift(
    at: "墙高 #{h}mm（涉及 #{names.length} 面墙）",
    why: '墙高在平面图上**不会标注**（属立面/剖面信息），这个数是我按常规取的',
    ask: "墙高取 #{h}mm 对吗？如果图纸有层高标注，请告诉我实际值"
  )
end

    # 墙厚问题（合并后）插到最前面——它是最该先确认的一项
    thickness_groups.sort_by { |th, _| -th }.each do |th, names|
      qs.unshift(
        at: "墙厚 #{th}mm（涉及 #{names.length} 面墙：#{names.join('、')}）",
        why: '墙厚在图上只占 9~20px，量图的相对误差 5~10%，我**不量它**；' \
             '这个数是你给的，但我想让你再确认一次',
        ask: "墙厚取 #{th}mm 对吗？（外墙与内墙若不同，请分别给出）"
      )
    end

    # 立面轮廓也要走同一套判断
    (data['elevations'] || []).each do |el|
      zs = Array(el['profile']).map { |pt| pt[1].to_f }
      zr = zs.empty? ? '标高未知' : "标高 #{zs.min.round}..#{zs.max.round}"
      at = "立面 #{el['name']}（挂 #{el['wall'] || '独立定位'}，#{zr}，厚 #{el['thickness']}）"
      q = ask_source.call(el, at, '请核对立面轮廓的坐标')
      qs << q if q
    end

    (data['rooms'] || []).each do |r|
      next if r['source']
      b = r['polygon'] ? room_bounds(r['polygon']) : nil
      size = b ? "#{(b[:x1] - b[:x0]).round}×#{(b[:y1] - b[:y0]).round}mm" : '尺寸未知'
      qs << { at: "房间 #{r['name']}（#{size}）", why: '没有标注来源',
              ask: '这间房的轮廓和名称是我从图上读的，请核对' }
    end

    # 去重（同一处可能同时命中"来源"与"置信度"两条规则）
    qs.uniq { |q| [q[:at], q[:why]] }
  end

  # ---------------------------------------------------------------- 立面轮廓
  #
  # 立面图**不产生独立实体**，它给的是"竖向轮廓"：墙从哪到哪、女儿墙多高、
  # 女儿墙内退多少、坡屋顶的斜线怎么走、雨棚板在哪一层。
  #
  # 表示法：把立面画成一个**剖面多边形**，坐标是 (u, z)：
  #   u = 沿基准墙轴线方向的距离（毫米），z = 标高（毫米）
  # 然后沿墙厚方向 extrude 一个厚度，就得到三维体。
  #
  # 有洞口的立面（比如山墙上开窗）用**两圈**表示：外圈 + 洞口圈，
  # SketchUp 的 add_face 会自动按奇偶规则挖掉内圈。
  #
  # 为什么不做弧线/自由曲线：图纸上的立面线脚通常是直线段组成的，
  # 先把直线做扎实；曲线等真正遇到再谈，不提前猜需求。

  # 关闭多边形（首尾相同则去掉重复点）
  def normalize_profile(profile)
    pts = Array(profile).map { |p| [p[0].to_f, p[1].to_f] }
    pts.pop if pts.length > 1 &&
               (pts.first[0] - pts.last[0]).abs < 0.01 &&
               (pts.first[1] - pts.last[1]).abs < 0.01
    pts
  end

  # 鞋带公式算有向面积（判断点序，用于把外圈统一成同一方向）
  def signed_area(pts)
    s = 0.0
    pts.each_with_index do |(x1, y1), i|
      x2, y2 = pts[(i + 1) % pts.length]
      s += (x1 * y2 - x2 * y1)
    end
    s / 2.0
  end

  def profile_bbox(pts)
    xs = pts.map { |p| p[0] }
    zs = pts.map { |p| p[1] }
    { u0: xs.min, u1: xs.max, z0: zs.min, z1: zs.max }
  end

  # 建一个立面轮廓体。
  # e = { "name", "wall"（基准墙名）或 "origin"/"direction"，"thickness", "profile" }
  def build_elevation(ents, e, walls_by_name)
    name = e['name'] || 'E'
    prof = normalize_profile(e['profile'])
    raise "立面 #{name} 的 profile 至少需要 3 个点" if prof.length < 3

    th = e['thickness'].to_f
    raise "立面 #{name} 缺少 thickness（沿墙厚的拉伸厚度）" if th <= 0

    # 定位：优先挂在某面墙上（继承它的轴线与厚度方向）
    if e['wall']
      w = walls_by_name[e['wall']]
      raise "立面 #{name} 引用了不存在的墙 #{e['wall']}" if w.nil?
      x0, y0 = w['from'].map(&:to_f)
      x1, y1 = w['to'].map(&:to_f)
      len = Math.sqrt((x1 - x0)**2 + (y1 - y0)**2)
      ux = (x1 - x0) / len
      uy = (y1 - y0) / len
      # 厚度方向
      nx = -uy
      ny = ux
      # 默认从轴线向 -n 侧偏半个厚度，使轮廓体**居中于墙轴线**
      off = (e['offset'] || (-th / 2.0)).to_f
      base_x = x0 + nx * off
      base_y = y0 + ny * off
    else
      base_x, base_y = (e['origin'] || [0, 0]).map(&:to_f)
      d = e['direction'] || [1, 0]
      dl = Math.sqrt(d[0]**2 + d[1]**2)
      raise "立面 #{name} 的 direction 长度为 0" if dl < 0.001
      ux = d[0].to_f / dl
      uy = d[1].to_f / dl
      nx = -uy
      ny = ux
    end

    # 轮廓 → 三维点：沿 u 铺到 (ux,uy)，z 用 base_z + 轮廓标高，再按厚度方向偏 th
    #
    # base_z 的意义：轮廓坐标可以写成**相对某个基面的标高**。
    # 例：女儿墙坐在屋面板顶面时，写 "base_z": 2950、"profile": [[0,0],…,[0,450]]，
    # 而不是把 2800 直接写进轮廓——否则女儿墙会和屋面板撞在一起
    # （实测：ROOF-整层顶板 ∩ E-女儿墙，Z 向重叠 150mm）。
    base_z = (e['base_z'] || 0).to_f
    to_pts = lambda do |ring, off_n|
      ring.map do |(u, z)|
        Geom::Point3d.new(
          mm(base_x + ux * u + nx * off_n),
          mm(base_y + uy * u + ny * off_n),
          mm(base_z + z)
        )
      end
    end

    outer = prof
    holes = Array(e['holes']).map { |h| normalize_profile(h) }.reject { |h| h.length < 3 }
    # 外圈与洞口圈取相反点序，帮助 add_face 正确识别内圈
    outer = outer.reverse if signed_area(outer) < 0
    holes = holes.map { |h| signed_area(h) > 0 ? h.reverse : h }

    bottom = to_pts.call(outer, 0.0)
    face = ents.add_face(bottom)
    raise "立面 #{name} 无法成面：轮廓可能自交或退化" if face.nil?

    # 记录挖洞用的面，推拉完要清掉——否则它们会以孤立面/孤立边的形式留在顶层，
    # 变成模型垃圾（实测：带洞的女儿墙会多出 1 个 Face + 4 个 Edge）。
    hole_faces = []
    holes.each_with_index do |h, i|
      hf = ents.add_face(to_pts.call(h, 0.0))
      raise "立面 #{name} 的洞口 #{i + 1} 无法成面" if hf.nil?
      hole_faces << hf
    end

    # 沿厚度方向推：先收进组，再按法线方向推拉（沿用已验证的模式）
    group = ents.add_group(face)
    n = face.normal
    # 需要推到 +n 方向（厚度方向），法线与 n 同向则推 +th，否则推 -th
    dot = n.x * nx + n.y * ny
    face.pushpull(dot >= 0 ? mm(th) : -mm(th))
    group.name = name

    # 清理挖洞留下的几何。
    # 只删面是不够的——实测顶层会残留 4 条孤立边。原因是 add_face 建洞口圈时
    # 会把新边加到模型里，而 add_group(face) 只把外圈带进组。
    # 所以先按洞口圈的边删边、再删面。
    hole_faces.each do |hf|
      next unless hf.valid?
      edges = hf.vertices.map(&:edges).flatten.uniq
      begin
        hf.erase!
      rescue StandardError
        nil
      end
      edges.each do |ed|
        begin
          ed.erase! if ed.valid?
        rescue StandardError
          nil
        end
      end
    end

    bb = profile_bbox(prof)
    {
      name: name, base_wall: e['wall'], thickness: th,
      u_range: [bb[:u0], bb[:u1]], z_range: [bb[:z0], bb[:z1]],
      holes: holes.length,
      profile_points: prof.length
    }
  end

  # ---------------------------------------------------------------- 整层顶板
  #
  # 用户指出的问题："天花板是不会漏风的，它一定是和墙严丝合缝或者盖在上面的"。
  #
  # 按房间生成天花有个根本弱点：它只盖到**房间内轮廓**，盖不住墙体本身，
  # 于是墙顶会露出一圈（从外面看像没封顶）。
  #
  # 所以补一个**整层顶板**：用所有墙的外包络做一块连续板，坐在墙顶上。
  #   · z 区间 = [墙顶, 墙顶+厚]，与墙体齐平不重叠
  #   · 平面 = 外墙总体范围 + 用户给定的出挑（eave），默认 0
  # 这样整个建筑是闭合的，没有"漏风"的地方。

  def build_envelope_ceiling(ents, data)
    spec = data['envelope_ceiling']
    return nil if spec == false
    spec = {} if spec.nil?

    walls = data['walls'] || []
    return nil if walls.empty?

    # 包络 = **原始轴线范围** + 半墙厚 + 出挑。
    # 注意不要用"已延伸过的轴线"再 + 半厚——那是把半厚加了两次
    # （实测：先延伸再加 pad，顶板变成 6480×8480，比正确的 6240×8240 各多 240）。
    xs = []
    ys = []
    zs = []
    halfs = []
    walls.each do |w|
      halfs << w['thickness'].to_f / 2.0
      [[w['from'], w['to']]].flatten(1).each do |pt|
        xs << pt[0].to_f
        ys << pt[1].to_f
      end
      zs << (w['base_z'] || 0).to_f + w['height'].to_f
    end
    eave = (spec['eave'] || 0).to_f
    # 每一侧分别取"位于该侧的墙"的半厚。
    #
    # 踩过：原来写 `pad = halfs.max`，即用**最厚那道墙**的半厚外扩四周。
    # 外墙 50（半厚 25）、内墙 100（半厚 50）时，四边各外扩 50 而非 25，
    # 顶板由 5000×5000 变成 5100×5100（多 100）。
    # 此前测试图内外墙厚度接近，差异一直被掩盖。
    thick = (spec['thickness'] || 150).to_f
    # 名字走**分组契约**：这是"整层顶板"，属于屋顶类 → RF-屋顶-Z<下>_<上>。
    # 早先叫 `ROOF-整层顶板`，跟新的 `RF-/WO-/WI-/CE-` 命名不一路，
    # 用户在 Outliner 里看到的是一堆不统一的前缀。
    name = spec['name'] ||
           (defined?(DshParts) ? DshParts.group_name(:roof) : 'RF-屋顶')

    # 顶板标高：默认坐在墙顶上，但**必须抬到最高楼面之上**。
    # 若建筑里还有夹层（F2 之类）且其高度超过墙顶，直接把顶板放在墙顶就会与它相撞
    # （实测：夹层 2800..2920 ∩ 顶板 2800..2950，Z 向重叠 120mm）。
    # 所以：默认标高 = max(墙顶, 所有楼板顶面)，可用 spec['z'] 显式指定。
    floor_tops = (data['floors'] || []).map { |f| (f['z'] || 0).to_f + (f['thickness'] || 0).to_f }
    z_default = [zs.max, floor_tops.max || 0].max
    z_top = spec.key?('z') ? spec['z'].to_f : z_default

    # 定义某条边的，是"**最靠该边的那道平行墙**"。
    #   axis  = 被外扩的轴（:x → 算东西边，找竖直墙；:y → 算南北边，找水平墙）
    #   which = :min 取小坐标侧，:max 取大坐标侧
    # 垂墙即使端点贴着这条边也不算——它不定义这条边的外皮。
    #
    # 踩过（三版）：
    #   v1 `pad = halfs.max`     → 用最厚墙统一外扩四周；外墙50/内墙100 时顶板多 100
    #   v2 端点绝对值靠近该边    → 垂墙端点也贴着边，被误选
    #   v3 跨度 min/max 靠近该边 → 垂墙的 min 端点依然贴着边，仍被误选
    # 只有"平行于该边"才能定义该边，这一条是关键。
    pad_w = lambda do |axis, which|
      cands = walls.select do |w|
        dx = (w['to'][0].to_f - w['from'][0].to_f).abs
        dy = (w['to'][1].to_f - w['from'][1].to_f).abs
        axis == :x ? (dy > dx) : (dx > dy)
      end
      cands = walls if cands.empty?
      key = lambda do |w|
        vals = [w['from'], w['to']].map { |q| (axis == :x ? q[0] : q[1]).to_f }
        which == :min ? vals.min : vals.max
      end
      # ⚠️ 这里必须用 min_by/max_by（块式），不能用 `min { }`/`max { }`。
      #
      # 踩过：SketchUp 自带的是 Ruby 3.2 但 `Enumerable#min` 带块的行为
      # 与 `Array#min(1)`（取最小 n 个）重载冲突，实际把**元素对**传进了块，
      # 于是 `w['thickness']` 里 w 是数组 → `[]` 拿不到值 → nil → NoMethodError。
      # 实测报错在 wall_end_extensions 里，根因却在这里 —— 报错点≠出错点。
      edge_w = which == :min ? cands.min_by(&key) : cands.max_by(&key)
      edge_w['thickness'].to_f / 2.0
    end
    x0 = xs.min - pad_w.call(:x, :min) - eave
    x1 = xs.max + pad_w.call(:x, :max) + eave
    y0 = ys.min - pad_w.call(:y, :min) - eave
    y1 = ys.max + pad_w.call(:y, :max) + eave

    g = box_on_ground(ents, x0, y0, x1, y1, thick, name, z_top)
    bb = g.bounds
    { name: name, size_mm: [to_mm(bb.width), to_mm(bb.height), to_mm(bb.depth)],
      footprint: [[x0.round, y0.round], [x1.round, y1.round]],
      z_range: [to_mm(bb.min.z), to_mm(bb.max.z)],
      rests_on: "墙顶 #{z_top.round}mm", eave: eave, thickness: thick }
  end

  # ---------------------------------------------------------------- 材质
  #
  # 目标里"材质"这一项。此前模型全是白模，可读性差。
  #
  # 两个必须守住的原则：
  #   1. **材质名不存在时不许抛异常**。
  #      我踩过：`group.material = 'Wood_Floor'` 直接抛
  #      `ArgumentError: Cannot find material named Wood_Floor`，整个构建失败。
  #   2. **不许悄悄换色**。按工作政策"遇到不确定就问"，找不到的材质名：
  #      · 若数据里同时给了颜色 → 用那个颜色建，并标明"自建"
  #      · 若只有名字、没有颜色 → 建一个灰模，并**记进报告**提醒用户
  #      绝不自己挑一个好看的颜色冒充。

  # 常见材质名的兜底颜色（只在用户给了名字但没给颜色时使用，且会进报告）
  DEF_MATERIAL_COLORS = {
    'concrete' => [200, 200, 198], '混凝土' => [200, 200, 198],
    'brick' => [178, 116, 96], '砖' => [178, 116, 96],
    'paint' => [246, 246, 243], '涂料' => [246, 246, 243],
    'wood' => [186, 140, 92], '木' => [186, 140, 92], '木地板' => [186, 140, 92],
    'tile' => [224, 224, 220], '瓷砖' => [224, 224, 220],
    'glass' => [178, 214, 226], '玻璃' => [178, 214, 226],
    'steel' => [140, 144, 148], '钢' => [140, 144, 148],
    'door' => [140, 100, 66], '门' => [140, 100, 66],
    'default' => [230, 230, 228], '灰模' => [230, 230, 228]
  }.freeze

  def material_color_for(name, explicit_color)
    return explicit_color.map { |c| c.to_i.clamp(0, 255) } if explicit_color.is_a?(Array) && explicit_color.length >= 3
    key = name.to_s.downcase
    DEF_MATERIAL_COLORS.each { |k, v| return v if key.include?(k.downcase) }
    DEF_MATERIAL_COLORS['default']
  end

  # 取材质对象：存在就用，不存在就按给定/兜底颜色建一个。
  # 返回 [material, created?]；任何异常都不许冒泡出去。
  def fetch_material(model, name, explicit_color = nil)
    return [nil, false] if name.nil? || name.to_s.strip.empty?
    nm = name.to_s
    existing = model.materials[nm]
    return [existing, false] if existing

    col = material_color_for(nm, explicit_color)
    mat = model.materials.add(nm)
    mat.color = Sketchup::Color.new(col[0], col[1], col[2])
    [mat, true]
  rescue StandardError => e
    raise DshBridge::Error.new('material', "创建材质 #{nm.inspect} 失败：#{e.class}: #{e.message}")
  end

  # 按构件名匹配材质规则。规则的数据结构（来自 JSON）：
  #   "materials": {
  #     "default":  { "name": "涂料", "color": [246,246,243] },
  #     "rules": [ { "match": "^W-",     "name": "砌体" },
  #                { "match": "-门扇",  "name": "wood", "color": [140,100,66] } ]
  #   }
  # match 是**正则**，先匹配到的先生效，所以把具体的放前面。
  #
  # 踩过的坑：我第一版用 `name.include?(m)` 做子串匹配，但数据里写的是 `^W-`、`^F1-`
  # 这种正则语法 —— 子串匹配不认 `^`，于是这些规则**静默失配**，
  # 45 个构件（所有墙、楼板、楼梯）全掉进 default。规则失配不会报错，只会悄悄错。
  def material_for(name, spec)
    return nil if spec.nil? || spec == false
    (spec['rules'] || []).each do |r|
      pat = r['match'].to_s
      next if pat.empty?
      begin
        return r if name.to_s.match?(Regexp.new(pat))
      rescue RegexpError => e
        # 正则写错要报出来，不能当作"没匹配上"
        raise DshBridge::Error.new('material', "材质规则 match=#{pat.inspect} 不是合法正则：#{e.message}")
      end
    end
    spec['default']
  end

  # 递归遍历所有层级的组，带回累积的世界原点。
  #
  # 为什么要递归：房间地面/天花嵌在 R-* 组里（`R-客厅-地面`），
  # 只遍历顶层组会让它们拿不到专属材质规则。
  #
  # 提醒：`vertex.position` 是**组内局部坐标**，世界坐标要靠累加各级
  # `transformation.origin` —— 这个坑我踩过好几轮了。
  def each_group_deep(ents, off = nil, &blk)
    ox = off ? off[0] : 0.0
    oy = off ? off[1] : 0.0
    oz = off ? off[2] : 0.0
    ents.grep(Sketchup::Group).each do |g|
      t = g.transformation.origin
      gx = ox + t.x
      gy = oy + t.y
      gz = oz + t.z
      blk.call(g, [gx, gy, gz])
      each_group_deep(g.definition.entities, [gx, gy, gz], &blk)
    end
  end
  # ---------------------------------------------------------------- 家具
  #
  # 定位说明：家具**不是从图纸里读出来的**（图纸上通常只有个轮廓或编号），
  # 所以这里的做法是**从已知标准尺寸反推形体**：
  #   · 一张 1500×2000 的床 = 标准双人床垫尺寸（1500×2000 是国标常见规格）
  #   · 桌高 750、椅座高 450、台面深 600 都是通行值
  # 数据里每一项都必须写 `basis`（这些数字凭什么）和 `confidence`。
  # 按工作政策：**不许为了好看瞎凑比例**；拿不准的标 low 并进疑问清单。

  # 房间内的长方体构件：给定中心、尺寸、绕竖轴朝向角（度）。
  # 可选 `off` 是**沿家具自身轴线的局部偏移** [沿宽, 沿长]，
  # 用来把部件（床头板、靠背）放到家具的某一端——
  # 这样偏移会跟着朝向角一起旋转，不必在外面手算 cos/sin。
  def box_abs(ents, cx, cy, sx, sy, sz, z0, angle_deg, name, off = nil)
    g = ents.add_group
    rad = angle_deg * Math::PI / 180.0
    ox = off ? off[0].to_f : 0.0
    oy = off ? off[1].to_f : 0.0
    # 局部偏移转到世界方向
    wx = ox * Math.cos(rad) - oy * Math.sin(rad)
    wy = ox * Math.sin(rad) + oy * Math.cos(rad)
    pts = [
      Geom::Point3d.new(mm(-sx / 2.0 + ox), mm(-sy / 2.0 + oy), mm(z0)),
      Geom::Point3d.new(mm(sx / 2.0 + ox), mm(-sy / 2.0 + oy), mm(z0)),
      Geom::Point3d.new(mm(sx / 2.0 + ox), mm(sy / 2.0 + oy), mm(z0)),
      Geom::Point3d.new(mm(-sx / 2.0 + ox), mm(sy / 2.0 + oy), mm(z0))
    ]
    face = g.definition.entities.add_face(pts)
    raise "box_abs(#{name}) 无法成面" if face.nil?
    face.pushpull(face.normal.z >= 0 ? mm(sz) : -mm(sz))
    g.transform!(Geom::Transformation.rotation(Geom::Point3d.new(0, 0, 0),
                                               Geom::Vector3d.new(0, 0, 1), rad))
    g.move!(Geom::Point3d.new(mm(cx - wx), mm(cy - wy), 0))
    g.name = name
    g
  end

  # 常见家具的**标准尺寸**（mm）。
  #
  # 数字分两级（与 规范速查.md 一致）：
  #   · 桌椅类来自 **GB/T 3326-2016**《家具 桌、椅、凳类主要尺寸》，是**规范值**
  #   · 其余是通行成品尺寸（家具是买成品的，国标给的是区间不是定值）
  #
  # ⚠️ 座高原来写 450 —— **超国标**。国标是 400~440（软面最大 460，含下沉量）。
  #    450 单看"差不多"，但它会连锁：配合高差从 300 掉到 300 → 贴着上限，
  #    人坐上去架胳膊。改成 **430**（成品餐椅常见值，落在区间内）。
  #    桌面高 750 是对的（国标 680~760），配合高差 750−430 = 320 也在 250~320 内。
  FURNITURE_STD = {
    'bed' => { 'w' => 1500, 'l' => 2000, 'h_frame' => 300, 'h_mattress' => 250 },
    'bed_single' => { 'w' => 900, 'l' => 2000, 'h_frame' => 300, 'h_mattress' => 250 },
    'table' => { 'w' => 800, 'l' => 1400, 'h' => 750, 'top' => 40 },
    'desk' => { 'w' => 600, 'l' => 1200, 'h' => 750, 'top' => 40 },
    'chair' => { 'w' => 450, 'l' => 450, 'h_seat' => 430, 'h_back' => 900, 'seat' => 40 },
    'stool' => { 'w' => 350, 'l' => 350, 'h_seat' => 430, 'seat' => 40 },
    'armchair' => { 'w' => 600, 'l' => 600, 'h_seat' => 430, 'h_back' => 900, 'seat' => 40 },
    'wardrobe' => { 'w' => 600, 'l' => 1200, 'h' => 2400 },
    'cabinet' => { 'w' => 450, 'l' => 900, 'h' => 900 },
    'sofa' => { 'w' => 900, 'l' => 2000, 'h_seat' => 420, 'h_back' => 800 },
    'fridge' => { 'w' => 650, 'l' => 650, 'h' => 1700 },
    'stove' => { 'w' => 600, 'l' => 750, 'h' => 850 },
    'sink' => { 'w' => 550, 'l' => 800, 'h' => 850 },
    'toilet' => { 'w' => 400, 'l' => 700, 'h' => 750 },
    'dresser' => { 'w' => 450, 'l' => 1000, 'h' => 740, 'top' => 40 },
    'dining_table_double' => { 'w' => 800, 'l' => 1600, 'h' => 750, 'top' => 40 },
    'dining_table_single' => { 'w' => 600, 'l' => 1200, 'h' => 750, 'top' => 40 },
  }.freeze

  def build_furniture(ents, item)
    kind = (item['kind'] || 'box').to_s
    std = FURNITURE_STD[kind]
    cx = item['at'][0].to_f
    cy = item['at'][1].to_f
    ang = (item['angle'] || 0).to_f
    name = item['name'] || kind
    z0 = (item['z'] || 0).to_f

    # 尺寸优先用数据给的，缺的才取标准值——并且把"哪些是取的标准值"记下来
    w = (item['w'] || (std && std['w'])).to_f
    l = (item['l'] || (std && std['l'])).to_f
    raise "家具 #{name} 缺少尺寸，且 #{kind} 没有标准尺寸可依" if w <= 0 || l <= 0

    h = (item['h'] || (std && (std['h'] || std['h_frame'])) || 750).to_f
    parts = []

    case kind
    when 'bed', 'bed_single'
      hf = (std ? std['h_frame'] : 300)
      hm = (std ? std['h_mattress'] : 250)
      hh = (item['h_headboard'] || 900).to_f
      parts << box_abs(ents, cx, cy, w, l, hf, z0, ang, "#{name}-床架")
      parts << box_abs(ents, cx, cy, w - 60, l - 60, hm, z0 + hf, ang, "#{name}-床垫")
      # 床头板在 -长/2 那一端（局部偏移，会跟着朝向角转）
      parts << box_abs(ents, cx, cy, w, 60, hh - hf, z0 + hf, ang, "#{name}-床头板",
                       [0, -l / 2.0 + 30])
    when 'table', 'desk'
      top = (std ? std['top'] : 40)
      parts << box_abs(ents, cx, cy, w, l, top, z0 + h - top, ang, "#{name}-台面")
      # 四条腿：靠四角内缩 60
      leg = 60
      [[-1, -1], [1, -1], [1, 1], [-1, 1]].each_with_index do |(sx_, sy_), i|
        parts << box_abs(ents, cx + sx_ * (w / 2.0 - leg / 2.0 - 40),
                         cy + sy_ * (l / 2.0 - leg / 2.0 - 40),
                         leg, leg, h - top, z0, ang, "#{name}-腿#{i + 1}")
      end
    when 'chair', 'armchair', 'stool'
      # 椅子 / 扶手椅 / 凳 共用一个形体：座面 + 四腿（+ 靠背）
      #
      # 凳**没有靠背** —— 用户点名问过"凳子桌子这些一般要多高多宽"，
      # 所以这里按 GB/T 3326-2016 的座高（430，区间 400~440）来，
      # 并且靠背只在 chair / armchair 上生成。
      hs = (std ? std['h_seat'] : 430)
      seat = (std ? std['seat'] : 40)
      hb = (std ? std['h_back'] : 900)
      parts << box_abs(ents, cx, cy, w, l, seat, z0 + hs - seat, ang, "#{name}-座面")
      unless kind == 'stool'
        parts << box_abs(ents, cx, cy, w, 40, hb - hs, z0 + hs, ang, "#{name}-靠背")
      end
      # 扶手椅：两侧加扶手（高 = 座面 + 200，通行做法）
      if kind == 'armchair'
        ah = hs + 200
        [[-1, 0], [1, 0]].each_with_index do |(sx_, _), i|
          parts << box_abs(ents, cx + sx_ * (w / 2.0 - 30), cy, 60, l,
                           ah - hs, z0 + hs, ang, "#{name}-扶手#{i + 1}")
        end
      end
      leg = 40
      [[-1, -1], [1, -1], [1, 1], [-1, 1]].each_with_index do |(sx_, sy_), i|
        parts << box_abs(ents, cx + sx_ * (w / 2.0 - leg), cy + sy_ * (l / 2.0 - leg),
                         leg, leg, hs - seat, z0, ang, "#{name}-腿#{i + 1}")
      end
    when 'sofa'
      hs = (std ? std['h_seat'] : 420)
      hb = (std ? std['h_back'] : 800)
      parts << box_abs(ents, cx, cy, w, l, hs, z0, ang, "#{name}-座箱")
      parts << box_abs(ents, cx, cy, w, 200, hb - hs, z0 + hs, ang, "#{name}-靠背",
                       [0, -l / 2.0 + 100])
    when 'wardrobe', 'cabinet', 'fridge'
      parts << box_abs(ents, cx, cy, w, l, h - z0, z0, ang, "#{name}-柜体")
    when 'stove', 'sink'
      parts << box_abs(ents, cx, cy, w, l, h - z0, z0, ang, "#{name}-台体")
    when 'toilet'
      parts << box_abs(ents, cx, cy, w, l, 400 - z0, z0, ang, "#{name}-座体")
      parts << box_abs(ents, cx, cy, w, 200, h - 400, 400, ang, "#{name}-水箱",
                       [0, -l / 2.0 + 100])
    else
      # 未知类型：按给定尺寸建一个长方体（不假装知道它长什么样）
      parts << box_abs(ents, cx, cy, w, l, h - z0, z0, ang, "#{name}-体")
    end

    # size 里第三个数取**顶面标高**而不是"某个部件的高度"：
    # 床的部件高度是 300（床架），但整件家具到 900（床头板）——
    # 报 300 会让人误以为床只有 300 高。
    top_z = parts.map { |p| to_mm(p.bounds.max.z) }.max || z0
    { name: name, ftype: kind, at: [cx.round, cy.round], angle: ang,
      size: [w.round, l.round, top_z.round], parts: parts.length,
      basis: item['basis'], confidence: item['confidence'] }
  end

  # ---------------------------------------------------------------- 坡屋面
  #
  # 为什么必须有：按工作政策"屋顶形式必须问用户（或由用户给图纸）"。
  # 但在此之前我**连问的基础设施都没有**——生成器只会建平屋面板 + 女儿墙，
  # 所以"你要什么屋顶"这句话后面接不上任何东西。
  # 这里把形式、坡度、出挑、方向都做成参数：**形式由数据指定，我不替你选**。
  #
  # 支持的 form：
  #   flat  平屋面（等价于现有整层顶板）
  #   shed  单坡（向 dir 的反方向落水，high_on 指定高侧）
  #   gable 双坡（屋脊平行于 dir）
  #   hip   四坡（屋脊平行于 dir，两端各收进 span/2）

  # 坡度输入可以是 0.5（高:平）、"1:2"、"30°"、"30deg"、"30%"
  def pitch_rad(p, default_deg = 30.0)
    return default_deg * Math::PI / 180.0 if p.nil?
    if p.is_a?(Numeric)
      return p * Math::PI / 180.0 if p > 3.0   # 大于 3 当作度数（坡度比不会超过 3）
      return Math.atan(p)                       # 否则当作 高:平 比
    end
    s = p.to_s.strip.downcase
    return s.to_f * Math::PI / 180.0 if s.end_with?('deg')
    return s.to_f * Math::PI / 180.0 if s.end_with?('°')
    return Math.atan(s.to_f / 100.0) if s.end_with?('%')
    if s.include?(':')
      a, b = s.split(':').map(&:to_f)
      return Math.atan(a / b)
    end
    Math.atan(s.to_f)
  end

  # 建面：凸多边形按给定点序建面，失败就反转顺序再试。
  # 为什么要这样：点序的顺/逆时针不容易一次写对，而 SketchUp 对面朝向敏感。
  # 与其在外面推导朝向，不如让代码自己试——**能建成就是对的**。
  def try_face(ents, pts_mm)
    [pts_mm, pts_mm.reverse].each do |seq|
      face = ents.add_face(seq.map { |(x, y, z)| Geom::Point3d.new(mm(x), mm(y), mm(z)) })
      return face if face
    rescue StandardError
      next
    end
    nil
  end

  # 一块屋面：成面 → **立刻包组** → 沿 +Z 推出厚度。返回组。
  #
  # 包组这一步不能省。我踩过：屋面直接往 ents 加面，
  # 结果 52 个 Face + 102 个 Edge 散落在顶层——既不好选，
  # 清空模型时也清不干净，下一次构建的实体数会累加。
  def roof_piece(ents, outer_pts, nth, name)
    inner = outer_pts.map { |(x, y, z)| [x, y, z - nth] }
    f = try_face(ents, inner)
    raise "#{name} 无法成面（点序或共线问题）" if f.nil?
    g = ents.add_group(f)
    f.pushpull(mm(nth))
    g.name = name
    g
  end

  def footprint_ring(x0, y0, x1, y1)
    [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
  end

  # 把矩形轮廓向外扩 d（出挑）
  def expand_ring(ring, d)
    xs = ring.map { |p| p[0] }
    ys = ring.map { |p| p[1] }
    footprint_ring(xs.min - d, ys.min - d, xs.max + d, ys.max + d)
  end

  # 由覆盖多边形 + 坡度生成坡屋面实体。
  # 返回 { faces:, ridge_h:, form:, ... }
  def build_roof_surface(ents, r, walls)
    form = (r['form'] || 'flat').to_s
    eave = (r['eave'] || 0).to_f
    t = (r['thickness'] || 200).to_f
    name = r['name'] || "ROOF-#{form}"

    # 覆盖范围：默认取所有墙的原始轴线包络 + 半墙厚 + 出挑。
    # 和整层顶板用同一套算法（不要用"已延伸的轴线"，那会把半厚加两次）。
    if r['polygon']
      ring = r['polygon'].map { |p| [p[0].to_f, p[1].to_f] }
      ring = expand_ring(ring, eave)
    else
      halfs = walls.map { |w| w['thickness'].to_f / 2.0 }
      xs = walls.flat_map { |w| [w['from'][0].to_f, w['to'][0].to_f] }
      ys = walls.flat_map { |w| [w['from'][1].to_f, w['to'][1].to_f] }
      pad = (halfs.max || 0) + eave
      ring = footprint_ring(xs.min - pad, ys.min - pad, xs.max + pad, ys.max + pad)
    end
    x0 = ring.map { |p| p[0] }.min
    x1 = ring.map { |p| p[0] }.max
    y0 = ring.map { |p| p[1] }.min
    y1 = ring.map { |p| p[1] }.max

    # 基面标高：显式 base_z 优先；否则用墙顶（屋面坐在墙顶上）。
    base = if r.key?('base_z')
             r['base_z'].to_f
           else
             (walls.map { |w| (w['base_z'] || 0).to_f + w['height'].to_f }.max || 0.0)
           end
    raise "屋面 #{name}：没有墙也没有给 base_z，无法确定基面标高" if walls.empty? && !r.key?('base_z')

    rad = pitch_rad(r['pitch'], 30.0)
    dir = (r['dir'] || 'x').to_s.downcase
    faces = 0
    ridge = nil
    made_groups = []

    # 加一块屋面：底面点向下偏 nth（屋面板厚），成面后**向上**推出 nth。
    #
    # 统一沿 +Z 推出（不是沿面法向）：面法向对坡面是斜的，对山墙三角面是水平的，
    # 「沿法向推」在两种情况下含义不同、结果只有一个是对的。
    # 沿 +Z 推则在两种情况下都得到"竖直方向等厚"的板，这才是屋面该有的厚度语义。
    add = lambda do |outer_pts, nth|
      faces += 1
      made_groups << roof_piece(ents, outer_pts, nth, format('%s-%02d', name, faces))
    end

    # 檐角标高 [x0y0, x1y0, x1y1, x0y1]：默认恒为 base。
    # 双坡/四坡的山墙端檐口**也是恒高**（屋脊平行 dir，屋面沿另一轴水平），
    # 所以这四种形式的檐口线都是水平的——封檐板因此是一圈竖直矩形。
    zc = [base, base, base, base]
    fascia_ring = nil   # 需要封檐板的檐口矩形；shed 只有低侧一条边

    case form
    when 'flat'
      add.call(ring.map { |(x, y)| [x, y, base] }, t)
      ridge = base
      fascia_ring = [x0, y0, x1, y1]
    when 'shed'
      hi = (r['high_on'] || 'y0').to_s        # y0 / y1 / x0 / x1
      span = %w[y0 y1].include?(hi) ? (y1 - y0) : (x1 - x0)
      rise = span * Math.tan(rad)
      z_hi = base + rise
      z_lo = base
      # 4 个角点，按 high_on 决定哪一侧高
      corner = lambda do |x, y|
        case hi
        when 'y0' then [x, y, (y - y0).abs < 1e-6 ? z_hi : z_lo]
        when 'y1' then [x, y, (y - y1).abs < 1e-6 ? z_hi : z_lo]
        when 'x0' then [x, y, (x - x0).abs < 1e-6 ? z_hi : z_lo]
        else [x, y, (x - x1).abs < 1e-6 ? z_hi : z_lo]
        end
      end
      add.call([corner.call(x0, y0), corner.call(x1, y0), corner.call(x1, y1), corner.call(x0, y1)], t)
      # 低侧与高侧的竖向封边
      add.call([[x0, y0, base], [x1, y0, base], corner.call(x1, y0), corner.call(x0, y0)].uniq, t) if hi != 'y0'
      ridge = z_hi
      # 单坡只有**低侧**是檐口（高侧是墙顶收头，没有檐下空间）
      zc = [z_hi, z_hi, z_lo, z_lo] if hi == 'y0'
      zc = [z_lo, z_lo, z_hi, z_hi] if hi == 'y1'
      zc = [z_hi, z_lo, z_lo, z_hi] if hi == 'x0'
      zc = [z_lo, z_hi, z_hi, z_lo] if hi == 'x1'
      fascia_ring = [x0, y0, x1, y1]
    when 'gable'
      if dir == 'x'
        span = y1 - y0
        rise = span / 2.0 * Math.tan(rad)
        zr = base + rise
        ym = (y0 + y1) / 2.0
        # 两面坡
        add.call([[x0, y0, base], [x1, y0, base], [x1, ym, zr], [x0, ym, zr]], t)
        add.call([[x0, ym, zr], [x1, ym, zr], [x1, y1, base], [x0, y1, base]], t)
        # 两端山墙（竖直三角面，用很薄的一块表达）
        add.call([[x0, y0, base], [x0, y1, base], [x0, ym, zr]], t)
        add.call([[x1, y1, base], [x1, y0, base], [x1, ym, zr]], t)
        ridge = zr
      else
        span = x1 - x0
        rise = span / 2.0 * Math.tan(rad)
        zr = base + rise
        xm = (x0 + x1) / 2.0
        add.call([[x0, y0, base], [xm, y0, zr], [xm, y1, zr], [x0, y1, base]], t)
        add.call([[xm, y0, zr], [x1, y0, base], [x1, y1, base], [xm, y1, zr]], t)
        add.call([[x0, y1, base], [x0, y0, base], [xm, y0, zr]], t)
        add.call([[x1, y0, base], [x1, y1, base], [xm, y1, zr]], t)
        ridge = zr
      end
      fascia_ring = [x0, y0, x1, y1]
    when 'hip'
      if dir == 'x'
        span = y1 - y0
        inset = span / 2.0
        rise = inset * Math.tan(rad)
        zr = base + rise
        ym = (y0 + y1) / 2.0
        rx0 = x0 + inset
        rx1 = x1 - inset
        # 两条正坡（梯形）
        add.call([[x0, y0, base], [x1, y0, base], [rx1, ym, zr], [rx0, ym, zr]], t)
        add.call([[rx0, ym, zr], [rx1, ym, zr], [x1, y1, base], [x0, y1, base]], t)
        # 两端斜脊（三角形）
        add.call([[x0, y1, base], [x0, y0, base], [rx0, ym, zr]], t)
        add.call([[x1, y0, base], [x1, y1, base], [rx1, ym, zr]], t)
        ridge = zr
      else
        span = x1 - x0
        inset = span / 2.0
        rise = inset * Math.tan(rad)
        zr = base + rise
        xm = (x0 + x1) / 2.0
        ry0 = y0 + inset
        ry1 = y1 - inset
        add.call([[x0, y0, base], [xm, ry0, zr], [xm, ry1, zr], [x0, y1, base]], t)
        add.call([[xm, ry0, zr], [x1, y0, base], [x1, y1, base], [xm, ry1, zr]], t)
        add.call([[x0, y1, base], [x0, y0, base], [xm, ry0, zr]], t)
        add.call([[x1, y0, base], [x1, y1, base], [xm, ry1, zr]], t)
        ridge = zr
      end
      fascia_ring = [x0, y0, x1, y1]
    else
      raise "不认识的屋面形式 #{form.inspect}（支持 flat / shed / gable / hip）"
    end

    # ── 檐口封檐板
    # 默认深度 = 屋面板厚（正好把板端头封住）。可用 fascia_depth 调整，0 表示不做。
    fd = r.key?('fascia_depth') ? r['fascia_depth'].to_f : t
    fas = nil
    if fascia_ring && fd > 0
      fx0, fy0, fx1, fy1 = fascia_ring
      if form == 'shed'
        # 单坡只有低侧一条边是檐口。找出标高最低的那条边，只加那一块。
        low = zc.each_index.min_by { |i| zc[i] }
        edges = [
          [[fx0, fy0], [fx1, fy0]], [[fx1, fy0], [fx1, fy1]],
          [[fx0, fy1], [fx1, fy1]], [[fx0, fy0], [fx0, fy1]]
        ]
        ea, eb = edges[low]
        fas = build_roof_fascia_edge(ents, name, ea, eb, zc[low], fd)
      else
        fas = build_roof_fascia(ents, name, fx0, fy0, fx1, fy1, base, fd)
      end
    end

    {
      name: name, form: form, pieces: faces,
      footprint: [[x0.round, y0.round], [x1.round, y1.round]],
      pitch_deg: (rad * 180.0 / Math::PI).round(1),
      base_z: base.round, ridge_z: ridge.nil? ? nil : ridge.round,
      thickness: t, eave: eave, dir: dir,
      fascia: fas,
      # 实测标高范围：来自**建出来的几何**，不是推算值。
      # 加这个是因为我排查"屋面基准差了 200"时只能反复用探针去量——
      # 报告里直接带上，以后一眼可查。
      z_range: made_groups.empty? ? nil : [
        made_groups.map { |g| to_mm(g.bounds.min.z) }.min.round,
        made_groups.map { |g| to_mm(g.bounds.max.z) }.max.round
      ]
    }
  end

  # 一条封檐板：沿 (a→b) 的竖直窄条，从 z_top 往下 depth。
  # 垂直方向内移半厚，避免相邻两条在转角互相穿插。
  def fascia_board(ents, a, b, z_top, depth, name, w = 40.0)
    ax, ay = a
    bx, by = b
    dx = bx - ax
    dy = by - ay
    len = Math.sqrt(dx * dx + dy * dy)
    return nil if len < 1
    ux = dx / len
    uy = dy / len
    nx = -uy
    ny = ux
    box_plate(ents, [ax + nx * w / 2.0, ay + ny * w / 2.0],
              [ux, uy, len], [nx, ny, w],
              z_top - depth, z_top, name)
  end

  # 檐口封檐板：沿檐口周长一圈，把屋面边缘"封口"。
  #
  # 为什么需要：坡屋顶做到檐口时只有一条薄板边，从外面看檐下是敞开的。
  # 真实做法是沿檐口钉一圈封檐板（fascia），把屋面板的端头挡住。
  #
  # 几何要点：这四种形式的**檐口都是水平的**，所以封檐板是一圈竖直矩形：
  #   · flat ：檐口 = ring，标高 base
  #   · gable/hip：直坡边沿 x 恒高；山墙端屋脊平行 x，所以**也是恒高**
  #                → 整个檐口是水平闭合矩形
  #   · shed ：标高随位置变，**只有低侧一条边是檐口**（高侧是墙顶收头）
  #
  # 单坡那个"只有一条边"是单独处理的：我一开始把低侧边伪装成"退化矩形"
  # 传进来，但这个函数是**按四边**建的，于是生成了 2 块、且位置互相重叠
  # （实测 y=5420..5460 和 5340..5380）。
  def build_roof_fascia(ents, name, x0, y0, x1, y1, z_eave, depth)
    return nil if depth.to_i <= 0
    edges = [
      [[x0, y0], [x1, y0]],
      [[x1, y0], [x1, y1]],
      [[x1, y1], [x0, y1]],
      [[x0, y1], [x0, y0]]
    ]
    made = []
    edges.each_with_index do |(a, b), i|
      g = fascia_board(ents, a, b, z_eave, depth, format('%s-封檐板%d', name, i + 1))
      made << g if g
    end
    return nil if made.empty?
    { name: "#{name}-封檐板", pieces: made.length, depth: depth,
      z_range: [z_eave - depth, z_eave] }
  end

  # 单坡专用：只在低侧那一条边加封檐板
  def build_roof_fascia_edge(ents, name, a, b, z_eave, depth)
    return nil if depth.to_i <= 0
    g = fascia_board(ents, a, b, z_eave, depth, "#{name}-封檐板")
    return nil if g.nil?
    { name: "#{name}-封檐板", pieces: 1, depth: depth,
      z_range: [z_eave - depth, z_eave] }
  end

  # ---------------------------------------------------------------- 主入口

  # data = {
  #   "meta" => {"name"=>..., "units"=>"mm"},
  #   "walls" => [...], "floors" => [...], "columns" => [...]
  # }
  def build(data)
    model = Sketchup.active_model
    ents = model.entities
    report = { built: [], warnings: [], errors: [] }

    label = (data['meta'] || {})['name'] || 'DSH 建筑'
    model.start_operation("DSH 生成：#{label}", true)

    (data['floors'] || []).each do |slab|
      begin
        g = build_floor(ents, slab)
        bb = g.bounds
        report[:built] << {
          kind: 'floor', name: g.name,
          size_mm: [to_mm(bb.width), to_mm(bb.height), to_mm(bb.depth)],
          min_z: to_mm(bb.min.z)
        }
      rescue => e
        report[:errors] << "楼板 #{slab['name']}: #{e.class}: #{e.message}"
      end
    end

    # ══════════════════════════════════════════════════════════════
    #  墙体：两种做法，由 `wall_mode` 选择
    # ══════════════════════════════════════════════════════════════
    #
    #   'grouped'（默认）：**按类别成组 + 轮廓推拉，一次成型**
    #       · 外墙 / 内墙 / 隔墙 各自一组，组内是一个整体
    #       · 外面没有分割线、面数少（实测 41 组 → 7 组）
    #       · 用 DshParts.build_walls（轮廓推拉）
    #
    #   'legacy'：老做法，每面墙一堆盒子
    #       · 转角互相重叠、外面有分割线、面数浪费
    #       · 保留它只是为了**出问题时能退回去**，不建议用
    #
    # 用户明确要求："大整体要分组，工具要会用推拉工具和 union，
    # 不能光靠一个一个建盒子堆出来。"
    wall_mode = (data['meta'] || {})['wall_mode'] || 'grouped'
    walls_data = data['walls'] || []

    if wall_mode == 'grouped' && !walls_data.empty? && defined?(DshParts)
      begin
        res = DshParts.build_walls(ents, walls_data)
        res.each do |r|
          if r[:group]
            r[:group].material = material_for(r[:group].name, nil) rescue nil
            report[:built] << {
              kind: 'wall_group', name: r[:group].name, category: r[:category],
              z0: r[:z0], z1: r[:z1],
              faces: r[:faces], outers: r[:outers], holes: r[:holes],
              volume_m3: r[:volume_m3], expect_m3: r[:want]
            }
            # 自检：体积必须等于"矩形并集面积 × 高"，否则说明成型错了
            unless r[:ok]
              report[:warnings] << format(
                '墙组 %s 体积 %.3f ≠ 期望 %.3f m³（成型可能有误）',
                r[:group].name, r[:volume_m3].to_f, r[:want].to_f)
            end
          else
            report[:errors] << "墙组 #{r[:category]}: #{r[:error]}"
          end
        end
      rescue StandardError => e
        report[:errors] << "分类成组失败（#{e.class}: #{e.message}），已回退到逐块做法"
        wall_mode = 'legacy'
      end
    end

    if wall_mode != 'grouped'
      # 转角延伸量：**循环外算一次**，按索引取用。
      # （不要在循环里用 index(wall) 定位——数据里若有重复对象会取错，
      #   而且每面墙都重算一遍全部墙的相接关系，纯属浪费。）
      wall_exts = wall_end_extensions(walls_data)

      walls_data.each_with_index do |wall, wi|
      begin
        # 转角处理：相接端各延伸半个墙厚，避免角部空洞（见 wall_end_extensions 的注释）
        eff = wall_with_extensions(wall, wall_exts[wi][0], wall_exts[wi][1])
        info = build_wall(ents, eff)
        r = { kind: 'wall', name: info[:name], length_mm: info[:length].round(1),
              slabs: info[:slabs], openings: info[:openings],
              extended: eff['_extended'],
              joinery: (info[:joineries] || []).map { |j|
                j[:error] ? { label: j[:name], error: j[:error] }
                          : { label: j[:label], type: j[:type], panels: j[:panels], size: j[:size] }
              } }
        (info[:joineries] || []).each do |j|
          report[:errors] << "门窗 #{j[:name]}: #{j[:error]}" if j[:error]
        end
        # 自检：这一面墙所有块的高度范围是否都在 [base_z, base_z+height] 内
        wz = (wall['base_z'] || 0).to_f
        wh = wall['height'].to_f
        tops = (ents.grep(Sketchup::Group).select { |g| g.name.start_with?(info[:name]) }
                    .map { |g| to_mm(g.bounds.max.z) })
        r[:top_mm] = tops.max
        if tops.max && (tops.max - (wz + wh)).abs > 1
          report[:warnings] << "墙 #{info[:name]} 顶面 #{tops.max}mm，期望 #{wz + wh}mm"
        end
        report[:built] << r
      rescue => e
        report[:errors] << "墙 #{wall['name']}: #{e.class}: #{e.message}"
      end
      end                      # walls_data.each_with_index
    end                        # if wall_mode != 'grouped'

    model.commit_operation

    # 先算出房间两两重叠关系，再逐间生成。
    # 顺序很重要：重叠信息必须在生成之前算好，才能写进每个房间自己的 valid/issues，
    # 否则重叠的房间会显示成 ✅（问题只飘在另一条警告里）。
    rooms_data = (data['rooms'] || [])
    polys = rooms_data.select { |r| r['polygon'] && r['polygon'].length >= 3 }
    overlap_map = Hash.new { |h, k| h[k] = [] }
    polys.combination(2).each do |r1, r2|
      next unless boxes_overlap?(room_bounds(r1['polygon']), room_bounds(r2['polygon']))
      overlap_map[r1['name']] << r2['name']
      overlap_map[r2['name']] << r1['name']
    end

    rooms_data.each do |room|
      begin
        v = validate_room(room, data['walls'] || [], overlap_map[room['name']])
        g = build_room(ents, room)
        report[:built] << {
          kind: 'room', name: g.name,
          size_mm: v[:size_mm], min_mm: v[:min_mm], max_mm: v[:max_mm],
          ceiling: (room['ceiling_height'] || 0).to_f,
          parts: g.definition.entities.grep(Sketchup::Group).length,
          valid: v[:ok], issues: v[:issues]
        }
        v[:issues].each { |s| report[:warnings] << "房间 #{room['name']}: #{s}" }
      rescue => e
        report[:errors] << "房间 #{room['name']}: #{e.class}: #{e.message}"
      end
    end

    # ── 整层顶板（盖在墙顶上，让建筑闭合、不漏风）
    #
    # 可以用 "envelope_ceiling": {"skip": true} 显式关掉。
    # 为什么需要这个开关：分层建模时（比如先建一层、再 --keep 追加二层），
    # 每层都自动加一块顶板就会**挡住中庭和上层**，而且它按当层墙的范围算，
    # 分两次建出来的顶板尺寸还是错的（实测 6117×8350）。
    # 与其每次手工删，不如让数据说了算。
    begin
      _ec = data['envelope_ceiling']
      env = (_ec.is_a?(Hash) && _ec['skip']) ? nil : build_envelope_ceiling(ents, data)
      if env
        report[:built] << { kind: 'envelope', **env }
      end
    rescue => ex
      report[:errors] << "整层顶板: #{ex.class}: #{ex.message}"
    end

    # ── 楼梯
    (data['stairs'] || []).each do |st|
      begin
        rec = build_stair(ents, st)
        report[:built] << { kind: 'stair', **rec }
        rec[:warnings].each { |w| report[:warnings] << "楼梯 #{st['name']}: #{w}" }
      rescue => ex
        report[:errors] << "楼梯 #{st['name']}: #{ex.class}: #{ex.message}"
      end
    end

    # ── 立面轮廓（女儿墙、坡屋顶、山墙、雨棚等"竖向"构件）
    # 立面必须挂在一面已知的墙上，或者自带 origin/direction。
    # 挂在墙上时还会核对轮廓是否超出墙长——超出说明我把立面读错了或墙读错了。
    walls_by_name = (data['walls'] || []).each_with_object({}) { |w, h| h[w['name']] = w }
    (data['elevations'] || []).each do |el|
      begin
        info = build_elevation(ents, el, walls_by_name)
        rec = { kind: 'elevation', name: info[:name], base_wall: info[:base_wall],
                thickness: info[:thickness], u_range: info[:u_range],
                z_range: info[:z_range], holes: info[:holes] }

        if info[:base_wall]
          w = walls_by_name[info[:base_wall]]
          dx = w['to'][0].to_f - w['from'][0].to_f
          dy = w['to'][1].to_f - w['from'][1].to_f
          wlen = Math.sqrt(dx * dx + dy * dy)
          u0, u1 = info[:u_range]
          if u0 < -1 || u1 > wlen + 1
            rec[:warning] = format('轮廓 u 范围 %.0f..%.0f 超出墙 %s 的长度 %.0fmm',
                                   u0, u1, info[:base_wall], wlen)
            report[:warnings] << "立面 #{info[:name]}: #{rec[:warning]}"
          end
          wh = w['height'].to_f + (w['base_z'] || 0).to_f
          if info[:z_range][1] > wh + 1
            report[:warnings] << format('立面 %s 顶标高 %.0fmm 高于所属墙顶 %.0fmm —— 若这是女儿墙/屋顶属正常，否则请核对',
                                        info[:name], info[:z_range][1], wh)
          end
        end
        report[:built] << rec
      rescue => ex
        report[:errors] << "立面 #{el['name']}: #{ex.class}: #{ex.message}"
      end
    end

    # ── 坡屋面（opt-in：数据里给了 roof 才建）
    #
    # 按工作政策"屋顶形式必须问用户（或由用户给图纸）"：
    # 这里**形式完全由数据的 roof.form 决定**，我不替你选。
    # 数据没给 roof 时，就只保留平屋面板（整层顶板），并在疑问清单里问形式。
    #
    # roof 可以是单个对象，也可以是**数组**（一个模型里多栋/多屋面）。
    Array(data['roof']).each do |rf|
      next unless rf.is_a?(Hash)
      begin
        report[:built] << { kind: 'roof', **build_roof_surface(ents, rf, data['walls'] || []) }
      rescue => ex
        report[:errors] << "屋面 #{rf['name'] || rf['form']}: #{ex.class}: #{ex.message}"
      end
    end

    # ── 家具（opt-in：数据里给了 furniture 才建）
    #
    # 按工作政策，家具**不是从图纸读出来的**——所以每一项都必须写
    # `basis`（尺寸凭什么）与 `confidence`；标 low 的会进疑问清单。
    (data['furniture'] || []).each do |fi|
      begin
        # 注意：`kind: 'furniture'` 必须放在 `**` 之前，而且被展开的 hash 里
        # **不能也有 `kind` 键**——Ruby 的 `**hash` 会覆盖前面的同名键。
        # 我踩过：build_furniture 原来返回 `kind: 'bed'`，把外层的
        # `kind: 'furniture'` 覆盖掉了，于是驱动按 `b["kind"] == "bed"`
        # 匹配不到任何分支，落进兜底、明细行什么细节都不显示。
        # 现在家具类型叫 `ftype`。
        report[:built] << { kind: 'furniture', **build_furniture(ents, fi) }
      rescue => ex
        report[:errors] << "家具 #{fi['name'] || fi['ftype']}: #{ex.class}: #{ex.message}"
      end
    end

    model.active_view.zoom_extents

    # ── 材质：几何建完后统一上材质
    #
    # 为什么放在**最后**而不是边建边赋：材质是按名字匹配的，
    # 而名字要等构件都建出来才齐；而且统一处理只需一段循环，
    # 不必在十来个建构件的地方各插一次。
    mspec = data['materials']
    if mspec && mspec != false
      applied = Hash.new(0)
      created = []
      failed = []
      # **递归**遍历：房间地面/天花嵌在 R-* 组里，只遍历顶层会让它们
      # 拿不到专属材质（实测："-地面$"、" -天花$" 规则一条都没命中）。
      each_group_deep(ents) do |g, _off|
        rule = material_for(g.name, mspec)
        next if rule.nil?
        begin
          mat, is_new =
            if rule.is_a?(Hash)
              fetch_material(model, rule['name'], rule['color'])
            else
              fetch_material(model, rule.to_s, nil)
            end
          next if mat.nil?
          g.material = mat
          applied[mat.display_name] += 1
          created << mat.display_name if is_new && !created.include?(mat.display_name)
        rescue StandardError => e
          failed << "#{g.name}: #{e.message}"
        end
      end
      report[:materials] = {
        applied: applied,
        created: created,
        failed: failed
      }
      created.each do |nm|
        report[:warnings] <<
          "材质「#{nm}」在模型里原本不存在，我按兜底颜色新建了它。" \
          '如果实际要用贴图或指定颜色，请在数据的 materials 里给该材质加上 color（或改用已有材质名）'
      end
    end

    model.entities.grep(Sketchup::Group).each do |g|
      next unless g.name.start_with?('DSH') || g.name =~ /^(W|F|C)\d/
      next unless g.bounds.valid?
      if to_mm(g.bounds.min.z) < -1
        report[:warnings] << "#{g.name} 落到地面以下 (min_z=#{to_mm(g.bounds.min.z)}mm)"
      end
    end

    report[:total_groups] = ents.grep(Sketchup::Group).length
    report[:questions] = questions_for(data)

    # ── 精简摘要，放在报告**最前面**
    #
    # 为什么需要：完整报告会随模型规模线性膨胀，而 DSH 工具层的输出上限约
    # 4000 字符。实测踩过：4 栋房子 16 面墙时报告被中途截断，
    # 排在后面的屋面信息**全部丢失**，看起来"屋顶没建出来"，
    # 实际是报告没传回来。查了很久。
    #
    # 摘要只留"每个构件一行"的关键值，体积小、不会先被截掉。
    report[:brief] = (report[:built] || []).map do |b|
      base = { k: b[:kind], n: b[:name] }
      base[:ok] = b[:warnings].to_a.empty? && b[:errors].to_a.empty?
      case b[:kind]
      when 'wall' then base.merge(l: b[:length_mm], s: b[:slabs], o: b[:openings], t: b[:top_mm])
      when 'stair' then base.merge(st: b[:steps], r: b[:rise], h: b[:height])
      when 'roof' then base.merge(f: b[:form], p: b[:pitch_deg], bz: b[:base_z],
                                  rz: b[:ridge_z], z: b[:z_range],
                                  fa: (b[:fascia] ? b[:fascia][:pieces] : 0))
      when 'furniture' then base.merge(t: b[:ftype], c: b[:confidence])
      when 'floor' then base.merge(z: b[:min_z])
      when 'envelope' then base.merge(z: b[:z_range])
      when 'elevation' then base.merge(o: b[:holes], th: b[:thickness])
      when 'room' then base.merge(sz: b[:size_mm])
      else base
      end
    end
    # 把 brief 挪到最前（Ruby 的 Hash 保序）
    ordered = { brief: report.delete(:brief) }
    report.each { |k, v| ordered[k] = v }
    ordered
  end
end
