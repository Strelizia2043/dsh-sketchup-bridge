# view_modes.rb -- 审查视图模式
#
# 解决一个反复出现的实际问题：
#   模型建好后，"从上往下看平面布局"是最常用的审查方式，
#   但房间**天花板**、**夹层楼板**、**立面轮廓**会把内部盖住——
#   我为此手工隐藏过 64 个组，而且差点忘了恢复，给你留了个残缺模型。
#
# 所以把它做成可复用的功能：一次性切换视图模式，并保证可完整还原。
#
# 只操作 group.hidden，不删任何东西，不改变几何。

module DshView
  # 每个模式 = 需要隐藏的组名前缀/正则
  MODES = {
    # 全部可见（交付时用）
    'full' => [],
    # 平面审查：隐藏天花、夹层楼板、立面轮廓、门窗扇框 → 露出墙、地面、楼梯
    'open' => [/-天花$/, /^F2-/, /^E-/, /-框\d$/, /-上槛$/, /-下槛$/, /-玻璃$/, /-门扇$/],
    # 只看结构：隐藏所有门窗扇框 + 天花
    'structure' => [/-天花$/, /-框\d$/, /-上槛$/, /-下槛$/, /-玻璃$/, /-门扇$/, /^E-/],
    # 只看标高 z 及以下（分层审查）
    'level' => []
  }.freeze

  module_function

  def all(entities)
    found = []
    entities.grep(Sketchup::Group).each do |g|
      found << g
      found.concat(nested(g))
    end
    found
  end

  def nested(group, depth = 0)
    return [] if depth > 3
    out = []
    group.definition.entities.grep(Sketchup::Group).each do |g|
      out << g
      out.concat(nested(g, depth + 1))
    end
    out
  end

  # 返回 { name:, hidden:, shown:, mode: }
  def set(model, mode, z_limit = nil)
    raise "未知视图模式 #{mode.inspect}，可用：#{MODES.keys.join(', ')}" unless MODES.key?(mode)
    top = model.entities.grep(Sketchup::Group)
    nested_groups = top.flat_map { |g| nested(g) }

    # 先全部恢复，保证每次切换都是幂等的
    (top + nested_groups).each { |g| g.hidden = false }

    hidden = 0
    shown = 0
    patterns = MODES[mode]

    top.each do |g|
      hide = patterns.any? { |p| g.name =~ p }
      if mode == 'level' && z_limit
        # 高于该标高的组隐藏（用组的顶标高判断）
        bb = g.bounds
        hide = true if (bb.max.z * 25.4) > z_limit.to_f + 1
      end
      g.hidden = true if hide
      hide ? hidden += 1 : shown += 1
    end

    { mode: mode, hidden: hidden, shown: shown, z_limit: z_limit,
      note: (mode == 'level' ? "已隐藏顶标高高于 #{z_limit}mm 的组" : '只改了可见性，几何未变；用 full 可完整还原') }
  end

  # 统计当前可见/隐藏，用于核对
  def status(model)
    top = model.entities.grep(Sketchup::Group)
    vis = top.reject(&:hidden?)
    hid = top.select(&:hidden?)
    {
      visible: vis.length,
      hidden: hid.length,
      visible_names: vis.map(&:name).first(30),
      hidden_names: hid.map(&:name).first(30)
    }
  end
end
