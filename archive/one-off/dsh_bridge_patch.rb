# dsh_bridge_patch.rb -- 热补丁 v5：把可靠的 reload 推给活着的进程
#
# 为什么需要这个文件：dsh_bridge.rb 是基础层，改完本该重启才生效。但只要服务还活着，
# 就能用 load 把**方法级**修正推进去，省掉一次重启。
#
# reload 的五次迭代（每次都是实测出来的，不是推演）：
#   v1 `DshBridge.const_defined?(:Handlers)`  → 沿祖先链误判 → NameError: Object::Handlers
#   v2 remove_const + module_eval             → 留下"Handlers 不存在"的窗口
#   v3 临时模块验证 + const_set，但常量路径写错（tmp::ACTIONS ≠ tmp::DshBridge::Handlers::ACTIONS）
#   v4 修好路径，reload 报成功 —— 但**之后所有 handler 全废**：
#      NameError: uninitialized constant #<Module:0x...>::DshBridge::VERSION
#      原因：handler 在匿名临时模块里 eval，词法作用域指向那个假模块，
#            于是 DshBridge::VERSION 解析到了假的 DshBridge 上。
#      ⇒ "先加载一份副本用于验证"这条路从原理上就不通：副本要么拿到生产用，
#        要么它的词法作用域与生产不符。
#   v5（本文件）：
#      · 真正生产的是 DshBridge::Handlers 本身（词法作用域天然正确）
#      · 危险只剩"语法错误导致半截代码"，用 Ripper 做**纯语法预检**拦住（不执行任何代码）
#      · 运行时异常会让旧方法留在模块上，属于可接受的降级

begin
  require 'ripper'
rescue LoadError
  nil
end

module DshBridge
  class << self
    def reload
      path = File.join(File.dirname(__FILE__), 'dsh_handlers.rb')
      raise DshBridge::Error.new('reload', "找不到 #{path}") unless File.exist?(path)

      # ── 预检 1：文件不能是空的或明显被截断
      size = File.size(path)
      if size < 500
        raise DshBridge::Error.new('reload', "文件只有 #{size} 字节，疑似被截断，拒绝加载")
      end

      # ── 预检 2：纯语法检查（Ripper 只解析、不执行）
      if defined?(Ripper)
        src = File.read(path)
        if Ripper.sexp(src).nil?
          raise DshBridge::Error.new('reload', 'Ruby 语法检查未通过（Ripper 解析失败），已拒绝加载，旧代码未受影响')
        end
      end

      had = DshBridge.const_defined?(:Handlers, false)
      old = had ? DshBridge::Handlers::ACTIONS.keys.sort : []

      # ── 真正加载：就地重开 DshBridge::Handlers，词法作用域天然正确
      begin
        load path
      rescue Exception => e # rubocop:disable Lint/RescueException
        DshBridge.log("reload FAILED #{e.class}: #{e.message}") if DshBridge.respond_to?(:log)
        raise DshBridge::Error.new(
          'reload_failed',
          "#{e.class}: #{e.message}\n文件已重新加载但有异常；若命令缺失请重启 SketchUp"
        )
      end

      unless DshBridge.const_defined?(:Handlers, false)
        raise DshBridge::Error.new('reload', '加载后仍找不到 DshBridge::Handlers')
      end

      acts = DshBridge::Handlers::ACTIONS
      now = acts.keys.sort
      DshBridge.log("reload(v5) ok #{now.length} actions (added=#{now - old}, removed=#{old - now})") if DshBridge.respond_to?(:log)

      {
        reloaded: true, version: DshBridge::VERSION, actions: now,
        previous_actions: old, added: now - old, removed: old - now,
        in_place: true, syntax_checked: defined?(Ripper) ? true : false, patch: 'v5'
      }
    end
  end
end

puts "[DSH] reload 已打补丁 v5（Ripper 语法预检 + 就地重开生产模块；不再使用临时模块）"
true
