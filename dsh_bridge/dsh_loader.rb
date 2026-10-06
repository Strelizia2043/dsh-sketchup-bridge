# dsh_loader.rb -- DSH <-> SketchUp 桥接插件（界面层，不阻塞）
#
# 关键设计教训（真踩过）：**桥是靠 UI 定时器驱动的，任何 UI.messagebox 都会把桥冻住。**
# 症状：点了"自检"弹框 → 框还没点掉 → DSH 那边发来的命令全部超时。
# 所以这一层里所有反馈都走 **非模态的 HtmlDialog**，绝不阻塞事件循环。
#
# 另一个教训：自检按钮原本用 read_nonblock 读回包，数据没到齐就只读到几个字节，
# 于是拿着半截 JSON 去 parse，报出"连接失败: JSON::ParserError"。修法是 IO.select 等齐。
#
# 浮窗用 Sketchup::Http::Request 去请求自己的回环端口，而不是在本进程里另开 socket
# 阻塞等待——这样"刷新"是一次不阻塞的 HTTP 往返，桥在期间照常服务 DSH。

module DshBridge
  module Panel
    module_function

    def dialog
      @dialog ||= build
    end

    def build
      require 'sketchup' if defined?(Sketchup) && !defined?(Sketchup::Http::Request)
      dlg = UI::HtmlDialog.new(
        dialog_title: 'DSH 桥',
        preferences_key: 'dsh_bridge_panel',
        width: 460,
        height: 380,
        resizable: true,
        style: UI::HtmlDialog::STYLE_DIALOG
      )
      dlg.add_action_callback('refresh') { |_ctx, _p| dlg.set_html(page) }
      dlg.add_action_callback('start')   { |_ctx, _p| DshBridge.start(DshBridge::PORT); dlg.set_html(page) }
      dlg.add_action_callback('reload') do |_ctx, _p|
        begin
          DshBridge.reload
        rescue StandardError => e
          @last_error = "#{e.class}: #{e.message}"
        end
        dlg.set_html(page)
      end
      dlg.add_action_callback('cube') do |_ctx, _p|
        @last_result = test_cube
        dlg.set_html(page)
      end
      dlg.set_html(page)
      dlg
    end

    # 用 HTTP 请求自己的桥，等价于 DSH 那边做的事——这才是真正的端到端自检
    def self_test_async(dlg)
      @last_result = '正在自检…'
      begin
        req = Sketchup::Http::Request.new(
          "http://#{DshBridge::HOST}:#{DshBridge::PORT}/ping",
          Sketchup::Http::GET
        )
        req.headers = { 'X-DSH-Token' => DshBridge::TOKEN, 'X-DSH-Action' => 'ping' }
        req.start do |_request, response|
          begin
            body = response.body.to_s
            reply = JSON.parse(body)
            @last_result =
              if reply['ok']
                d = reply['result']['data']
                "✅ 连通正常 —— 桥 v#{d['version']} / SketchUp #{d['sketchup']} / Ruby #{d['ruby']} / #{d['actions'].length} 条命令"
              else
                "⚠️ 连上了但请求失败：#{reply['error'].inspect}"
              end
          rescue StandardError => e
            @last_result = "⚠️ 回包无法解析（#{e.class}）：#{body.to_s[0, 200]}"
          end
          begin
            dlg.set_html(page)
          rescue StandardError
            nil
          end
        end
        '自检已发出，结果稍后自动刷新。'
      rescue StandardError => e
        @last_result = "❌ 自检请求发不出去：#{e.class}: #{e.message}"
        "❌ #{e.message}"
      end
    end

    def test_cube
      m = Sketchup.active_model
      return '当前没有打开的模型，无法建方盒。' unless m
      m.start_operation('DSH 测试立方体', true)
      pts = [[0, 0, 0], [1000.mm, 0, 0], [1000.mm, 1000.mm, 0], [0, 1000.mm, 0]]
      face = m.entities.add_face(pts.map { |p| Geom::Point3d.new(*p) })
      face.pushpull(-1000.mm) if face
      m.commit_operation
      m.active_view.zoom_extents
      '✅ 已创建 1000×1000×1000 毫米立方体（可一步撤销）。'
    end

    def esc(s)
      s.to_s.gsub('&', '&amp;').gsub('<', '&lt;').gsub('>', '&gt;')
    end

    def page
      st = DshBridge.running? ? DshBridge.server.status : nil
      rows = []
      rows << ['状态', st ? '运行中' : '<b style="color:#c00">未运行</b>']
      rows << ['监听', "#{DshBridge::HOST}:#{DshBridge::PORT}"]
      rows << ['DSH 连接', st && st[:client] ? "已连接（#{st[:client_since]}）" : '等待中']
      rows << ['请求 / 成功 / 失败', "#{st ? st[:requests] : 0} / #{st ? st[:served] : 0} / #{st ? st[:failed] : 0}"]
      rows << ['最后命令', (st && st[:last_action]) || '-']
      rows << ['最后错误', (st && st[:last_error]) || '-']
      rows << ['命令数', (DshBridge.const_defined?(:Handlers) ? DshBridge::Handlers::ACTIONS.length : 0).to_s]
      rows << ['版本', "v#{DshBridge::VERSION} / SketchUp #{Sketchup.version}"]
      rows << ['截图目录', DshBridge::SHOT_DIR]

      tr = rows.map do |k, v|
        "<tr><td class=k>#{esc(k)}</td><td class=v>#{v}</td></tr>"
      end.join

      msg = @last_result ? "<div class=msg>#{esc(@last_result)}</div>" : ''

      <<~HTML
        <!DOCTYPE html><html><head><meta charset="utf-8"><style>
          body{font:13px/1.6 "Microsoft YaHei",system-ui,sans-serif;margin:0;padding:14px;background:#f7f7f8;color:#222}
          h3{margin:0 0 10px;font-size:15px}
          table{border-collapse:collapse;width:100%}
          td{padding:3px 6px;border-bottom:1px solid #e6e6e9;vertical-align:top}
          td.k{color:#666;width:38%;white-space:nowrap}
          td.v{font-family:Consolas,monospace;word-break:break-all}
          .msg{margin:10px 0;padding:8px 10px;background:#fff;border-left:3px solid #2a7;border-radius:3px}
          .bar{margin-top:10px;display:flex;gap:6px;flex-wrap:wrap}
          button{font:12px "Microsoft YaHei",sans-serif;padding:5px 10px;border:1px solid #ccc;background:#fff;border-radius:4px;cursor:pointer}
          button:hover{background:#eee}
          .hint{color:#888;font-size:11px;margin-top:8px}
        </style></head><body>
          <h3>DSH 桥</h3>
          <table>#{tr}</table>
          #{msg}
          <div class=bar>
            <button onclick="location='skp:refresh'">刷新</button>
            <button onclick="location='skp:start'">启动桥</button>
            <button onclick="location='skp:reload'">重载命令层</button>
            <button onclick="location='skp:cube'">建测试立方体</button>
          </div>
          <div class=hint>注意：任何模态对话框都会冻住桥（定时器停摆）。所以这里不用弹框，全部就地刷新。</div>
        </body></html>
      HTML
    end
  end

  module Menu
    module_function

    def show_panel
      d = Panel.dialog
      d.set_html(Panel.page)
      d.show
      Panel.self_test_async(d)
      nil
    end

    def build
      menu = UI.menu('Plugins').add_submenu('DSH 桥')
      menu.add_item('状态 / 自检（非阻塞面板）') { show_panel }
      menu.add_item('重新加载命令层（不重启 SketchUp）') do
        begin
          r = DshBridge.reload
          Panel.instance_variable_set(:@last_result,
                                      "✅ 命令层已重载：#{r[:actions].length} 条（新增 #{r[:added].inspect}，移除 #{r[:removed].inspect}）")
          show_panel
        rescue StandardError => e
          Panel.instance_variable_set(:@last_result, "❌ 重载失败：#{e.class}: #{e.message}")
          show_panel
        end
      end
      menu.add_item('创建一个 1000mm 测试立方体') do
        Panel.instance_variable_set(:@last_result, Panel.test_cube)
        show_panel
      end
      menu.add_separator
      menu.add_item('启动桥') do
        DshBridge.start(DshBridge::PORT)
        show_panel
      end
      menu.add_item('停止桥') do
        DshBridge.stop
        Panel.instance_variable_set(:@last_result, '桥已停止。')
        show_panel
      end
      menu
    rescue StandardError => e
      puts "[DSH] 菜单创建失败: #{e.class}: #{e.message}"
      nil
    end

    def build_toolbar
      tb = UI::Toolbar.new('DSH 桥')

      c1 = UI::Command.new('DSH 状态') { show_panel }
      c1.tooltip = 'DSH 桥状态 / 自检'
      c1.status_bar_text = '打开非阻塞状态面板，并发起一次真正的端到端自检'
      tb.add_item(c1)

      c2 = UI::Command.new('DSH 重载') do
        begin
          r = DshBridge.reload
          Panel.instance_variable_set(:@last_result, "✅ 命令层已重载：#{r[:actions].length} 条命令")
        rescue StandardError => e
          Panel.instance_variable_set(:@last_result, "❌ 重载失败：#{e.class}: #{e.message}")
        end
        show_panel
      end
      c2.tooltip = '重载命令层（不重启 SketchUp）'
      c2.status_bar_text = '从磁盘重载 dsh_handlers.rb'
      tb.add_item(c2)

      c3 = UI::Command.new('DSH 测试立方体') do
        Panel.instance_variable_set(:@last_result, Panel.test_cube)
        show_panel
      end
      c3.tooltip = '建一个 1000mm 测试立方体'
      c3.status_bar_text = '在原点创建 1000×1000×1000 毫米立方体，用于确认 DSH 能否看到几何'
      tb.add_item(c3)

      tb.show
      tb
    rescue StandardError => e
      puts "[DSH] 工具栏创建失败: #{e.class}: #{e.message}"
      nil
    end
  end
end

begin
  DshBridge::Menu.build
  DshBridge::Menu.build_toolbar
rescue StandardError => e
  puts "[DSH] 界面层初始化失败: #{e.class}: #{e.message}"
end

# 说明：这里刻意不写 `file_loaded(__FILE__)`。
# 那是给 SketchupExtension#load 做重复加载防护用的；我们是直接落在 Plugins 目录由
# SketchUp 一次性加载，不需要它。而且它是修饰符 if 写法、不以 end 收尾，
# 会让我那条"必须 end 收尾"的完整性检查虚报（已经踩过一次）。
