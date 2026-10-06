# dsh_handlers.rb -- DSH <-> SketchUp 桥接插件（命令实现层）
#
# 这一层是**可热重载**的：改完这个文件，发一条 {"action":"reload"} 就从磁盘重新加载，
# 不需要重启 SketchUp。所以我把所有命令逻辑都放这里，尽量少让你重启。
#
# 每条命令的返回值会被序列化成 JSON 回传给 DSH。设计原则：
#   1. 返回值必须"自解释"——带了哪些参数、影响了几何、当前模型规模，一眼能看懂发生了什么
#   2. 大输出自动截断，避免把 DSH 的上下文（和 token）吃掉
#   3. 破坏性动作可选 preview（执行后立刻撤销），先看效果再决定要不要留下

module DshBridge
  module Handlers
    # ── 工作区定位（**不写死路径**） ─────────────────────────────────
    #
    # 原来这里是 `HOME = 'E:/deepseek工作区'` —— 换机器/换目录就废，
    # 而且症状很隐蔽：截图和产物悄悄写到别处，不报错。
    #
    # 现在按四步定位，前一步失败才用后一步：
    #   1. 向上找到 sk_client.py 所在目录，读那里的 dsh_workspace.json
    #   2. 环境变量 DSH_WORKSPACE 指向的目录
    #   3. 从**本文件位置**向上找含 sk_client.py 的那一层
    #      （工作区目录名任意，不一定是 sketchup-bridge）
    #   4. 兜底：插件目录下的 sketchup-bridge/
    #
    # ⚠️ 这段在模块加载时执行，所以只能用 Ruby 标准库，
    #    不能依赖本文件后面定义的任何东西。
    module Paths
      module_function

      # 从某目录向上找含 sk_client.py 的那一层
      def ascend(start)
        here = start
        6.times do
          return here if File.exist?(File.join(here, 'sk_client.py'))
          parent = File.dirname(here)
          break if parent == here
          here = parent
        end
        nil
      end

      def find_config
        here = File.dirname(File.expand_path(__FILE__))
        cands = []
        5.times do
          cands << File.join(here, 'dsh_workspace.json')
          parent = File.dirname(here)
          break if parent == here
          here = parent
        end
        env = ENV['DSH_WORKSPACE']
        cands << File.join(env, 'dsh_workspace.json') if env && !env.to_s.empty?
        cands.find { |p| File.exist?(p) }
      end

      def load_config(path)
        require 'json'
        JSON.parse(File.read(path, encoding: 'UTF-8'))
      rescue StandardError
        nil
      end

      def resolve
        self_dir = File.dirname(File.expand_path(__FILE__))
        cfg_path = find_config
        cfg = cfg_path ? load_config(cfg_path) : nil

        # ③ 先从自身位置推导（最可靠：sk_client.py 就在工作区根目录）
        proj = ascend(self_dir)

        # ① 配置文件优先
        if cfg.is_a?(Hash) && !cfg['home'].to_s.strip.empty?
          up = cfg['home'].to_s.tr('\\', '/')
          if File.exist?(File.join(up, 'sk_client.py'))
            proj = up                                  # home 就是工作区本身
          else
            name = cfg['project'].to_s.strip
            name = 'sketchup-bridge' if name.empty?
            proj = File.join(up, name)
          end
        elsif ENV['DSH_WORKSPACE'] && !ENV['DSH_WORKSPACE'].to_s.empty?
          v = ENV['DSH_WORKSPACE'].to_s.tr('\\', '/')
          proj = File.exist?(File.join(v, 'sk_client.py')) ? v : File.join(v, 'sketchup-bridge')
        end

        # ④ 兜底
        proj ||= File.join(File.dirname(self_dir), 'sketchup-bridge')

        shots = nil
        shots = cfg['shots'].to_s.tr('\\', '/') if cfg.is_a?(Hash) && !cfg['shots'].to_s.strip.empty?
        shots ||= File.join(proj, 'shots')

        { home: File.dirname(proj), project: proj, shots: shots,
          config: cfg_path, derived: cfg.nil? }
      end
    end

    _RES = Paths.resolve
    HOME        = _RES[:home]
    PROJECT_DIR = _RES[:project]
    SHOT_DIR    = _RES[:shots]
    CONFIG_PATH = _RES[:config]

    MAX_LIST = 80
    MAX_STR  = 4000

    # ── 必读的接手指南 ──────────────────────────────────────────────
    #
    # 为什么要有这个东西：DSH 的对话记忆**重启后会清空**，
    # 而工具链、坑、约定都留在磁盘上。没有强制机制的话，
    # 新会话会**在不知道这些坑的情况下改代码**，把已经修好的问题重新引入。
    #
    # 三条机制配合：
    #   1. `ping`（每次连接都会调）返回 briefing 提示 —— 让新会话**第一眼就看到**
    #   2. `briefing` 命令返回指南全文 —— 读了才拿到内容
    #   3. **`reload` 在没读指南前拒绝执行** —— 硬门，不是提醒
    #
    # 第 3 条是关键：只提示不拦，"必须读"就是句空话。
    BRIEFING_NAME = 'DSH-接手指南.md'
    # 插件目录与工作区各放一份（跟着插件走，也方便就地改）
    BRIEFING_PATHS = [
      File.join(File.dirname(File.expand_path(__FILE__)), BRIEFING_NAME),
      "#{PROJECT_DIR}/#{BRIEFING_NAME}"
    ].freeze

    ACTIONS = {}

    module_function

    # 指南文件的实际路径（读不到返回 nil）
    def briefing_path
      BRIEFING_PATHS.find { |p| File.exist?(p) }
    end

    # ⚠️「已读」这个标记放在**进程级全局变量**里，三个坑都踩过：
    #
    #   1. 放 Handlers 的 `@briefing_read` → `load` 重新打开模块，被清掉
    #   2. 放 `DshBridge` 的实例变量 → 用 eval 加载时**外层模块被重建**，也被清掉
    #   3. 于是出现"读了指南 → reload → 又被拦"的死循环，指南等于白读
    #
    # 全局变量 `$dsh_...` 在进程内跨 load / 跨模块重建都存活，是这里唯一可靠的位置。
    # 名字带前缀避免碰撞；重启 SketchUp 自然归零 —— 那正是"新会话要重读"的时机。
    #
    # 另外记**读到的是哪一版**，用**内容哈希**而不是 mtime：
    #
    # 踩过：一开始用 `mtime-size` 做指纹，结果 reload 之后标记失效 ——
    # 因为 `briefing_path` 会解析到**插件目录**那份，而读的时候可能是
    # **工作区**那份；两份内容一模一样，但 mtime 不同，指纹就对不上。
    # 用内容哈希，内容相同即视为同一版，跨路径、跨拷贝都稳。
    def briefing_stamp(path)
      return nil unless path && File.exist?(path)
      require 'digest'
      Digest::SHA256.file(path).hexdigest
    rescue StandardError
      nil
    end

    def briefing_read?
      $dsh_briefing_stamp && $dsh_briefing_stamp == briefing_stamp(briefing_path)
    end

    def mark_briefing_read!
      $dsh_briefing_stamp = briefing_stamp(briefing_path)
    end

    # ---------------------------------------------------------------- 工具

    def model
      m = Sketchup.active_model
      raise DshBridge::Error.new('no_model', '当前没有打开的模型') unless m
      m
    end

    # SketchUp 内部单位是英寸，对外一律毫米
    def to_mm(inches)
      (inches.to_f * 25.4).round(2)
    end

    def clamp_str(s, limit = MAX_STR)
      s = s.to_s
      return s if s.length <= limit
      "#{s[0, limit]}\n...[截断 #{s.length - limit} 字符]"
    end

    def bbox_info(bb)
      return nil unless bb && bb.valid?
      {
        min_mm: bb.min.to_a.map { |v| to_mm(v) },
        max_mm: bb.max.to_a.map { |v| to_mm(v) },
        size_mm: [to_mm(bb.width), to_mm(bb.height), to_mm(bb.depth)]
      }
    end

    def entity_row(e)
      row = { type: e.typename }
      row[:name] = e.name if e.respond_to?(:name) && e.name && !e.name.empty?
      row[:id] = e.entityID if e.respond_to?(:entityID)
      if e.respond_to?(:bounds)
        bb = e.bounds
        row[:size_mm] = [to_mm(bb.width), to_mm(bb.height), to_mm(bb.depth)] if bb && bb.valid?
        row[:min_mm]  = bb.min.to_a.map { |v| to_mm(v) } if bb && bb.valid?
      end
      if e.respond_to?(:material) && e.material
        row[:material] = e.material.display_name
      end
      if e.is_a?(Sketchup::Group) || e.is_a?(Sketchup::ComponentInstance)
        row[:definition] = e.definition.name
        row[:children] = e.definition.entities.length
      end
      row[:faces] = e.definition.entities.grep(Sketchup::Face).length if e.is_a?(Sketchup::ComponentInstance)
      row
    end

    def entity_by_id(m, id)
      m.find_entity_by_id(id) || (raise DshBridge::Error.new('not_found', "找不到 entityID=#{id}"))
    end

    def safe_name(e)
      n = (e.respond_to?(:name) ? e.name.to_s : '')
      n.empty? ? e.typename : n
    end

    # 路径是否在工作区内。
    #
    # ⚠️ 这个判断原来写成 `path.include?('deepseek工作区')` —— **写死了目录名**。
    # 换机器后 save/export 一律报 outside_workspace，而且看不出原因。
    # 现在按规范化后的前缀比较（大小写不敏感，Windows 上盘符大小写常不一致）。
    def inside_workspace?(path)
      return true if path.nil? || path.to_s.empty?
      p = File.expand_path(path.to_s.tr('\\', '/'))
      [PROJECT_DIR, HOME].compact.each do |root|
        next if root.to_s.empty?
        r = File.expand_path(root.to_s.tr('\\', '/'))
        return true if p == r || p.start_with?(r + '/')
      end
      false
    rescue StandardError
      # 判断本身出问题时**放行**：宁可允许写盘，也不要因为守卫自身出错
      # 把正常工作全挡住（这个守卫是防误操作，不是安全边界）。
      true
    end

    def capture
      cap = DshBridge::Capture.new
      cap.orig = $stdout
      $stdout = cap
      cap
    end

    def release(cap)
      $stdout = cap.orig if cap.orig
      nil
    end

    # 从异常里提炼出对修复有用的信息：跳过 SketchUp 内部帧
    def trace_of(e, limit = 8)
      (e.backtrace || []).reject { |l| l.include?('RubyStdLib') }.first(limit)
    end

    # ---------------------------------------------------- 变更检测（踩过坑）
    #
    # 原实现用 model.undo_stack_length / active_operations 判断"这次改动生效没"，
    # 但 **SketchUp 2026 里这两个方法根本不存在**（respond_to? 只有 start_operation）。
    # 结果 changed 永远为 false——明明建了三个物体却报"未改动"。
    # 一个会说谎的准确性指标比没有指标更糟，所以改成统计真实可读的模型指标。

    SNAPSHOT_KEYS = %w[entities faces edges groups components images materials definitions].freeze

    def counts_of(collection)
      {
        'entities' => collection.length,
        'faces' => collection.grep(Sketchup::Face).length,
        'edges' => collection.grep(Sketchup::Edge).length,
        'groups' => collection.grep(Sketchup::Group).length,
        'components' => collection.grep(Sketchup::ComponentInstance).length,
        'images' => collection.grep(Sketchup::Image).length
      }
    rescue StandardError
      { 'entities' => -1 }
    end

    def snapshot(m)
      snap = counts_of(m.entities)
      snap['materials'] = (m.materials.length rescue -1)
      snap['definitions'] = (m.definitions.length rescue -1)
      snap
    rescue StandardError
      {}
    end

    def diff_of(before, after)
      return {} unless before.is_a?(Hash) && after.is_a?(Hash)
      keys = (before.keys | after.keys)
      keys.each_with_object({}) do |k, acc|
        b = before[k]
        a = after[k]
        acc[k] = a - b if b.is_a?(Integer) && a.is_a?(Integer) && a != b
      end
    end

    # ---------------------------------------------------------------- 命令

    ACTIONS['ping'] = lambda do |_srv, _args|
      # briefing 字段：新会话连上来的**第一眼**就会看到它。
      # 没读之前一直带着 must_read: true，读了才变 false。
      bp = DshBridge::Handlers.briefing_path
      brief = {
        must_read: !DshBridge::Handlers.briefing_read?,
        name: BRIEFING_NAME,
        action: 'briefing',
        hint: DshBridge::Handlers.briefing_read? ?
              '已读过接手指南' :
              '**先执行 {"action":"briefing"} 读接手指南全文** —— ' \
              '它记录了架构、两条技术路线、以及 8 条踩过的坑。' \
              '在读过之前，reload 会被拒绝（防止在不知情的情况下改坏代码）。'
      }
      brief[:found] = !bp.nil?
      {
        pong: true,
        version: DshBridge::VERSION,
        ruby: RUBY_VERSION,
        sketchup: Sketchup.version,
        platform: (Sketchup.respond_to?(:platform) ? Sketchup.platform.to_s : 'unknown'),
        briefing: brief,
        actions: ACTIONS.keys.sort
      }
    end

    # 读接手指南全文。**读一次就把 must_read 关掉**（本会话内）。
    ACTIONS['briefing'] = lambda do |_srv, _args|
      bp = DshBridge::Handlers.briefing_path
      if bp.nil?
        raise DshBridge::Error.new('briefing_missing',
                                   "找不到 #{BRIEFING_NAME}；找过：#{BRIEFING_PATHS.join(' / ')}")
      end
      text = File.read(bp, encoding: 'UTF-8')
      DshBridge::Handlers.mark_briefing_read!
      {
        name: BRIEFING_NAME,
        path: bp,
        bytes: text.bytesize,
        marked_read: true,
        content: text
      }
    end

    ACTIONS['status'] = lambda do |srv, _args|
      st = srv.status.dup
      m = Sketchup.active_model
      st[:model] = m ? (m.path.to_s.empty? ? '(未保存)' : m.path) : '(无模型)'
      st[:modified] = m ? m.modified? : nil
      st[:handlers_loaded] = DshBridge.const_defined?(:Handlers)
      st
    end

    ACTIONS['reload'] = lambda do |_srv, _args|
      # ── 硬门：没读接手指南之前，不许热重载
      #
      # 为什么拦在这里：`reload` 是"改完代码让它生效"的入口。
      # 一个不知道那些坑的新会话，一上来就改代码并 reload，
      # 极可能把已经修好的问题重新引入（比如又把门做成窗、
      # 又把 `min` 当 `min_by` 用）。**只提示不拦，"必须读"就是空话。**
      unless DshBridge::Handlers.briefing_read?
        bp = DshBridge::Handlers.briefing_path
        raise DshBridge::Error.new(
          'briefing_required',
          "**先读接手指南再改代码**：执行 {\"action\":\"briefing\"}。" \
          "它记录了架构、两条技术路线、标准工作流，以及 8 条踩过的坑" \
          "（报错点≠出错点、静默失败比报错危险、自洽≠正确…）。" \
          "#{bp ? "指南在 #{bp}" : '⚠️ 但没找到指南文件，请检查 BRIEFING_PATHS'}"
        )
      end
      DshBridge.reload
    end

    # 执行任意 Ruby。这是最常用的一条命令。
    # args:
    #   code    : String 或 String[]（数组按顺序执行，逐个收集非 nil 返回值）
    #   undo    : 默认 true —— 整段包进一个 SketchUp 操作，撤销时是一步
    #   op_name : 出现在"撤销"菜单里的名字
    #   preview : true 则执行完立刻撤销（干跑），只回传发生了什么
    #   print   : true 则把最后一个非 nil 返回值也回传
    ACTIONS['eval'] = lambda do |_srv, args|
      m = model
      code = args['code']
      code = [code] if code.is_a?(String)
      raise DshBridge::Error.new('bad_args', 'code 必须是字符串或字符串数组') unless code.is_a?(Array)
      code = code.map(&:to_s)

      preview  = args['preview'] ? true : false
      use_op   = args.key?('undo') ? (args['undo'] ? true : false) : true
      op_name  = (args['op_name'] || 'DSH').to_s
      want_val = args['print'] ? true : false

      before = snapshot(m)

      cap = capture
      results = {}
      err = nil
      op_started = false
      op_closed = false
      t0 = Time.now
      begin
        if use_op
          op_started = m.start_operation(op_name, true) ? true : false
        end
        code.each_with_index do |src, i|
          unless src.strip.empty?
            r = eval(src, TOPLEVEL_BINDING, "dsh(#{i})", 1) # rubocop:disable Security/Eval
            results[i] = r unless r.nil?
          end
        end
      rescue Exception => e # rubocop:disable Lint/RescueException
        err = e
      ensure
        if use_op && op_started
          begin
            if err.nil?
              m.commit_operation
            else
              m.abort_operation
            end
            op_closed = true
          rescue StandardError
            nil
          end
        end
        release(cap)
      end

      if err
        # 出错时把已经产生的输出也带回去，方便定位
        raise DshBridge::Error.new('ruby_error',
                                   "#{err.class}: #{err.message}\n#{trace_of(err).join("\n")}")
      end

      after = snapshot(m)
      delta = diff_of(before, after)
      changed = !delta.empty?

      undo_note = nil
      if preview
        # 同样不要拿 Sketchup.undo 的返回值当判据——它成功时返回 nil。
        # 用"撤销前后的计数差"判断，跟 undo 命令里同一套判据。
        before_undo = snapshot(m)
        begin
          if Sketchup.respond_to?(:undo)
            Sketchup.undo
            d = diff_of(before_undo, snapshot(m))
            undo_note = if d.empty?
                          'preview 未产生可撤销的变化（或撤销未生效）——请核对 delta'
                        else
                          "已撤销（preview 干跑，回滚了 #{d.inspect}）"
                        end
          else
            undo_note = '本 SketchUp 版本不提供 Sketchup.undo，preview 未能撤销——改动仍在！'
          end
        rescue StandardError => e
          undo_note = "撤销失败：#{e.class}: #{e.message}——改动仍在！"
        end
      end

      out = {
        ms: ((Time.now - t0) * 1000).round(1),
        changed: changed,
        delta: delta,
        counts_before: before,
        counts_after: after,
        operation: { name: op_name, wrapped: use_op, started: op_started, committed: op_closed },
        preview: preview,
        output: clamp_str(cap.digest),
        model_entities: after['entities'],
        selection: m.selection.length
      }
      out[:preview_undo] = undo_note if preview
      if want_val && !results.empty?
        out[:values] = results.map { |k, v| [k, clamp_str(v.inspect, 2000)] }.to_h
      end
      out
    end

    # 探查模型。args: scope = all|selection|top|containers, limit, depth, bbox
    ACTIONS['info'] = lambda do |_srv, args|
      m = model
      scope = (args['scope'] || 'top').to_s
      limit = (args['limit'] || 40).to_i
      depth = (args['depth'] || 1).to_i

      ents =
        case scope
        when 'selection' then m.selection.to_a
        when 'all'       then m.entities.to_a
        when 'faces'     then m.entities.grep(Sketchup::Face)
        when 'edges'     then m.entities.grep(Sketchup::Edge)
        else m.entities.to_a
        end

      rows = ents.first(limit).map { |e| entity_row(e) }
      lists = {}
      begin
        lists[:tags] = m.layers.map(&:name).first(40)
      rescue StandardError
        lists[:tags] = []
      end
      begin
        lists[:materials] = m.materials.map(&:display_name).first(40)
      rescue StandardError
        lists[:materials] = []
      end
      begin
        lists[:scenes] = m.pages.map(&:name).first(40)
      rescue StandardError
        lists[:scenes] = []
      end

      cam = m.active_view.camera
      data = {
        scope: scope,
        total_in_scope: ents.length,
        shown: rows.length,
        entities: rows,
        counts: {
          top_level: m.entities.length,
          groups: m.entities.grep(Sketchup::Group).length,
          components: m.entities.grep(Sketchup::ComponentInstance).length,
          faces: m.entities.grep(Sketchup::Face).length,
          edges: m.entities.grep(Sketchup::Edge).length,
          definitions: m.definitions.length
        },
        model_bbox: bbox_info(m.bounds),
        selection: m.selection.to_a.first(20).map { |e| safe_name(e) },
        camera: {
          eye_mm: cam.eye.to_a.map { |v| to_mm(v) },
          target_mm: cam.target.to_a.map { |v| to_mm(v) },
          up: cam.up.to_a,
          perspective: cam.perspective?,
          fov: cam.perspective? ? cam.fov : nil
        },
        lists: lists,
        depth: depth
      }
      data[:truncated] = ents.length > rows.length
      data
    end

    # 截图。args: viewport, width, height, camera(哈希: eye/target/up/perspective), ortho, name, restore
    ACTIONS['shot'] = lambda do |_srv, args|
      m = model
      v = m.active_view
      w = (args['width'] || 1280).to_i
      h = (args['height'] || 800).to_i
      vp = args.key?('viewport') ? (args['viewport'] ? true : false) : false
      restore = args.key?('restore') ? (args['restore'] ? true : false) : true

      # 渲染模式（可选）。实测这台 SketchUp 2026：
      #   RenderMode 0 = 线框 / 1 = 单色（**不显示材质颜色**）/ 2 = 着色+贴图（默认，能看材质）
      # 所以想验证材质必须用 2。要"材质本色不带光照"目前没有可用的模式——
      # 1 是单色，会把所有材质画成同一种灰。
      ro = m.rendering_options
      saved_render_mode = nil
      if args['render_mode']
        begin
          saved_render_mode = ro['RenderMode']
          ro['RenderMode'] = args['render_mode'].to_i
        rescue StandardError
          saved_render_mode = nil
        end
      end

      require 'fileutils'
      FileUtils.mkdir_p(SHOT_DIR)
      name = (args['name'] || "shot-#{Time.now.strftime('%H%M%S')}").to_s.gsub(/[^0-9A-Za-z_\-]/, '_')
      path = "#{SHOT_DIR}/#{name}.png"

      # 记住状态，拍完恢复（否则我的取景会污染你的工作视图）
      cam = v.camera
      saved = {
        eye: cam.eye.to_a, target: cam.target.to_a, up: cam.up.to_a,
        perspective: cam.perspective?, fov: cam.fov, height: cam.height
      }

      begin
        if (c = args['camera']) && c.is_a?(Hash)
          eye    = c['eye']
          target = c['target']
          if eye && target
            newcam = Sketchup::Camera.new(
              Geom::Point3d.new(eye[0].to_f / 25.4, eye[1].to_f / 25.4, eye[2].to_f / 25.4),
              Geom::Point3d.new(target[0].to_f / 25.4, target[1].to_f / 25.4, target[2].to_f / 25.4),
              Geom::Vector3d.new(*((c['up'] || [0, 0, 1]).map(&:to_f)))
            )
            newcam.perspective = c['perspective'] ? true : false if c.key?('perspective')
            newcam.fov = c['fov'].to_f if c['fov']
            m.active_view.camera = newcam
          end
        end

        res = { path: path, width: w, height: h, viewport: vp }
        opts = { filename: path, width: w, height: h, antialias: true, compression: 0.9 }
        wrote = nil
        begin
          wrote = vp ? v.write_image(opts) : v.write_image(opts)
        rescue ArgumentError => e
          res[:write_image_warning] = e.message
        rescue StandardError => e
          res[:write_image_warning] = "#{e.class}: #{e.message}"
        end
        res[:write_returned] = wrote.inspect unless wrote.nil?

        unless File.exist?(path)
          alt = "#{SHOT_DIR}/#{name}.jpg"
          begin
            v.write_image(opts.merge(filename: alt, format: 'jpg'))
          rescue StandardError
            nil
          end
          if File.exist?(alt)
            path = alt
            res[:path] = alt
          else
            raise DshBridge::Error.new('shot_failed',
                                       "截图没有生成：#{(res[:write_image_warning] || '未报错但文件不存在').to_s[0, 300]}")
          end
        end

        res[:bytes] = File.size(path)
        res[:mtime] = File.mtime(path).strftime('%H:%M:%S')
        res[:camera_used_mm] = {
          eye: m.active_view.camera.eye.to_a.map { |x| to_mm(x) },
          target: m.active_view.camera.target.to_a.map { |x| to_mm(x) }
        }
        res
      ensure
        if restore
          begin
            newcam = Sketchup::Camera.new(
              Geom::Point3d.new(*saved[:eye]),
              Geom::Point3d.new(*saved[:target]),
              Geom::Vector3d.new(*saved[:up])
            )
            newcam.perspective = saved[:perspective]
            saved[:perspective] ? (newcam.fov = saved[:fov]) : (newcam.height = saved[:height])
            m.active_view.camera = newcam
          rescue StandardError
            nil
          end
        end
        # 渲染模式也要恢复，否则我截图会改掉你视图的显示方式
        if saved_render_mode
          begin
            ro['RenderMode'] = saved_render_mode
          rescue StandardError
            nil
          end
        end
      end
    end

    # 存盘。args: path（默认落在 DSH 工作区）, overwrite
    ACTIONS['save'] = lambda do |_srv, args|
      m = model
      path = args['path']
      if path.nil? || path.to_s.empty?
        require 'fileutils'
        FileUtils.mkdir_p("#{PROJECT_DIR}/models")
        stamp = Time.now.strftime('%Y%m%d-%H%M%S')
        path = "#{HOME}/sketchup-bridge/models/model-#{stamp}.skp"
      end
      path = path.to_s.tr('\\', '/')
      # ⚠️ 这里原来写的是 `!path.include?('deepseek工作区')` —— **写死了工作区名**。
      # 换机器（或改目录名）之后，连正常保存都会被拒：
      # 症状是 save/export 一律报 outside_workspace，而原因看不出来。
      # 现在用上面的四步定位结果判断。
      if !inside_workspace?(path) && !args['allow_outside']
        raise DshBridge::Error.new('outside_workspace',
                                   "拒绝写入工作区之外的路径: #{path}（确实要写请传 allow_outside: true）")
      end
      if File.exist?(path) && !args['overwrite']
        raise DshBridge::Error.new('exists', "文件已存在: #{path}（要覆盖请传 overwrite: true）")
      end
      require 'fileutils'
      FileUtils.mkdir_p(File.dirname(path))
      ok = m.save(path)
      { saved: ok ? true : false, path: path, bytes: (File.exist?(path) ? File.size(path) : nil),
        title: m.title }
    end

    ACTIONS['undo'] = lambda do |_srv, args|
      m = model
      n = [(args['count'] || 1).to_i, 20].min
      # 注意：撤销在 **Sketchup 模块**上（Sketchup.undo），不在 Model 上。
      # Model 上只有 start_operation / commit_operation / abort_operation；
      # 实测 m.undo 报 `undefined method 'undo' for Sketchup::Model`。
      unless Sketchup.respond_to?(:undo)
        raise DshBridge::Error.new('undo_unsupported', '本 SketchUp 版本不提供 Sketchup.undo')
      end
      # 而且 **Sketchup.undo 成功时返回 nil**，不能拿返回值当成功判据——
      # 我第一版写 `break unless ok`，于是"撤销成功却报告 undone=0"。
      # 正确的判据是：模型计数有没有真的变。
      delta = {}
      done = 0
      n.times do
        before = snapshot(m)
        begin
          Sketchup.undo
        rescue StandardError => e
          raise DshBridge::Error.new('undo_failed', "#{e.class}: #{e.message}")
        end
        d = diff_of(before, snapshot(m))
        break if d.empty?
        done += 1
        delta = d
      end
      { undone: done, requested: n, delta: delta, counts_after: snapshot(m),
        api: 'Sketchup.undo（成功返回 nil，判据用计数变化）' }
    end

    ACTIONS['redo'] = lambda do |_srv, args|
      m = model
      n = [(args['count'] || 1).to_i, 20].min
      unless Sketchup.respond_to?(:redo)
        raise DshBridge::Error.new('redo_unsupported', '本 SketchUp 版本不提供 Sketchup.redo')
      end
      delta = {}
      done = 0
      n.times do
        before = snapshot(m)
        begin
          Sketchup.redo
        rescue StandardError => e
          raise DshBridge::Error.new('redo_failed', "#{e.class}: #{e.message}")
        end
        d = diff_of(before, snapshot(m))
        break if d.empty?
        done += 1
        delta = d
      end
      { redone: done, requested: n, delta: delta }
    end

    # 说明"我能看到什么、看不到什么"。
    # 实测结论（别凭记忆改）：
    #   Sketchup::Model 上**没有** undo / redo / undo_stack_length / active_operations
    #   撤销与重做在 **Sketchup 模块**上：Sketchup.undo / Sketchup.redo
    #   所以"撤销栈里有哪些操作名"拿不到——如实说明，而不是返回空数组假装正常。
    ACTIONS['history'] = lambda do |_srv, _args|
      m = model
      probe = {
        'Model#undo' => m.respond_to?(:undo),
        'Model#redo' => m.respond_to?(:redo),
        'Model#undo_stack_length' => m.respond_to?(:undo_stack_length),
        'Model#active_operations' => m.respond_to?(:active_operations),
        'Model#start_operation' => m.respond_to?(:start_operation),
        'Sketchup.undo' => Sketchup.respond_to?(:undo),
        'Sketchup.redo' => Sketchup.respond_to?(:redo)
      }
      {
        available_methods: probe,
        counts: snapshot(m),
        model_modified: m.modified?,
        note: '撤销/重做在 Sketchup 模块上（Sketchup.undo / Sketchup.redo），Model 上没有。' \
              '本版不提供"列出撤销栈操作名"的能力，因此无法预演你会看到什么——' \
              '但 DSH 的每个操作都包成一个命名操作（op_name），会出现在你的撤销菜单里。'
      }
    end

    # 选中指定 entityID（让我能"指"给你看，也能把选择集当工作集）
    ACTIONS['select'] = lambda do |_srv, args|
      m = model
      ids = args['ids']
      ids = [ids] if ids.is_a?(Integer)
      ids = [] unless ids.is_a?(Array)
      m.selection.clear
      found = []
      missing = []
      ids.each do |id|
        e = m.find_entity_by_id(id.to_i)
        if e
          m.selection.add(e)
          found << id
        else
          missing << id
        end
      end
      { selected: found, missing: missing, count: m.selection.length }
    end

    # 量两个点之间的距离（毫米），用来核对我看图估出来的尺寸
    ACTIONS['measure'] = lambda do |_srv, args|
      a = args['from']
      b = args['to']
      raise DshBridge::Error.new('bad_args', '需要 from 和 to，各为 [x,y,z] 毫米') unless a && b
      pa = Geom::Point3d.new(a[0].to_f / 25.4, a[1].to_f / 25.4, a[2].to_f / 25.4)
      pb = Geom::Point3d.new(b[0].to_f / 25.4, b[1].to_f / 25.4, b[2].to_f / 25.4)
      v = pa.vector_to(pb)
      {
        distance_mm: to_mm(v.length),
        delta_mm: v.to_a.map { |x| to_mm(x) },
        from_mm: a, to_mm: b
      }
    end

    # 删除顶层实体。args: ids 或 all=true（all 需要 confirm）
    ACTIONS['erase'] = lambda do |_srv, args|
      m = model
      before = snapshot(m)
      if args['all']
        unless args['confirm']
          raise DshBridge::Error.new('need_confirm', '要清空模型请传 confirm: true')
        end
        n = m.entities.length
        m.start_operation('DSH 清空', true)
        m.entities.clear!
        m.commit_operation
        return { erased: n, scope: 'all', delta: diff_of(before, snapshot(m)) }
      end
      ids = args['ids']
      ids = [ids] if ids.is_a?(Integer)
      ids = [] unless ids.is_a?(Array)
      raise DshBridge::Error.new('bad_args', '需要 ids 数组，或 all: true + confirm: true') if ids.empty?
      m.start_operation('DSH 删除', true)
      n = 0
      gone = []
      ids.each do |id|
        e = m.find_entity_by_id(id.to_i)
        next unless e
        e.erase!
        n += 1
        gone << id
      end
      m.commit_operation
      { erased: n, ids: gone, delta: diff_of(before, snapshot(m)) }
    end

    # 把相机对准某个实体或整个模型——比盲猜坐标可靠得多
    # args: id / ids / zoom_all, margin
    ACTIONS['focus'] = lambda do |_srv, args|
      m = model
      v = m.active_view
      if args['id'] || args['ids']
        ids = args['ids'] || [args['id']]
        ids = [ids] if ids.is_a?(Integer)
        ents = ids.map { |i| m.find_entity_by_id(i.to_i) }.compact
        raise DshBridge::Error.new('not_found', '没有一个 id 找得到') if ents.empty?
        bb = Geom::BoundingBox.new
        ents.each { |e| bb.add(e.bounds) }
        v.zoom(bb)
        { focused: ents.map { |e| safe_name(e) }, bbox_mm: bbox_info(bb) }
      else
        v.zoom_extents
        { focused: 'all', bbox_mm: bbox_info(m.bounds) }
      end
    end

    # 从磁盘导入模型/组件（.skp / .dae / .obj 等），落在工作区内
    ACTIONS['import'] = lambda do |_srv, args|
      m = model
      path = args['path'].to_s.tr('\\', '/')
      raise DshBridge::Error.new('bad_args', '需要 path') if path.empty?
      raise DshBridge::Error.new('not_found', "文件不存在: #{path}") unless File.exist?(path)
      ok = m.import(path)
      { imported: ok ? true : false, path: path, entities_after: m.entities.length,
        new_top_level: m.entities.to_a.last(5).map { |e| entity_row(e) } }
    end

    # 导出：让我或你能拿到别的格式
    ACTIONS['export'] = lambda do |_srv, args|
      m = model
      path = args['path'].to_s.tr('\\', '/')
      raise DshBridge::Error.new('bad_args', '需要 path（含扩展名，如 .dae/.obj/.stl）') if path.empty?
      if !inside_workspace?(path) && !args['allow_outside']
        raise DshBridge::Error.new('outside_workspace', "拒绝写入工作区之外: #{path}")
      end
      require 'fileutils'
      FileUtils.mkdir_p(File.dirname(path))
      ok = m.export(path)
      { exported: ok ? true : false, path: path, bytes: (File.exist?(path) ? File.size(path) : nil) }
    end

    ACTIONS['help'] = lambda do |_srv, _args|
      {
        actions: ACTIONS.keys.sort,
        notes: {
          eval: 'args: code(String|Array), undo(bool,默认true), op_name, preview(bool 干跑), print(bool)',
          shot: 'args: width,height,camera{eye,target,up,perspective,fov}(毫米),name,restore',
          info: 'args: scope(top|all|faces|edges|selection), limit, depth',
          save: 'args: path(默认落工作区), overwrite',
          erase: 'args: ids[] 或 all:true+confirm:true',
          export: 'args: path, allow_outside',
          focus: 'args: id / ids[] / 空=zoom_extents',
          measure: 'args: from[x,y,z] to[x,y,z] 毫米'
        },
        units: '所有坐标/尺寸对外一律毫米'
      }
    end
  end
end
