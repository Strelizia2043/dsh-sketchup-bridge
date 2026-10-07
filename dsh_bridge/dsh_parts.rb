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

  # ══════════════════════════════════════════════════════════════════
  #  分组契约（**这是模型的骨架，不是可选的美化**）
  # ══════════════════════════════════════════════════════════════════
  #
  # 用户的要求：**每个"大整体"单独一组**，而且组内尽量是一个实体
  # （不是一堆互相穿插的小盒子）。理由很实在：
  #   · 一堆小盒子 → 转角互相重叠、外面全是分割线、面数浪费
  #   · 一个整体   → 干净、面数少、点选/隐藏/上材质都方便
  #
  # 分组顺序按**由下往上**（便于遮挡与理解）。每类内部若跨多个标高，
  # 会再按 z 区间拆子组 —— 因为"轮廓推拉"要求同一组内竖向截面一致。
  CATEGORIES = [
    { key: :floor,     name: 'FL', label: '地板' },
    { key: :mezzanine, name: 'MZ', label: '夹层' },
    { key: :wall_out,  name: 'WO', label: '外墙' },
    { key: :wall_in,   name: 'WI', label: '内墙' },
    { key: :wall_part, name: 'WP', label: '隔墙' },
    { key: :ceiling,   name: 'CE', label: '天花板' },
    { key: :roof,      name: 'RF', label: '屋顶' },
    { key: :eave,      name: 'EV', label: '房檐' },
    { key: :glazing,   name: 'GL', label: '玻璃' },
    { key: :stair,     name: 'ST', label: '楼梯' },
    { key: :railing,   name: 'RA', label: '栏杆' },
    { key: :furniture, name: 'FU', label: '家具' }
  ].freeze

  # 组名：`<前缀>-<标签>`；给了 z 就带标高（同类跨标高时必须带，否则重名）
  def group_name(cat_key, z0 = nil, z1 = nil)
    c = CATEGORIES.find { |x| x[:key] == cat_key }
    raise ArgumentError, "未知类别 #{cat_key}" if c.nil?
    return "#{c[:name]}-#{c[:label]}" if z0.nil?
    format('%s-%s-Z%d_%d', c[:name], c[:label], z0.round, z1.round)
  end

  # 按名字猜墙的类别 —— **只在数据没写 kind 时兜底**。
  # 数据里显式写 `kind` 比猜可靠得多，这里兼容老数据。
  def guess_wall_category(name)
    n = name.to_s
    return :wall_out  if n.include?('外墙') || n.include?('长墙')
    return :wall_part if n.include?('小房间') || n.include?('隔墙')
    :wall_in
  end

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

  # ──────────────────────────────────────── 已淘汰的做法（留个记号）
  #
  # 这里原来有个 solid_union（网格分解 + 贪心合并）：把重叠的盒子切成
  # 不重叠的小格，再合并成大块。**体积能精确核对，但没用**：
  #   · 消掉重叠 ≠ 消掉分割线 —— 洞口的 900/2100 高度会切出新的 z 分界，
  #     块数反而变多（实测 9 → 26）
  #   · 真正要的是一个整体，那用 extrude_profile（轮廓推拉，一次成型）
  #     或 fuse_solids（union 融合）—— 两者都在下面
  # 按项目规矩：**失败的机制要删掉，不留半成品**。所以它被删了，
  # 只留这段说明，免得以后有人（包括我）再想一遍同样的错路。

  # ──────────────────────────────────────────────── 融合成"一整个"实体
  #
  # 用户的要求：别一个构件一个组、别在转角留分割线 —— 要"画底形 + 推拉"
  # 那种**一整个**。实测结论：
  #
  #   · 网格分解（solid_union）**能消重叠，但消不掉分割线**：
  #     洞口的 900/2100 高度会切出新的 z 层，块数反而变多（实测 9 → 26）
  #   · **`Sketchup::Group#union` 才是正解**：两个重叠盒子并成一个，
  #     体积精确（1.5 m³ 分毫不差）、面数从 12 降到 6、连接缝自动消失
  #   · `subtract` **行为不可靠**（三种情形的体积都对不上任何合理解释），
  #     所以洞口仍然用"矩形切分"表达，**不用 subtract**
  #
  # ⚠️ 能力探测：`union` 在 SketchUp 2026 Pro 上有。
  #    它可能是 Pro 专属（实体工具），所以在非 Pro 上会失败 ——
  #    这里**探测 + 回退**：失败就保留原始盒子，不让整个构建崩掉。
  #
  # 返回 { group: 融合体或 nil, fused: 是否成功, parts: 参与块数 }
  def fuse_solids(ents, name, boxes, mat: nil)
    boxes = Array(boxes).compact
    return { group: nil, fused: false, parts: 0 } if boxes.empty?
    return { group: boxes.first, fused: false, parts: 1 } if boxes.size == 1

    # 探测：拿第一个实例问它会不会 union
    unless boxes.first.respond_to?(:union)
      return { group: nil, fused: false, parts: boxes.size,
               reason: '本 SketchUp 没有 Group#union（可能是非 Pro 版）' }
    end

    begin
      cur = boxes.first
      boxes[1..-1].each do |b|
        # ⚠️ union **会消耗掉传入的那个组**（它被并进结果），
        #    所以并完就不能再引用 b 了 —— 实测报过 "reference to deleted Group"。
        cur = cur.union(b)
      end
      # union 可能留下空壳组，清掉
      boxes.each { |b| b.erase! if b.valid? && b != cur }
      cur.name = name
      cur.material = mat if mat
      { group: cur, fused: true, parts: boxes.size }
    rescue StandardError => e
      # 失败就把原始盒子还给调用方（它们可能已被部分消耗，所以重新数一遍）
      alive = boxes.select(&:valid?)
      { group: alive.first, fused: false, parts: alive.size,
        reason: "#{e.class}: #{e.message}" }
    end
  end

  # 用户嘴里说的就是"用 union 把大整体并起来"。名字对上，免得再去翻文档。
  alias union_solids fuse_solids

  # 天花板 / 楼板 / 屋顶 / 房檐 —— 这些"水平大板"全都是**轮廓推拉**：
  # 底面画一次、拉一层高。跟墙用的是同一个函数，这里只是给个好记的名字。
  #
  # 之所以单独给别名：用户明确要求"天花板、屋顶、房檐各分一组"，
  # 用 `ceiling(...)` / `roof(...)` 写出来，读代码的人一眼知道在做什么。
  def ceiling(ents, name, rects, z0, thickness, mat: nil)
    extrude_profile(ents, name, rects, z0, thickness, mat: mat)
  end

  def floor_slab(ents, name, rects, z0, thickness, mat: nil)
    extrude_profile(ents, name, rects, z0, thickness, mat: mat)
  end

  def roof_slab(ents, name, rects, z0, thickness, mat: nil)
    extrude_profile(ents, name, rects, z0, thickness, mat: mat)
  end

  def eave(ents, name, rects, z0, thickness, mat: nil)
    extrude_profile(ents, name, rects, z0, thickness, mat: mat)
  end

  # ────────────────────────────────────────────── 轮廓推拉（一次成型）
  #
  # 用户的思路（**正确且更直接**）：先画出**底轮廓**，再用推拉拉起来 ——
  # 一次成型、没有分割线、面数最少。比"建一堆盒子再 union"更快。
  #
  # 适用条件（唯一一条）：**竖向截面不变**，即从底到顶的平面形状一样。
  #   ✅ 墙（同一标高段，洞口已在外部按高度切好）
  #   ✅ 楼板 / 天花板 / 整体顶板（矩形，可带洞）
  #   ❌ 坡屋顶、楼梯踏步、家具（每段形状不同）
  #
  # 算法四步（每一步都单独验证过）：
  #   ① 网格分解：把矩形集合切成**无重叠**的小格
  #   ② 找边界边：小格的边里"只被一个格用到"的就是轮廓（内部边被用两次）
  #   ③ 接环：**左手法则**——站在顶点上选"相对来路左转最小"的出边
  #      （⚠️ 不能"顺着未用边一直走"：遇到 T 形分支会串到别的环上，
  #        实测"四面墙+内墙"面积算成 17.52 m²，正确是 5.59）
  #   ④ 成面 → 挖洞 → 推拉
  #
  # ⚠️ 成面的陷阱：**容器里不能已有共面几何**，否则 add_face 返回 nil。
  #    所以内部先 new 一个空组再操作；同一位置重复调用也会失败（要换个组）。
  #
  # rects:  [[x0, y0, x1, y1], ...]  同标高的矩形（毫米）
  # 返回   { group:, area_m2:, holes:, volume_m3:, manifold: } 或 { error: }
  def extrude_profile(ents, name, rects, z0, height, mat: nil)
    rs = Array(rects).map { |r| r.map(&:to_f) }
                     .select { |x0, y0, x1, y1| x1 - x0 > 0.1 && y1 - y0 > 0.1 }
    return { error: '没有有效的矩形' } if rs.empty?

    # ① 网格分解
    xs = rs.flat_map { |r| [r[0], r[2]] }.uniq.sort
    ys = rs.flat_map { |r| [r[1], r[3]] }.uniq.sort
    cells = {}
    ys.each_cons(2) do |ya, yb|
      xs.each_cons(2) do |xa, xb|
        mx = (xa + xb) / 2.0
        my = (ya + yb) / 2.0
        next unless rs.any? { |r| r[0] <= mx && mx <= r[2] && r[1] <= my && my <= r[3] }
        cells[[xa, ya]] = [xa, ya, xb, yb]
      end
    end
    return { error: '网格分解后没有实心格' } if cells.empty?

    # ② 边界边（有向：外轮廓逆时针）
    # ⚠️ **必须按坐标索引找邻居，不能用 ya - 1**。
    #
    # 踩过：网格坐标是 0/100/8150/8250 这类**任意值**，不是单位步长，
    # 所以 cells.key?([xa, ya - 1]) 永远找不到下方邻居 →
    # 每条边都被当成边界 → 环判错、洞数虚高、面数虚高。
    # 正确做法：先建坐标值 → 索引的表，再按索引 ±1 找。
    xi = {}; xs.each_with_index { |v, k| xi[v] = k }
    yi = {}; ys.each_with_index { |v, k| yi[v] = k }
    edges = []
    cells.each_value do |xa, ya, xb, yb|
      i = xi[xa]; j = yi[ya]
      below = (j > 0) && cells.key?([xa, ys[j - 1]])
      above = (j + 1 < ys.size) && cells.key?([xa, ys[j + 1]])
      left  = (i > 0) && cells.key?([xs[i - 1], ya])
      right = (i + 1 < xs.size) && cells.key?([xs[i + 1], ya])
      edges << [xa, ya, xb, ya] unless below    # 下边
      edges << [xb, ya, xb, yb] unless right    # 右边
      edges << [xb, yb, xa, yb] unless above    # 上边
      edges << [xa, yb, xa, ya] unless left     # 左边
    end

    # ③ 左手法则接环
    outs = Hash.new { |h, k| h[k] = [] }
    edges.each { |ax, ay, bx, by| outs[[ax, ay]] << [bx, by] }
    used = {}
    loops = []
    edges.each do |ax, ay, bx, by|
      next if used[[ax, ay, bx, by]]
      pts = [[ax, ay]]
      cur = [ax, ay]
      nxt = [bx, by]
      ok = true
      while pts.size <= 20_000
        used[[cur[0], cur[1], nxt[0], nxt[1]]] = true
        break if nxt == pts.first
        pts << nxt
        back = Math.atan2(cur[1] - nxt[1], cur[0] - nxt[0])
        cands = (outs[nxt] || []).reject { |p| used[[nxt[0], nxt[1], p[0], p[1]]] }
        if cands.empty?
          ok = false
          break
        end
        best = nil
        best_ang = nil
        cands.each do |p|
          ang = Math.atan2(p[1] - nxt[1], p[0] - nxt[0]) - back
          ang += 2 * Math::PI while ang < 0
          ang -= 2 * Math::PI while ang >= 2 * Math::PI
          ang = 2 * Math::PI if ang < 1e-9
          if best_ang.nil? || ang < best_ang
            best_ang = ang
            best = p
          end
        end
        cur = nxt
        nxt = best
      end
      loops << pts if ok && pts.size >= 3
    end
    return { error: '没找到闭合轮廓' } if loops.empty?

    # ⚠️ **必须去掉共线的中间点** —— 这是"外面为什么有分割线"的根因：
    # 网格分解会把一条直边切成多点（如 12 点的矩形：每边中间多一个分界点），
    # 推拉后**每两点之间生成一个竖直面** → 外表面被切成 12 片，
    # 视觉上就是一道道分割线（实测 18 面 / 48 边，用户一眼就看出来了）。
    # 去掉共线点后：矩形回到 4 点 → 6 面，外面干净。
    loops = loops.map { |lp| simplify_loop(lp) }
    areas = loops.map { |lp| signed_area_mm(lp) }
    oi = areas.each_with_index.max_by { |a, _| a.abs }[1]
    # ⚠️ **不能只取"最大的那个环"当外轮廓**。
    #
    # 踩过：当墙被洞口切成**多块不相连**的形状时（L1 外墙的落地玻璃就是），
    # 面积最大的是整栋的外包围盒，而那几个真正的墙段被当成"洞"剪掉 ——
    # 结果体积算成 -0.000（全被挖空）。
    #
    # 正解：**按绕向分类**。边界边是有向的（逆时针绕实心区），于是：
    #   · 逆时针（面积 > 0）= 外轮廓
    #   · 顺时针（面积 < 0）= 洞
    # 多个外轮廓说明形状不连通，各自推拉即可。
    outer_loops = loops.each_with_index.select { |_, i| areas[i] > 0 }.map { |lp, _| lp }
    hole_loops  = loops.each_with_index.select { |_, i| areas[i] < 0 }.map { |lp, _| lp }
    outer_loops = [loops[oi]] if outer_loops.empty?     # 兜底

    # ④ 成面（必须在**空容器**里）
    g = ents.add_group
    g.name = name
    ge = g.definition.entities
    to3d = lambda do |lp, z|
      lp.map { |p| Geom::Point3d.new(mm(p[0]), mm(p[1]), mm(z)) }
    end

    made = 0
    outer_loops.each do |lp|
      f = ge.add_face(to3d.call(lp, z0))
      made += 1 if f
    end
    if made.zero?
      g.erase!
      return { error: '外轮廓成面失败（容器里可能已有共面几何）' }
    end
    hole_loops.each do |lp|
      hf = ge.add_face(to3d.call(lp, z0))
      hf.erase! if hf          # 只擦面、保留边 → 外面上出现洞
    end

    faces = ge.grep(Sketchup::Face)
    # ⚠️ 面数**可能是多个**：形状被洞口切成几块不相连时，每块各自成一面。
    # 第一版断言"必须恰好 1 个面"，那会误伤这种完全正常的情况。
    if faces.empty?
      g.erase!
      return { error: '成面后一个面都没有' }
    end
    # ⚠️ pushpull 是沿**面法线**方向。法线朝下时就往下长（实测 L1 的墙
    # 长成了 Z -2700..0）。所以先判法线，朝下就推负值。
    faces.each do |pf|
      dir = pf.normal.z >= 0 ? 1.0 : -1.0
      pf.pushpull(dir * mm(height))
    end
    g.material = mat if mat

    net = outer_loops.sum { |lp| signed_area_mm(lp).abs } -
          hole_loops.sum { |lp| signed_area_mm(lp).abs }
    { group: g,
      outer_pts: (outer_loops.first ? outer_loops.first.size : 0),
      outers: outer_loops.size, holes: hole_loops.size,
      area_m2: net / 1e6,
      volume_m3: (g.volume * (25.4**3) / 1e9 rescue nil),
      manifold: (g.manifold? rescue nil),
      faces: ge.grep(Sketchup::Face).size }
  end

  # 去掉环里**共线的中间点**。
  #
  # 为什么必须做：网格分解会把一条直边切成多点（6000 长的墙 → 240/5760 处各多一个点），
  # 这些点推进 3D 后每两点之间就生成一个竖直面 ——
  # **外表面被切成一片片，看着就是分割线**（用户直接指出来了）。
  # 去掉共线点：12 点的矩形回到 4 点 → 外表面一片到底。
  #
  # 判据：三点共线（叉积接近 0）就删中间那个。
  def simplify_loop(pts, tol = 1.0)
    return pts if pts.size <= 3
    pts = pts.dup
    out = []
    n = pts.size
    n.times do |i|
      a = pts[(i - 1) % n]
      b = pts[i]
      c = pts[(i + 1) % n]
      cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
      out << b if cross.abs > tol          # 有拐弯 → 保留
    end
    out.size >= 3 ? out : pts
  end

  # 顶点列表的有向面积（mm²）：> 0 逆时针（外轮廓），< 0 顺时针（洞）
  def signed_area_mm(pts)
    a = 0.0
    pts.each_with_index do |p, i|
      q = pts[(i + 1) % pts.size]
      a += p[0] * q[1] - q[0] * p[1]
    end
    a / 2.0
  end

  # ══════════════════════════════════════ 墙：实体分组构建（正式入口）
  #
  # 把一批墙按**类别 + 标高**分组，每组一次 `extrude_profile` 推拉成型。
  # 这是"分类整体"模型的正式做法，替代以前"每面墙一个盒子"。
  #
  # 处理顺序：
  #   ① 相接的墙端延伸（填满墙角）—— 延伸量有上限，且**钳进建筑包围盒**
  #   ② 按洞口切分：通高洞口 → 轮廓里断开；有窗台的洞 → 沿 z 分层
  #   ③ 按 (类别, z0, z1) 归桶
  #   ④ 每桶一次轮廓推拉 → 一个整体组
  #
  # ⚠️ 三个已经踩过的坑，别再犯：
  #   · 延伸量**不能**用 `max(自身半厚, reach)` —— 那会在"端点已贴在
  #     对方外皮"时仍然多伸半个墙厚，把墙推出建筑轮廓（实测 y=-50）
  #   · 延伸量**不能**取"所有接触墙的横向最大距离" —— 会跑到 X=2050
  #   · 洞口字段**有 `u` 和 `abs` 两种**，只认一个会静默把洞口填实
  #
  # walls:   [{ 'name', 'from'=>[x,y], 'to'=>[x,y], 'thickness', 'height',
  #             'base_z', 'kind'(可省), 'openings'=>[...] }, ...]
  # 返回     [{ category:, z0:, z1:, group:, volume_m3:, want:, ok: }, ...]
  def build_walls(ents, walls, envelope: nil, mat: nil)
    ws = Array(walls)
    return [] if ws.empty?
    env = envelope || wall_envelope(ws)
    exts = wall_end_extensions(ws, env)

    buckets = Hash.new { |h, k| h[k] = [] }
    ws.each_with_index do |w, i|
      cat = wall_category_of(w)
      wall_blocks(w, exts[i][0], exts[i][1], env).each do |rect, za, zb|
        buckets[[cat, za.round, zb.round]] << rect
      end
    end

    out = []
    buckets.sort_by { |(cat, za, _), _| [CATEGORIES.index { |c| c[:key] == cat } || 99, za] }
           .each do |(cat, za, zb), rects|
      name = group_name(cat, za, zb)
      r = extrude_profile(ents, name, rects, za, zb - za, mat: mat)
      want = rect_area(rects) / 1e6 * (zb - za) / 1000.0
      r = r.merge(category: cat, z0: za, z1: zb, want: want,
                  ok: r[:volume_m3] && (r[:volume_m3] - want).abs < 0.01)
      out << r
    end
    out
  end

  # 墙的类别：先看数据里的 `kind`，没写才按名字猜。
  #
  # ⚠️ 这里踩过坑，所以加了一层语义别名。
  #
  # `kind` 这个字段名和 `CATEGORIES` 的键**撞车**了：契约里的合法键是
  # `wall_out` / `wall_in` / `wall_part`，但写数据的人（包括我自己）
  # 很自然会写 `outer` / `inner` —— 那不是类别键，于是 `group_name`
  # 直接抛 `ArgumentError: 未知类别 outer`，**整个墙体分支挂掉、回退到逐块做法**，
  # 而且错误被 rescue 吞进报告里，外面只看到"墙没分组"，很难查。
  #
  # 所以：语义别名先映射，映射不到的**才**抛（不静默兜底 —— 那样会错得没边）。
  KIND_ALIAS = {
    'outer' => :wall_out, 'exterior' => :wall_out, '外墙' => :wall_out,
    'inner' => :wall_in,  'interior' => :wall_in,  '内墙' => :wall_in,
    'partition' => :wall_part, '隔墙' => :wall_part,
  }.freeze

  def wall_category_of(w)
    k = w['kind']
    return guess_wall_category(w['name']) if k.nil? || k.to_s.empty?
    s = k.to_s
    sym = KIND_ALIAS[s] || KIND_ALIAS[s.downcase] || s.to_sym
    unless CATEGORIES.any? { |c| c[:key] == sym }
      raise ArgumentError,
            "墙 #{w['name']} 的 kind=#{k.inspect} 不是合法类别；" \
            "可用：#{CATEGORIES.map { |c| c[:key] }.join(', ')}，" \
            "或语义别名：#{KIND_ALIAS.keys.join(', ')}"
    end
    sym
  end

  # 矩形集合的并集面积（mm²）—— 用网格中点判定，和 extrude_profile 同一套逻辑
  def rect_area(rects)
    xs = rects.flat_map { |r| [r[0], r[2]] }.uniq.sort
    ys = rects.flat_map { |r| [r[1], r[3]] }.uniq.sort
    a = 0.0
    ys.each_cons(2) do |ya, yb|
      xs.each_cons(2) do |xa, xb|
        mx = (xa + xb) / 2.0
        my = (ya + yb) / 2.0
        next unless rects.any? { |q| q[0] <= mx && mx <= q[2] && q[1] <= my && my <= q[3] }
        a += (xb - xa) * (yb - ya)
      end
    end
    a
  end

  # 建筑包围盒：所有墙外皮的范围 [[xmin,xmax],[ymin,ymax]]
  def wall_envelope(walls)
    xs = []
    ys = []
    walls.each do |w|
      fr = w['from'].map(&:to_f)
      to = w['to'].map(&:to_f)
      t = w['thickness'].to_f / 2.0
      if (to[0] - fr[0]).abs < 1e-6
        xs << fr[0] - t << fr[0] + t
        ys << [fr[1], to[1]].min - t << [fr[1], to[1]].max + t
      else
        xs << [fr[0], to[0]].min - t << [fr[0], to[0]].max + t
        ys << fr[1] - t << fr[1] + t
      end
    end
    [[xs.min, xs.max], [ys.min, ys.max]]
  end

  def clamp(v, a, b)
    v < a ? a : (v > b ? b : v)
  end

  # 每面墙两端的延伸量。
  #
  # 判据（**这是唯一说得清的一条**）：端点贴在别的墙上时，
  # 沿本墙方向走多远才能从**对方体内**出来。
  # 把本墙方向与对方方向解一个小方程即可；再夹两条硬约束：
  #   ① 上限 = 自身半厚 + 对方半厚（防病态值）
  #   ② 结果不许把矩形推出建筑包围盒（越界就钳）
  def wall_end_extensions(walls, env = nil, tol = 60.0)
    env ||= wall_envelope(walls)
    walls.each_with_index.map do |w, i|
      fr = w['from'].map(&:to_f)
      to = w['to'].map(&:to_f)
      vx = to[0] - fr[0]
      vy = to[1] - fr[1]
      len = Math.hypot(vx, vy)
      next [0.0, 0.0] if len < 1e-6
      ux = vx / len
      uy = vy / len
      t_self = w['thickness'].to_f / 2.0

      [0, 1].map do |which|
        dir = which.zero? ? -1.0 : 1.0     # from 端往反方向伸，to 端往正方向
        pt = which.zero? ? fr : to
        best = 0.0
        walls.each_with_index do |o, j|
          next if j == i
          ofr = o['from'].map(&:to_f)
          oto = o['to'].map(&:to_f)
          ox = oto[0] - ofr[0]
          oy = oto[1] - ofr[1]
          olen = Math.hypot(ox, oy)
          next if olen < 1e-6
          h_o = o['thickness'].to_f / 2.0
          dx = pt[0] - ofr[0]
          dy = pt[1] - ofr[1]
          cross = (dx * oy - dy * ox) / olen          # 到对方轴线的有向距离
          next if cross.abs > h_o + tol               # 没贴在这道墙上
          rate = (dir * ux * oy - dir * uy * ox) / olen
          next if rate.abs < 1e-9
          far = h_o * (cross >= 0 ? 1.0 : -1.0)       # 对方**远侧**边线
          s = (far - cross) / rate
          s = clamp(s, 0.0, t_self + h_o)
          best = s if s > best
        end
        # 夹到包围盒内：伸出去多少就退回多少
        lim = if which.zero?
                (dir * ux).abs > 0.5 ? (pt[0] - env[0][0]) / (dir * ux).abs \
                                     : (pt[1] - env[1][0]) / (dir * uy).abs
              else
                (dir * ux).abs > 0.5 ? (env[0][1] - pt[0]) / (dir * ux).abs \
                                     : (env[1][1] - pt[1]) / (dir * uy).abs
              end
        [best, [lim, 0.0].max].min
      end
    end
  end

  # 一面墙 → [(矩形, z0, z1), ...]
  #
  # 洞口两种表达都要认：
  #   · `abs` = [沿墙起, 沿墙止]（绝对坐标，推荐）
  #   · `u` / `at` + `width`（沿墙局部坐标，从 from 端量起）
  # 只认一种会**静默把洞口填实**（实测：体积变成完整环、玻璃洞消失）。
  def wall_blocks(w, ef, et, env)
    fr = w['from'].map(&:to_f)
    to = w['to'].map(&:to_f)
    vx = to[0] - fr[0]
    vy = to[1] - fr[1]
    len = Math.hypot(vx, vy)
    ux = vx / len
    uy = vy / len
    a = [fr[0] - ux * ef, fr[1] - uy * ef]
    b = [to[0] + ux * et, to[1] + uy * et]
    t = w['thickness'].to_f / 2.0
    vertical = (b[0] - a[0]).abs < 1e-6
    r = if vertical
          [a[0] - t, [a[1], b[1]].min, a[0] + t, [a[1], b[1]].max]
        else
          [[a[0], b[0]].min, a[1] - t, [a[0], b[0]].max, a[1] + t]
        end
    # 硬约束：钳进包围盒（防止任何计算误差把墙推出轮廓）
    r = [clamp(r[0], env[0][0], env[0][1]), clamp(r[1], env[1][0], env[1][1]),
         clamp(r[2], env[0][0], env[0][1]), clamp(r[3], env[1][0], env[1][1])]

    z0 = (w['base_z'] || 0).to_f
    top = z0 + w['height'].to_f
    ops = w['openings'] || []
    return [[r, z0, top]] if ops.empty?

    lo = vertical ? r[1] : r[0]
    hi = vertical ? r[3] : r[2]
    spans = ops.map do |o|
      s0 = if o['abs']
             o['abs'][0].to_f
           else
             lo + (o['u'] || o['at']).to_f
           end
      [s0, s0 + o['width'].to_f, o]
    end.sort_by { |x| x[0] }

    cuts = ([lo, hi] + spans.flat_map { |s0, s1, _| [s0, s1] }).uniq.sort
    out = []
    cuts.each_cons(2) do |sa, sb|
      next if sb - sa < 1
      mid = (sa + sb) / 2.0
      seg = vertical ? [r[0], sa, r[2], sb] : [sa, r[1], sb, r[3]]
      hit = spans.find { |s0, s1, _| s0 <= mid && mid <= s1 }
      if hit.nil?
        out << [seg, z0, top]
      else
        o = hit[2]
        sill = o['sill'].to_f
        oh = o['height'].to_f
        oh = w['height'].to_f if oh <= 0
        otop = [z0 + sill + oh, top].min
        # 通高洞口（窗台 0 且到顶）→ 这一段整片没有墙（轮廓里就是缺口）
        next if sill <= 1 && otop >= top - 1
        out << [seg, z0, z0 + sill] if sill > 1          # 窗台下
        out << [seg, otop, top] if top - otop > 1        # 门楣 / 过梁
      end
    end
    out
  end

  # ══════════════════════════════ 水平大板：分组入口（天花板/屋顶/房檐）
  #
  # 用户明确要求："天花板、房檐、屋顶这些也要自己单独分一组，
  # 因为**这些也算大整体**"。
  #
  # 和墙一样：按类别 + 标高分组，每组一次轮廓推拉成型。
  # 一个"板"的输入形状有三种，都要认：
  #   · `rects`  → 直接给矩形列表（最省事，带洞就用 4 块围一圈）
  #   · `polygon`+`holes` → 给轮廓和洞（楼板/天花最常见的表达）
  #   · `polys`  → 多个多边形（屋顶可能有几段）
  #
  # slabs: [{ 'category' => 'ceiling'|'roof'|'eave'|'floor'|'mezzanine',
  #            'z' | 'z0', 'thickness',
  #            'rects' | ('polygon' + 'holes'),
  #            'name'（可选，不给就按契约生成） }, ...]
  #
  # 返回 [{ category:, z0:, z1:, group:, volume_m3:, want:, ok: }, ...]
  def build_slabs(ents, slabs, mat: nil)
    out = []
    Array(slabs).each do |s|
      cat = (s['category'] || s['kind'] || 'ceiling').to_sym
      unless CATEGORIES.any? { |c| c[:key] == cat }
        out << { category: cat, error: "未知类别 #{cat}" }
        next
      end
      z0 = (s['z0'] || s['z'] || 0).to_f
      th = (s['thickness'] || 100).to_f
      rects = slab_rects(s)
      if rects.empty?
        out << { category: cat, error: '没算出任何矩形（检查 rects / polygon+holes）' }
        next
      end
      name = s['name'] || group_name(cat, z0, z0 + th)
      r = extrude_profile(ents, name, rects, z0, th, mat: mat)
      want = rect_area(rects) / 1e6 * th / 1000.0
      out << r.merge(category: cat, z0: z0, z1: z0 + th, want: want,
                     ok: r[:volume_m3] && (r[:volume_m3] - want).abs < 0.01)
    end
    out
  end

  # 把三种输入形状统一折算成矩形列表
  #
  # ⚠️ `polygon` + `holes` 的算法：**只支持轴对齐的矩形洞**，
  # 按"洞的四条边线"把大矩形切成 4 条带 —— 多于一个洞时会不准。
  # 需要多个洞时请直接给 `rects`（那是精确表达）。
  # 之所以不在这里做通用的多边形布尔：那需要完整的并集算法，
  # 而 extrude_profile 本身就能正确处理多个矩形，代价只是多写几行数据。
  def slab_rects(s)
    if s['rects'] && !Array(s['rects']).empty?
      return Array(s['rects']).map { |r| r.map(&:to_f) }
    end
    poly = s['polygon']
    return [] if poly.nil? || poly.length < 3
    xs = poly.map { |p| p[0].to_f }
    ys = poly.map { |p| p[1].to_f }
    x0 = xs.min; x1 = xs.max; y0 = ys.min; y1 = ys.max
    holes = Array(s['holes']).map { |h| h.map(&:to_f) }
    return [[x0, y0, x1, y1]] if holes.empty?

    # 用洞的边界线把大矩形切成网格，取不在任何洞内的格
    hx = holes.flat_map { |h| [h[0], h[2]] }.uniq.sort
    hy = holes.flat_map { |h| [h[1], h[3]] }.uniq.sort
    gx = ([x0, x1] + hx).uniq.sort
    gy = ([y0, y1] + hy).uniq.sort
    out = []
    gy.each_cons(2) do |ya, yb|
      gx.each_cons(2) do |xa, xb|
        next if xb - xa < 0.5 || yb - ya < 0.5
        mx = (xa + xb) / 2.0
        my = (ya + yb) / 2.0
        next if holes.any? { |h| h[0] <= mx && mx <= h[2] && h[1] <= my && my <= h[3] }
        out << [xa, ya, xb, yb]
      end
    end
    out
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
