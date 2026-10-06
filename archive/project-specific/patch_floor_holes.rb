# 给 build_from_plan.rb 的 build_floor 加**洞口支持**（中庭、楼梯井要用）
#
# 背景：原来 build_floor 只认 polygon，且用 room_bounds(poly) 取**包围盒**建板，
# 所以哪怕 polygon 写成带内圈的样子也会被填实。
#
# 本图的真实需求：用户明确说"中间这一块是没有地板的"（采光中庭），
# 所以一二层楼板都必须挖掉一块。楼梯井同理。
#
# 做法沿用项目里已验证的思路：**不用布尔运算，把带洞矩形拆成若干无重叠矩形**。
#   水平切分：把所有洞口的 y 边界作为切线，切成若干水平带；
#   每条带内，按洞口的 x 区间切出实心矩形。
p = "E:/deepseek工作区/sketchup-bridge/build_from_plan.rb"
s = File.read(p, encoding: "UTF-8")

anchor = "  def build_floor(ents, slab)\n"
raise "找不到 build_floor" unless s.include?(anchor)

helper = <<-'RB'
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

RB
s = s.sub(anchor, helper + anchor)

old = <<-'RB'
    if th > 0
      # 用 box_on_ground：方向由法线判断统一处理，不会像直接 pushpull 那样
      # 可能把板推到 z 以下（我第一版就是这样，F1-地板 长到了 z=-100）。
      #
      # 关于标高语义：楼板**顶面在 z**（z 就是楼面完成面标高），板体向"室内方向"长，
      # 也就是 z..z+th。早先写成 z-th 会让整块地板挂在地面以下 —— 那只是把错误
      # 从 z=-100 换个方向，仍然是错的。
      box_on_ground(ents, b[:x0], b[:y0], b[:x1], b[:y1], th, name, z)
RB
raise "找不到 build_floor 的建板分支" unless s.include?(old)

new = <<-'RB'
    # 有 holes 时：拆成多个无重叠矩形，逐个建（中庭 / 楼梯井就靠这个）
    holes = Array(slab['holes'])
    if holes.any?
      rects = floor_with_holes(b[:x0], b[:y0], b[:x1], b[:y1], holes)
      if rects.length == 1
        box_on_ground(ents, rects[0][0], rects[0][1], rects[0][2], rects[0][3],
                      th, name, z)
      else
        # 多个矩形 → 各自成一个组，再装进一个母组，名字统一。
        # 为什么不直接建成一个带内圈的面：pushpull 对带内圈的面行为不稳，
        # 而且项目里已有"拆矩形"的成熟做法（slab_decomposition）。
        parent = ents.add_group
        parent.name = name
        rects.each_with_index do |(rx0, ry0, rx1, ry1), i|
          sub = box_on_ground(ents, rx0, ry0, rx1, ry1, th, '', z)
          sub.name = "#{name}-#{format('%02d', i + 1)}"
          sub.move_to(parent)
        end
        parent
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
RB
raise "找不到地板函数体定位" unless s.include?(old)
s = s.sub(old, new)
# 原来的 else 分支会被留下，删掉它
s = s.sub(new + <<-'RB2', new)
    else
      pts = poly.map { |p| Geom::Point3d.new(mm(p[0]), mm(p[1]), mm(z)) }
      face = ents.add_face(pts)
      raise "楼板 #{name} 无法成面（点可能共线或自交）" if face.nil?
      g = ents.add_group(face)
      g.name = name
      g
    end
RB2
File.write(p, s, encoding: "UTF-8")
puts "  已给 build_floor 加入 holes 支持（拆矩形，不用布尔运算）"

