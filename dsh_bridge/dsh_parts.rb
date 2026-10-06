# dsh_parts.rb —— 通用构件库（**可热重载**）
#
# 为什么单独成层：这一轮给 designproject2 建模时，我把"墙开门窗、楼板挖洞、
# 螺旋楼梯、材质"这些逻辑写成了 p2_*.rb 一堆**一次性脚本**——
# 下次换张图又得重写一遍。
# 这里把它们固化成带参数的函数，任何图纸都能直接调。
#
# 与另两层的关系：
#   dsh_bridge.rb   基础设施（改这里要重启）
#   dsh_handlers.rb 命令实现（可热重载）
#   dsh_parts.rb    **构件库**（本文件，可热重载）—— 被 build_from_plan.rb 使用
#
# 全部函数都遵守两条已踩过坑的约定：
#   1. **洞口用"沿墙方向的面线起止"给**，不是 u（u 会随墙端漂移，实测漂过 25~284mm）
#   2. **不用布尔运算**：带洞的墙/板一律**拆成无重叠矩形**（项目里已验证的做法）

module DshParts
  module_function

  # ──────────────────────────────────────────────────────────── 基础

  def mm(v)
    v.to_f / 25.4
  end

  # 实体矩形 → 盒子。**扁平命名**：SketchUp 里套母组容易出问题
  # （实测 `sub.move_to(parent)` 静默失败，母组是空的），所以一律平铺。
  def box(ents, x0, y0, x1, y1, z0, h, name)
    pts = [
      Geom::Point3d.new(mm(x0), mm(y0), mm(z0)),
      Geom::Point3d.new(mm(x1), mm(y0), mm(z0)),
      Geom::Point3d.new(mm(x1), mm(y1), mm(z0)),
      Geom::Point3d.new(mm(x0), mm(y1), mm(z0))
    ]
    face = ents.add_face(pts)
    raise "box(#{name}) 无法成面：参数退化 (#{x0},#{y0})-(#{x1},#{y1})" if face.nil?
    g = ents.add_group(face)
    # pushpull 方向按法线判，否则会往下长（踩过：F1-地板长到 z=-100）
    face.pushpull(face.normal.z >= 0 ? mm(h) : -mm(h))
    g.name = name
    g
  end

  # ──────────────────────────────────────────────────────────── 墙

  # 带洞口的墙。
  #
  # axis      'h' 水平墙（at 是 y）/ 'v' 竖直墙（at 是 x）
  # at        墙轴线位置
  # span      [起, 止]（沿墙方向的面线范围）
  # openings  [{ a:, b:, kind: 'door'|'window', sill:, height: }]
  #           a/b 是**沿墙方向的绝对坐标**（不是 u —— 见文件头说明）
  #
  # 返回 { solids: n, glass: n, frames: n }
  def wall(ents, name, axis, at, th, span, z0, h, openings = [],
           door_h: 2100.0, mat_wall: nil, mat_glass: nil, mat_frame: nil)
    lo, hi = span.map(&:to_f)
    ops = Array(openings).map { |o| { a: o[:a].to_f, b: o[:b].to_f,
                                      kind: (o[:kind] || 'door').to_s,
                                      sill: (o[:sill] || 0).to_f,
                                      height: o[:height] } }
                        .sort_by { |o| o[:a] }
    # 校验：洞口必须在墙范围内，且不重叠（越界的洞会静默做错）
    ops.each do |o|
      if o[:a] < lo - 0.01 || o[:b] > hi + 0.01
        raise "墙 #{name} 的洞口 #{o[:a]}..#{o[:b]} 超出墙范围 #{lo}..#{hi}"
      end
    end
    ops.each_cons(2) do |x, y|
      raise "墙 #{name} 的洞口重叠：#{x[:b]} > #{y[:a]}" if x[:b] > y[:a] + 0.01
    end

    solid = ->(a, b, z, hh, tag) do
      return if b - a < 0.5 || hh < 0.5
      g = if axis == 'h'
            box(ents, a, at - th / 2.0, b, at + th / 2.0, z, hh, "#{name}-#{tag}")
          else
            box(ents, at - th / 2.0, a, at + th / 2.0, b, z, hh, "#{name}-#{tag}")
          end
      g.material = mat_wall if mat_wall
      g
    end

    # 墙段（洞口之间的实墙）
    cur, n = lo, 0
    ops.each do |o|
      if o[:a] - cur > 0.5
        n += 1
        solid.call(cur, o[:a], z0, h, format('%02d', n))
      end
      cur = o[:b]
    end
    if hi - cur > 0.5
      n += 1
      solid.call(cur, hi, z0, h, format('%02d', n))
    end

    # 洞口构件
    gcount = fcount = 0
    ops.each_with_index do |o, i|
      top = o[:height] ? (z0 + o[:height]) : (z0 + h)
      # 门楣 / 窗上墙（洞口顶到墙顶之间）
      if z0 + h - top > 0.5
        solid.call(o[:a], o[:b], top, z0 + h - top, "楣#{i + 1}")
      end
      next if o[:kind] == 'door'      # **门只留洞**（用户明确：门不该变成窗）
      # 窗：窗台墙 + 玻璃 + 上下框
      sill = o[:sill]
      if sill > 0.5
        solid.call(o[:a], o[:b], z0, sill, "窗台下#{i + 1}")
      end
      gh = top - (z0 + sill) - 120
      if gh > 0.5
        gl = if axis == 'h'
               box(ents, o[:a], at - 25, o[:b], at + 25, z0 + sill + 60, gh, "#{name}-玻璃#{i + 1}")
             else
               box(ents, at - 25, o[:a], at + 25, o[:b], z0 + sill + 60, gh, "#{name}-玻璃#{i + 1}")
             end
        gl.material = mat_glass if mat_glass
        gcount += 1
      end
      [z0 + sill, top - 60].each_with_index do |fz, k|
        next if fz < z0 - 0.5
        fr = if axis == 'h'
               box(ents, o[:a], at - th / 2.0, o[:b], at + th / 2.0, fz, 60, "#{name}-窗框#{k + 1}-#{i + 1}")
             else
               box(ents, at - th / 2.0, o[:a], at + th / 2.0, o[:b], fz, 60, "#{name}-窗框#{k + 1}-#{i + 1}")
             end
        fr.material = mat_frame if mat_frame
        fcount += 1
      end
    end
    { solids: n, glass: gcount, frames: fcount }
  end

  # ──────────────────────────────────────────────────────────── 楼板（挖洞）

  # 带洞楼板：**不用布尔运算**，把带洞矩形拆成若干无重叠矩形。
  # 踩过：`sub.move_to(parent)` 静默失败（母组是空的，板只剩第一块），
  # 所以这里**平铺**输出，名字带序号。
  # 验证方式必须是**量总面积**，不是看有没有报错。
  def slab_with_holes(ents, name, x0, y0, x1, y1, z, th, holes, mat: nil)
    hs = Array(holes).map { |h| [h[0].to_f, h[1].to_f, h[2].to_f, h[3].to_f] }
                     .select { |a, b, c, d| c > x0 && a < x1 && d > y0 && b < y1 }
    if hs.empty?
      g = box(ents, x0, y0, x1, y1, z, th, name)
      g.material = mat if mat
      return [g]
    end
    xs = ([x0, x1] + hs.flat_map { |h| [h[0], h[2]] }).uniq.sort
    ys = ([y0, y1] + hs.flat_map { |h| [h[1], h[3]] }).uniq.sort
    out = []
    ys.each_cons(2) do |ya, yb|
      next if yb - ya < 0.5
      xs.each_cons(2) do |xa, xb|
        next if xb - xa < 0.5
        mx, my = (xa + xb) / 2.0, (ya + yb) / 2.0
        next if hs.any? { |h| h[0] <= mx && mx <= h[2] && h[1] <= my && my <= h[3] }
        g = box(ents, xa, ya, xb, yb, z, th, format('%s-%02d', name, out.size + 1))
        g.material = mat if mat
        out << g
      end
    end
    out
  end

  # ──────────────────────────────────────────────────────────── 螺旋楼梯

  # 螺旋楼梯：中柱 + 若干扇形踏面。
  #
  # 踩过的坑：第一版把每级做成"绕中心的小盒子"，16 级每级只占 22.5°，
  # 踏面宽 118mm —— 顶视看是**一片薄片堆叠**，根本不像楼梯。
  # 正确的做法是**扇形**：每级一条从中心扫出去的扇形面，再向下推拉成板。
  # 转角也要够（这里默认 420°，16 级每级 26°）。
  def spiral_stair(ents, name, cx, cy, radius, z0, z1,
                   steps: 16, total_deg: 420.0, tread_th: 70.0,
                   col_r: 90.0, mat: nil, mat_col: nil, segments: 12)
    rise = (z1 - z0) / steps.to_f
    sweep = total_deg / steps.to_f
    col = box(ents, cx - col_r, cy - col_r, cx + col_r, cy + col_r, z0,
              z1 - z0, "#{name}-中柱")
    col.material = mat_col if mat_col
    made = 0
    steps.times do |i|
      a0 = i * sweep
      a1 = a0 + sweep + 4.0        # 稍微重叠，避免出现缝
      ztop = z0 + (i + 1) * rise
      pts = [Geom::Point3d.new(mm(cx), mm(cy), mm(ztop))]
      segments.times do |k|
        ang = (a0 + (a1 - a0) * k / (segments - 1).to_f) * Math::PI / 180.0
        pts << Geom::Point3d.new(mm(cx + radius * Math.cos(ang)),
                                 mm(cy + radius * Math.sin(ang)),
                                 mm(ztop))
      end
      face = ents.add_face(pts)
      next if face.nil?
      g = ents.add_group(face)
      g.name = "#{name}-踏#{format('%02d', i + 1)}"
      face.pushpull(-mm(tread_th))
      g.material = mat if mat
      made += 1
    end
    { steps: made, rise: rise, top: z0 + steps * rise }
  end

  # ──────────────────────────────────────────────────────────── 材质

  # 取或建材质。**名字不存在时不抛异常**（踩过：直接抛 ArgumentError 让整个构建失败）
  def mat(model, name, rgb, alpha = nil)
    m = model.materials[name] || model.materials.add(name)
    m.color = Sketchup::Color.new(*rgb)
    m.alpha = alpha if alpha
    m
  end

  # 按组名前缀批量上材质。返回实际刷了多少组。
  # 用于"墙全刷银、地面全刷棕"这种整体要求，避免漏刷。
  def paint(groups, mat, *prefixes)
    n = 0
    groups.each do |g|
      nm = g.name.to_s
      next unless prefixes.any? { |p| nm.start_with?(p) || nm.include?(p) }
      g.material = mat
      n += 1
    end
    n
  end
end
