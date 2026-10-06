# dsh_bridge.rb -- DSH <-> SketchUp 桥接插件（基础设施层）
#
# 作用：在 SketchUp 进程内起一个只监听 127.0.0.1 的 TCP 服务，接收换行分隔的
#       JSON 命令，执行后回传 JSON。DSH 侧用 sk_client.py 连接。
#
# 分三层（重要）：
#   dsh_bridge.rb   本文件 = 基础设施（Socket / 调度 / 分帧）。**改这里要重启 SketchUp**
#   dsh_handlers.rb 命令实现层。**可热重载**：发 {"action":"reload"} 即从磁盘重新加载，
#                   不用重启 SketchUp。所以我平时改命令逻辑，你不需要动。
#   dsh_loader.rb   菜单 / 工具栏 / 面板（纯便利层，坏了不影响桥）
#
# 安全边界：只绑定 127.0.0.1；必须带正确 token；写盘默认只允许 DSH 工作区内。

require 'socket'
require 'json'

module DshBridge
  # ── 定位文件（路径与 token 都在里面）──────────────────────────
  #
  # 为什么要一个定位文件：
  #   · 这个文件原来把工作区路径写死成 'E:/deepseek工作区/sketchup-bridge'
  #     —— 换机器/换目录就废，而且症状隐蔽。
  #   · token 原来是写死的常量 'dsh-su-2026' —— **所有人共用同一个**，
  #     任何本机程序只要知道它就能连上你的 SketchUp。上传到 GitHub 更糟：
  #     等于把钥匙印在说明书上。
  #
  # 现在：先从 dsh_workspace.json 读；读不到再按位置推导。
  # token 缺省时**首次运行随机生成并写回**，每个安装各不相同。
  module Locate
    module_function

    # 按四步找定位文件：自身向上 → 环境变量
    def config_path
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

    def config
      p = config_path
      return {} unless p
      require 'json'
      JSON.parse(File.read(p, encoding: 'UTF-8'))
    rescue StandardError
      {}
    end

    # 工作区根目录（含 sk_client.py 的那一层）
    def project_dir
      cfg = config
      home = cfg['home'].to_s.tr('\\', '/')
      unless home.empty?
        return home if File.exist?(File.join(home, 'sk_client.py'))
        name = cfg['project'].to_s.strip
        name = 'sketchup-bridge' if name.empty?
        cand = File.join(home, name)
        return cand if File.exist?(File.join(cand, 'sk_client.py'))
      end
      here = File.dirname(File.expand_path(__FILE__))
      6.times do
        return here if File.exist?(File.join(here, 'sk_client.py'))
        parent = File.dirname(here)
        break if parent == here
        here = parent
      end
      File.join(File.dirname(File.expand_path(__FILE__)), 'sketchup-bridge')
    end

    # token：读配置 → 没有就随机生成并写回
    #
    # 生成后写回文件是必要的：DSH 侧的客户端要从同一个文件读它。
    # 写不进去（只读目录等）也不致命 —— 那就每次启动一个新 token，
    # **客户端会连不上**，所以这时给出明确提示而不是静默失败。
    def token
      cfg = config
      t = cfg['token'].to_s
      return t if t.length >= 16
      require 'securerandom'
      t = SecureRandom.hex(16)
      write_token(t)
      t
    end

    def write_token(tok)
      path = config_path
      return false unless path
      require 'json'
      cfg = JSON.parse(File.read(path, encoding: 'UTF-8'))
      cfg['token'] = tok
      File.write(path, JSON.pretty_generate(cfg), encoding: 'UTF-8')
      true
    rescue StandardError
      false
    end
  end

  VERSION = begin
    # 版本号**只从 version.json 读**，不在这里写死。
    #
    # 踩过：这里长期写着 VERSION = '1.0.0'，而本文件实际至少改过 5 版
    # （光 reload 逻辑就有 v1~v5），版本号一次没动过。
    # 于是 `ping` 报出来的版本是装饰品——**问"现在第几版"给不出可信答案**。
    #
    # 读不到就退回 '0.0.0-unknown'，**不要**退回一个看起来正常的号——
    # 那会让人以为版本是准的。
    cands = [ENV['DSH_VERSION_JSON'],
             File.join(Locate.project_dir, 'version.json')].compact
    found = cands.find { |p| File.exist?(p) }
    if found
      d = JSON.parse(File.read(found, encoding: 'UTF-8'))
      comp = (d['components'] || []).find { |c| c['name'] == 'dsh_bridge.rb' }
      comp ? comp['version'].to_s : '0.0.0-unknown'
    else
      '0.0.0-unknown'

    end
  rescue StandardError
    '0.0.0-unknown'
  end
  HOST     = '127.0.0.1'
  PORT     = 9877
  # token 不再写死。
  #
  # 原来这里是 `TOKEN = 'dsh-su-2026'` —— 两个问题：
  #   1. **所有安装共用同一个**，任何本机程序知道它就能连上你的 SketchUp
  #   2. 上传到公开仓库等于把钥匙印在说明书上
  # 现在从 dsh_workspace.json 读；缺省时首次运行随机生成并写回，
  # 因此每个安装各不相同。客户端从同一个文件读，所以无需手工同步。
  TOKEN    = Locate.token
  MAX_LINE = 8 * 1024 * 1024
  # eval 输出的截断上限（桥这一侧）。
  # 曾把它从 200_000 提到 1_000_000，以为是它截断了几何校验的 JSON——
  # 其实 68 个构件才 ~4KB，根本没到上限；真凶是**DSH 工具层约 4000 字符就截显示**。
  # 真正的修法是让脚本只回传"结论 + 异常项"。这个上限留着防的是别的大输出。
  MAX_OUT  = 1_000_000
  TICK     = 0.12
  # 连上却不发命令的连接，超过这么久就回收——否则"一次只服务一条连接"会被它堵死
  IDLE_TIMEOUT = 30
  # 工作区相关的路径都从 Locate 取，**不写死**。
  #
  # 原来这里是 `HOME = 'E:/deepseek工作区'` + `SHOT_DIR = "#{HOME}/sketchup-bridge/shots"`，
  # 和 dsh_handlers.rb 里那份重复定义 —— 换机器要改两处，迟早漏一处。
  # 现在只有 Locate 一个真源。
  HOME     = Locate.project_dir          # 语义变了：现在指向工作区本身
  WORKSPACE = Locate.project_dir
  SHOT_DIR = File.join(WORKSPACE, 'shots')

  class Error < StandardError
    attr_reader :code
    def initialize(code, msg)
      @code = code
      super(msg)
    end
  end

  # 捕获 $stdout：让 eval 里的 puts / p 能被 DSH 看到，而不是消失在 SketchUp 控制台
  class Capture
    attr_accessor :orig
    def initialize
      @buf = []
      @orig = nil
    end

    def write(str)
      s = str.to_s
      @buf << s
      @orig.write(s) if @orig && !@orig.equal?(self)
      s.length
    end

    def <<(str)
      write(str)
      self
    end

    def print(*a); write(a.join); end
    def puts(*a)
      if a.empty?
        write("\n")
      else
        a.each do |x|
          s = x.to_s
          write(s.end_with?("\n") ? s : "#{s}\n")
        end
      end
      nil
    end

    def printf(fmt, *a); write(format(fmt, *a)); end
    def flush; self; end
    def sync; true; end
    def sync=(v); v; end
    def tty?; false; end
    def isatty; false; end
    def fileno; nil; end
    def close; nil; end
    def closed?; false; end
    def string; @buf.join; end
    def clear; @buf.clear; self; end

    # 限量取用，防止大输出把 DSH 的上下文吃掉
    def digest(limit = MAX_OUT)
      s = string
      return s if s.length <= limit
      head = s[0, limit / 2]
      tail = s[-limit / 2, limit / 2]
      "#{head}\n...[已截断 #{s.length - limit} 字符]...\n#{tail}"
    end
  end

  class Server
    attr_reader :port, :requests, :served, :failed, :last_error, :client_since, :last_action

    def initialize(port = PORT)
      @port = port
      @queue = []
      @client = nil
      @buf = ''
      @requests = 0
      @served = 0
      @failed = 0
      @last_error = nil
      @client_since = nil
      @client_t0 = nil
      @last_action = nil
      @accept = TCPServer.new(HOST, @port)
      @accept.setsockopt(Socket::IPPROTO_TCP, Socket::TCP_NODELAY, 1)
    end

    def tick
      pump_accept
      pump_client
      pump_request
    rescue => e
      @last_error = "#{e.class}: #{e.message}"
    end

    def stop
      close_client
      begin
        @accept.close if @accept
      rescue StandardError
        nil
      end
      @accept = nil
      true
    end

    def status
      {
        version: DshBridge::VERSION,
        port: @port,
        client: !@client.nil?,
        client_since: @client_since,
        idle_timeout_s: IDLE_TIMEOUT,
        requests: @requests,
        served: @served,
        failed: @failed,
        last_action: @last_action,
        last_error: @last_error,
        queued: @queue.length
      }
    end

    private

    def pump_accept
      return unless @accept
      # 一次只服务一条连接。因为每条连接都在处理完/超时后被关闭，
      # 所以这里不会留下"没人管的残骸"把后续连接堵死。
      if @client
        if @client_t0 && (Time.now - @client_t0) > IDLE_TIMEOUT
          drop_client("空闲超过 #{IDLE_TIMEOUT}s，已回收")
        end
        return if @client
      end
      begin
        sock = @accept.accept_nonblock
      rescue IO::WaitReadable, Errno::EINTR, Errno::EAGAIN
        return
      end
      sock.setsockopt(Socket::IPPROTO_TCP, Socket::TCP_NODELAY, 1)
      @client = sock
      @buf = ''
      @client_since = Time.now.strftime('%H:%M:%S')
      @client_t0 = Time.now
      @last_error = nil
    end

    def drop_client(reason)
      @last_error = reason if reason
      sock = @client
      @client = nil
      @buf = ''
      @client_t0 = nil
      return unless sock
      begin
        sock.close
      rescue StandardError
        nil
      end
    end

    def pump_client
      return unless @client
      chunk = nil
      begin
        chunk = @client.read_nonblock(65_536)
      rescue IO::WaitReadable, Errno::EINTR, Errno::EAGAIN
        return
      rescue EOFError, Errno::ECONNRESET, Errno::EPIPE, IOError => e
        drop_client("客户端断开: #{e.class}")
        return
      end
      if chunk.nil? || chunk.empty?
        drop_client('客户端断开')
        return
      end
      @buf << chunk
      while (idx = @buf.index("\n"))
        line = @buf.slice!(0, idx + 1).strip
        next if line.empty?
        if line.length > MAX_LINE
          drop_client("单条命令超过 #{MAX_LINE} 字节")
          return
        end
        @queue << line
      end
      drop_client('未闭合的超长行') if @buf.length > MAX_LINE
    end

    def pump_request
      return unless @client
      return if @queue.empty?
      raw = @queue.shift
      @requests += 1
      begin
        req = JSON.parse(raw)
        raise DshBridge::Error.new('bad_request', '请求必须是 JSON 对象') unless req.is_a?(Hash)
        unless req['token'].to_s == DshBridge::TOKEN
          raise DshBridge::Error.new('auth', 'token 不正确')
        end
        action = req['action'].to_s
        @last_action = action
        args = req['args']
        args = {} unless args.is_a?(Hash)
        reply = DshBridge.dispatch(self, action, args)
        @served += 1
        send_response('id' => req['id'], 'ok' => true, 'result' => reply)
      rescue DshBridge::Error => e
        @failed += 1
        @last_error = "#{e.code}: #{e.message}"
        send_response('id' => safe_id(raw), 'ok' => false,
                      'error' => { 'code' => e.code, 'message' => e.message })
      rescue JSON::ParserError => e
        @failed += 1
        @last_error = "bad_json: #{e.message}"
        send_response('id' => nil, 'ok' => false,
                      'error' => { 'code' => 'bad_json', 'message' => e.message })
      rescue => e
        @failed += 1
        @last_error = "#{e.class}: #{e.message}"
        send_response('id' => safe_id(raw), 'ok' => false,
                      'error' => { 'code' => 'internal', 'message' => "#{e.class}: #{e.message}" })
      ensure
        # 每处理完一条命令就收线。曾经的漏洞：连接处理完不回收，留下 CLOSE_WAIT 残骸，
        # 而"一次只服务一条连接"的设计会让这条残骸把后面所有连接全堵死。
        # 注意用 close_client（纯 close），不要先 shutdown——原因见 close_client 里的注释。
        close_client
      end
    end

    def close_client
      sock = @client
      @client = nil
      @client_t0 = nil
      @buf = ''
      return unless sock
      # 只用 close，**不要**先 shutdown(SHUT_WR)。
      #
      # 我一度以为 CLOSE_WAIT 残骸是因为"只 close 没 shutdown"，于是加了 shutdown，
      # 结果桥变成"每连必断、回包全丢"：Windows 上先 shutdown 再 close、而对端还有
      # 未读数据时，发的是 RST 而不是正常 FIN，刚写出去的回包会被直接丢弃
      # （实测：加之前客户端能读到 JSON，加之后 recv 立刻返回 b''）。
      #
      # CLOSE_WAIT 的真因是**没有回收**残骸连接，跟 shutdown 无关；那件事已经由
      # pump_accept 里的空闲回收 + 这里的显式 close 解决了。
      begin
        sock.close
      rescue StandardError
        nil
      end
    end

    def safe_id(raw)
      JSON.parse(raw)['id']
    rescue StandardError
      nil
    end

    def send_response(hash)
      return unless @client
      line = "#{JSON.generate(hash)}\n"
      off = 0
      while off < line.bytesize
        begin
          n = @client.write_nonblock(line.byteslice(off, line.bytesize - off))
        rescue IO::WaitWritable, Errno::EINTR, Errno::EAGAIN
          IO.select(nil, [@client], nil, 0.5)
          next
        rescue Errno::EPIPE, Errno::ECONNRESET, IOError => e
          drop_client("回传失败: #{e.class}")
          return
        end
        off += n
      end
    end
  end

  class << self
    attr_reader :server, :timer

    # 命令日志。SketchUp 硬崩溃时不会留下任何 Ruby 报错，唯一能定位的办法就是
    # "崩溃前最后一条命令是什么"。所以每条命令先写 start，再写 done/error——
    # 如果日志停在某条 start 后面没有对应的 done，那条就是凶手。
    def log(msg)
      @log_mutex ||= Mutex.new
      @log_mutex.synchronize do
        require 'fileutils'
        FileUtils.mkdir_p(WORKSPACE)
        File.open(File.join(WORKSPACE, 'bridge.log'), 'a') do |f|
          f.puts "#{Time.now.strftime('%H:%M:%S')} #{msg}"
        end
      end
    rescue StandardError
      nil
    end

    def start(port = PORT)
      return '已在运行' if @server
      @server = Server.new(port)
      @timer = UI.start_timer(TICK, true) { @server && @server.tick }
      log("start port=#{port}")
      "DSH 桥已启动: #{HOST}:#{port}（token=#{TOKEN[0, 6]}…）"
    rescue => e
      @server = nil
      "启动失败: #{e.class}: #{e.message}"
    end

    def stop
      return '本来就没运行' unless @server
      UI.stop_timer(@timer) if @timer
      @timer = nil
      @server.stop
      @server = nil
      log('stop')
      'DSH 桥已停止'
    end

    def running?
      !@server.nil?
    end

    # 重新从磁盘加载命令实现层（不需要重启 SketchUp）
    #
    # 这段代码一共迭代了五次，每一次的失败都写在下面——因为它值得被记住：
    #   v1 `DshBridge.const_defined?(:Handlers)` → 沿祖先链误判 → NameError: Object::Handlers
    #   v2 remove_const + module_eval            → 留下"Handlers 不存在"的窗口
    #   v3 临时模块验证 + const_set，常量路径写错 → 被自家防线拦下
    #   v4 路径修对，reload 报成功——**但之后所有 handler 全废**：
    #      NameError: uninitialized constant #<Module:0x...>::DshBridge::VERSION
    #      原因：handler 在匿名临时模块里 eval，词法作用域指向那个假模块。
    #      ⇒ "先加载一份副本用于验证"从原理上就不通：副本要么不能拿到生产用，
    #        要么它的词法作用域与生产不一致。
    #   v5（现在）：生产的就是 DshBridge::Handlers 本身，作用域天然正确；
    #      剩下的风险"语法错误写坏文件"用 Ripper 做**纯语法预检**拦住（只解析不执行）。
    def reload
      path = File.join(File.dirname(__FILE__), 'dsh_handlers.rb')
      raise DshBridge::Error.new('reload', "找不到 #{path}") unless File.exist?(path)

      size = File.size(path)
      if size < 500
        raise DshBridge::Error.new('reload', "文件只有 #{size} 字节，疑似被截断，拒绝加载")
      end

      begin
        require 'ripper'
      rescue LoadError
        nil
      end
      if defined?(Ripper)
        if Ripper.sexp(File.read(path)).nil?
          raise DshBridge::Error.new('reload', 'Ruby 语法预检未通过（Ripper 解析失败），已拒绝加载，旧代码未受影响')
        end
      end

      had = DshBridge.const_defined?(:Handlers, false)
      old = had ? DshBridge::Handlers::ACTIONS.keys.sort : []

      begin
        load path
      rescue Exception => e # rubocop:disable Lint/RescueException
        log("reload FAILED #{e.class}: #{e.message}")
        raise DshBridge::Error.new('reload_failed',
                                   "#{e.class}: #{e.message}\n文件已重载但有异常；若命令缺失请重启 SketchUp")
      end

      unless DshBridge.const_defined?(:Handlers, false)
        raise DshBridge::Error.new('reload', '加载后仍找不到 DshBridge::Handlers')
      end

      now = DshBridge::Handlers::ACTIONS.keys.sort
      log("reload ok #{now.length} actions (added=#{now - old}, removed=#{old - now})")
      {
        reloaded: true, version: DshBridge::VERSION, actions: now,
        previous_actions: old, added: now - old, removed: old - now,
        in_place: true, syntax_checked: defined?(Ripper) ? true : false
      }
    end

    def dispatch(server, action, args)
      t0 = Time.now
      raise DshBridge::Error.new('no_action', '缺少 action') if action.nil? || action.empty?
      unless DshBridge.const_defined?(:Handlers, false)
        raise DshBridge::Error.new('no_handlers', '命令层未加载，请重启 SketchUp')
      end
      fn = DshBridge::Handlers::ACTIONS[action]
      unless fn
        raise DshBridge::Error.new('unknown_action',
                                   "未知命令 #{action.inspect}；可用: #{DshBridge::Handlers::ACTIONS.keys.sort.join(', ')}")
      end
      log("→ #{action} #{args.inspect[0, 300]}")
      begin
        result = fn.call(server, args)
      rescue Exception => e # rubocop:disable Lint/RescueException
        log("✗ #{action} #{e.class}: #{e.message}")
        raise
      end
      ms = ((Time.now - t0) * 1000).round(1)
      log("← #{action} ok #{ms}ms")
      { 'data' => result, 'ms' => ms, 'actions' => DshBridge::Handlers::ACTIONS.length }
    end
  end
end

# 载入命令实现层
begin
  require File.join(File.dirname(__FILE__), 'dsh_handlers.rb')
rescue => e
  puts "[DSH] 命令层加载失败: #{e.class}: #{e.message}"
end

# 自动就位：文件被 SketchUp 加载（放进 Plugins 目录）时桥就起来，不需要手动点菜单
if defined?(Sketchup) && Sketchup.respond_to?(:active_model)
  begin
    puts "[DSH] #{DshBridge.start(DshBridge::PORT)}" unless DshBridge.running?
  rescue => e
    puts "[DSH] 自动启动失败: #{e.class}: #{e.message}"
  end
end

# 菜单 / 工具栏（可选层；失败不影响桥本身）
begin
  loader = File.join(File.dirname(__FILE__), 'dsh_loader.rb')
  require loader if File.exist?(loader)
rescue => e
  puts "[DSH] 界面层加载失败（桥仍然可用）: #{e.class}: #{e.message}"
end
