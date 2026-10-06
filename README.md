# DSH ↔ SketchUp 桥

让 DSH 能直接操作你的 SketchUp：建几何、改材质、取景截图、撤销、存盘。
只监听 `127.0.0.1:9877`，必须带 token，写盘默认只允许落在 DSH 工作区内。

```
DSH ──(JSON over TCP 回环)──> dsh_bridge.rb ──> dsh_handlers.rb ──> SketchUp Ruby API
                                    │
                                    └── shot 命令 → shots/*.png → DSH 用 read_image 看图
```

## 三个文件的分工（决定了什么时候要重启 SketchUp）

| 文件 | 作用 | 改动后 |
|---|---|---|
| `dsh_bridge.rb` | Socket、调度、分帧、token | **要重启 SketchUp** |
| `dsh_handlers.rb` | 所有命令的实现 | **不用重启**，发 `reload` 命令热重载 |
| `dsh_loader.rb` | 菜单、工具栏、"自检"按钮 | 不用重启（重载命令层时一并生效） |

所以正常情况下，我们只在第一次安装时重启一次。

## 安装（三步，约 30 秒）

1. 把 `dsh_bridge.rb`、`dsh_handlers.rb`、`dsh_loader.rb` **三个文件**复制到：

   ```
   %APPDATA%\SketchUp\SketchUp <版本>\SketchUp\Plugins\
   ```

2. 重启 SketchUp（首次加载未签名插件，会弹确认 —— 点同意/是）。

3. 验证：菜单 **Plugins → DSH 桥 → 自检（验证 DSH 能否连上）**，应显示 ✅。

> 桥在文件被加载时会**自动启动**，不需要手动点菜单。

## 自检与排错

工具栏上有一个 **DSH 自检** 按钮。它不依赖 DSH，而是自己按同一套协议打一条真实请求，
所以能自己回答"到底是哪一环坏了"：

| 自检结果 | 含义 |
|---|---|
| ✅ 连通正常 | 端到端没问题，DSH 可以连 |
| ❌ 连接失败 | 桥在跑但端口连不上：被别的程序占用，或防火墙拦了回环 |
| ⚠️ 连上了但请求失败 | 协议对不上：多半是 token 或命令层没加载 |

菜单 **Plugins → DSH 桥 → 状态** 会显示：是否运行、有没有客户端连着、请求/成功/失败计数、
最后一条命令、最后一条错误。

## 命令一览

| 命令 | 参数 | 说明 |
|---|---|---|
| `ping` | — | 版本、Ruby 版本、SketchUp 版本、可用命令列表 |
| `status` | — | 桥与模型的运行状态 |
| `eval` | `code`(串或数组)、`undo`(默认 true)、`op_name`、`preview`、`print` | 执行 Ruby，`puts` 的输出会回传 |
| `info` | `scope`(top/all/faces/edges/selection)、`limit`、`depth` | 模型概览：实体、尺寸、材质、Tag、场景、相机 |
| `shot` | `width`、`height`、`camera{eye,target,up,fov,perspective}`、`name`、`restore` | 截图到工作区，返回路径 |
| `save` | `path`、`overwrite` | 存盘，默认落 `sketchup-bridge/models/` |
| `undo` / `redo` | `count` | 撤销 / 重做 |
| `history` | `limit` | 撤销栈里的操作名（能看出"我到底改了什么"） |
| `select` | `ids` | 按 entityID 选中 |
| `erase` | `ids` 或 `all:true` + `confirm:true` | 删除 |
| `focus` | `id` / `ids` / 空 | 把镜头对准某物或整个模型 |
| `measure` | `from`、`to`（毫米） | 量距离，用来核对看图估出来的尺寸 |
| `import` / `export` | `path` | 导入 / 导出模型 |
| `reload` | — | 从磁盘重载命令层（不重启 SketchUp） |
| `help` | — | 命令与参数说明 |

**单位约定：所有对外的坐标与尺寸一律毫米**，换算在桥里做，DSH 不用碰英寸。

## 为什么它比"盲写代码"准

这是"让我操作得更准"的几条具体机制，不是空话：

1. **每条命令都自报影响面。** `eval` 的回传里带 `changed`（撤销栈是否增长）、
   `model_entities`（当前顶层实体数）、`output`（你 `puts` 的东西）。我能立刻看出
   "这条命令到底动没动模型"，而不是猜。
2. **`preview` 干跑。** `preview: true` 会执行完立刻撤销，先看会发生什么再决定要不要留下。
   破坏性操作可以零风险试。
3. **撤销边界干净。** 整段代码包成一个 SketchUp 操作，`op_name` 会出现在你的撤销菜单里，
   你能看到"DSH 干了什么"，也能一步撤回。出错时自动 `abort_operation`，不留半成品。
4. **`measure` 校准。** 我从截图估尺寸会偏，用它量实际距离来纠正。
5. **`focus` 等价于"把镜头对准"。** 不靠猜坐标取景。
6. **输出自动截断。** 大 `puts` 不会把我的上下文冲掉（这也是省钱）。
7. **热重载。** 改命令逻辑不用你重启 SketchUp，省的是你的时间，也是联调的 token。

## 客户端

有 `.cmd` 和 `.ps1` 两个等价包装（`.ps1` 受执行策略限制，`.cmd` 不受）：

```powershell
cd <你克隆下来的目录>
.\sk.cmd ping
.\sk.cmd info
.\sk.cmd ruby "puts Sketchup.version"
.\sk.cmd ruby "ents = Sketchup.active_model.entities" --Values
.\sk.cmd shot --name look1
.\sk.cmd reload
.\sk.cmd undo 1
.\sk.cmd              # 不带参数 = 交互式 shell
```

直接调 Python 也一样（注意 `>` 会被 PowerShell 当重定向，所以带比较符的 Ruby 代码要用单引号或写进 `.rb` 文件跑）：

```powershell
$py = "python"
& $py sk_client.py ping
```

当库用：

```python
from sk_client import SC
c = SC()
c.ping()
c.ruby(['m = Sketchup.active_model',
        'm.entities.add_face([0,0,0], [1000.mm,0,0], [1000.mm,1000.mm,0], [0,1000.mm,0])'])
print(c.shot('cube'))
```

超时说明：`SC(timeout=...)` 配的值就是唯一生效的值，便利方法不会偷偷覆盖它
（这条是踩过坑之后加的，`test_convenience_wrappers_do_not_override_timeout` 盯着它）。

## 离线自测

不需要 SketchUp，用假服务器把客户端的每条路径都跑一遍：

```powershell
& $py test_bridge_protocol.py
```

覆盖：正常往返、鉴权失败、分片到达（3 字节一片）、连接被中途关闭、超时、
未知命令、非 JSON 回传、中文往返、大 payload、Ruby 文件完整性。

## 日常使用流程（重要）

改 `dsh_handlers.rb` 之后，**必须同步到插件目录再 reload**，因为 `reload` 读的是
`File.dirname(__FILE__)`，也就是插件目录里的那份：

```powershell
# 1) 改工作区代码后先同步
Copy-Item dsh_handlers.rb "%APPDATA%\SketchUp\SketchUp <版本>\SketchUp\Plugins\" -Force
# 2) 再热重载（不用重启 SketchUp）
.\sk.cmd reload
```

只有改 `dsh_bridge.rb`（基础设施）才需要重启 SketchUp。

## 验证脚本一览

| 脚本 | 用途 | 需要 SketchUp |
|---|---|---|
| `test_bridge_protocol.py` | 21 项离线自测（协议、错误路径、回归钉） | ❌ |
| `verify_e2e.py` | 端到端：info → 建几何 → 截图 → 历史 | ✅ |
| `verify_clean.py` | 干净全流程：清空 → 建方块 → 截图 → 撤销 → 再截图 | ✅ |
| `verify_final.py` | 8 项验收（连通/热重载/撤销 API/建几何/preview/undo/截图） | ✅ |
| `verify_step.py` | 分步验证，崩了能停在出事那一步 | ✅ |
| `diag_const.py` / `diag_undo.py` | 语言行为与 API 探测（改代码前先问，别猜） | ✅ |

## 安全边界

- 只绑定 `127.0.0.1`，外部网络连不上。
- 必须带正确 token（写在 `dsh_bridge.rb` 的 `TOKEN`）。
- `save` / `export` 默认拒绝写工作区之外，要写别处必须显式传 `allow_outside`。
- `erase all` 必须显式 `confirm: true`。
- 桥**不绕过任何 SketchUp 自身的确认**：它做的事等价于你手动敲 Ruby 控制台。

## 踩过的坑（都是实测出来的，不是猜测）

留在这里是因为每一条都曾让"能不能用"变成"用不了"，而且都很容易被重新踩回去。

| 坑 | 症状 | 真因 | 现在的防线 |
|---|---|---|---|
| **模态对话框会冻住桥** | 点"自检"弹框后，DSH 发来的命令全部超时 | 桥靠 `UI.start_timer` 驱动，`UI.messagebox` 是模态的，会停掉事件循环 | 界面层全部改用非阻塞 HtmlDialog，禁止弹模态框 |
| **`shutdown(SHUT_WR)` 再 `close` 会丢回包** | 桥"每连必断"，客户端 `recv` 立刻拿到 `b''` | Windows 上对端还有未读数据时，这样关会发 RST 而不是 FIN | 只用 `close`；有回归测试钉死不许出现 `shutdown` |
| **`const_defined?` 会沿祖先链查找** | 热重载报 `NameError: constant Object::Handlers not defined` | `Object` 在 `DshBridge` 祖先链上，被误判成 Handlers 存在 | 一律用 `const_defined?(:Handlers, false)` |
| **`undo_stack_length` / `active_operations` 在此版本不存在** | 建了三个物体却报 `changed=false`，history 返回空 | SketchUp 2026 没有这两个方法（`respond_to?` 只有 `start_operation`） | 改用实体/面/边/材质计数快照做 `delta`；history 如实报告哪些方法可用 |
| **残骸连接会堵死整个桥** | 一条连接断开后，后续连接全部无响应 | "一次只服务一条连接"的设计 + 不回收 | `pump_accept` 空闲回收 + `ensure close_client` |
| **便利方法硬编码超时会覆盖配置** | 配了 0.4s 却干等 15s | `ping()` 内部写了 `timeout=15` | 全部透传 `self.timeout`；有回归测试 |
| **`.cmd` 文件用 UTF-8 中文注释会乱码** | cmd.exe 报一堆"不是内部或外部命令" | cmd.exe 按 OEM 码页读 `.cmd` | `sk.cmd` 只写 ASCII 注释 |
| **PowerShell 禁止运行 `.ps1`** | 无法加载 `sk.ps1` | 执行策略限制 | 提供等价的 `sk.cmd` |
| **撤销在 `Sketchup` 模块上，不在 `Model` 上** | `undo`/`preview` 报 `undefined method 'undo' for Sketchup::Model` | `Sketchup::Model` 只有 `start_operation`/`commit_operation`/`abort_operation`；`Sketchup.undo` / `Sketchup.redo` 才是真身 | 用 `Sketchup.undo`；`history` 会如实汇报两边的可用性 |
| **`Sketchup.undo` 成功时返回 `nil`** | 撤销明明生效，却报告 `undone=0`；`preview` 报"撤销返回 false" | 拿返回值当成功判据是错的 | 一律用**撤销前后的计数差**判断是否生效（`undo`/`redo`/`preview` 三处统一） |
| **`pushpull` 会让原 face 引用失效** | `add_group(原face)` 报 `TypeError: reference to deleted Entity` | SketchUp 2026 的 pushpull 会重建几何 | 成组用**新建的实体**（`e.to_a.last`），不要复用 pushpull 前的引用 |
| **`reload` 读的是插件目录，不是工作区** | 改完工作区、reload 说成功，但行为仍是旧的 | `File.dirname(__FILE__)` 指向插件目录 | **改完必须先同步到插件目录，再 reload**（否则 reload 加载的是旧文件） |
| **临时模块里 eval 会污染词法作用域** | reload 报成功，但之后所有 handler 报 `uninitialized constant #<Module:0x...>::DshBridge::VERSION` | handler 在匿名模块里 eval，作用域指向假模块 | 生产的就是真模块（就地 load），语法风险用 `Ripper` 纯解析预检拦住 |
| **`pushpull` 沿面法线推，不是沿坐标轴** | 建房间时四面墙被推到地面**以下**（`z=-2800..0`），只有门头是对的 | 地面矩形（俯视逆时针点序）法线朝下 `z=-1`，`pushpull(+h)` 就往下长。实测：地面矩形 `pushpull(+300mm)` → 盒子落在 `z=-300..0` | 一律按法线判断方向：`face.pushpull(face.normal.z >= 0 ? h : -h)` |
| **不能用 `entities.to_a.last(n)` 收集"我刚建的实体"** | 102 个顶层实体：墙体碎成散件，只有一个垛进了组 | 那是**任意**实体，不是"你的"。pushpull 会生成多条边/面，数量根本猜不准 | **先把面收进组，再在组内推拉**——组内就只有这一个物体，不会抓错 |
| **`bounds` 已经是世界坐标** | 自检把正确的 2800mm 墙报成 0mm | 我又乘了一次 25.4（尺寸要换算，坐标不要） | 坐标直接用；只有需要毫米数值时对尺寸乘 25.4 |
| **修饰符 `rescue` 保护不了赋值** | `group.material = '不存在' rescue nil` 仍抛 `ArgumentError` | 修饰符 rescue 只作用于**右边那个表达式**，赋值本身在保护范围外 | 该用显式 `begin/rescue`，别用修饰符写法兜异常 |
| **`vertex.position` 返回的是组的本地坐标，不是世界坐标** | 校验脚本把正确的几何误报成"偏移 120mm""天花板在地面" | 该天花组的 `transformation.origin.z = 2900`，但组内顶点读出来是 `100`；渲染图显示天花明明盖在墙顶 | 世界坐标 = 本地坐标 + **父链上所有** `transformation.origin` 之和。本版本 `Transformation` 只有 `origin`（没有 `world_to_local`、也不支持 `tr * bounds`），所以对未旋转的组用 origin 累加即可 |
| **同一个组里先后 `add_face` 会让世界 bounds 算错** | 房间"地面 + 天花"放进同一组后，组的 bounds 被拉伸（x +120、y +4320），但组内顶点是对的 | 实测隔离开关：只建地面 → 正确；同组内加天花 → 拉伸；天花建成独立组 → 两个都正确 | 地面/天花都建成**实体板**（走已验证的 `box_on_ground`），再收进一个父组。既绕开问题，几何也更真实 |
| **"低于地面"的检查阈值太宽会漏掉真错** | 楼板整体挂在 `z=-100..0`，我的检查写的是"低于 −1 才报警"，正好放过 | 阈值掩盖了系统性偏移 | 校验要报**完整区间**，让人看到 `z=[-100, 0]` 而不是只问"是否低于某个数" |
| **DSH 工具层会把长输出截断到约 4000 字符** | 几何校验的 JSON 被截成半截，解析失败 | 68 个构件的全量输出约 4KB，**没到桥的 `MAX_OUT`（200KB）**，是工具层显示截断 | 脚本只回传"摘要 + 异常项"，不全量回传。我为此先怀疑解析器、又错改了桥的 `MAX_OUT`，绕了两圈 |
| **测试脚本顺序串了会误判** | 几何校验报"X 超出建筑范围"，看着像几何错了 | 负向测试先跑，留了坏模型在 SketchUp 里；几何校验却拿好数据的期望去核对 | 回归顺序固定为：**正向构建 → 几何校验 → 疑问清单 → 读图链路 → 负向测试（放最后）** |
| **转角延伸会让洞口跟着漂** | 入户门框跑到 `x=1080..1140`（数据声明 1200..2200），客厅窗同样偏 −120 | 洞口用的是**沿墙局部坐标 `u`**，而转角延伸把墙的 `from` 端点外移了 120mm，`u` 没跟着平移 | `wall_with_extensions` 里同步 `o['u'] += extr_from`。**门窗位置错比转角缺口严重得多**，这是修转角时引入的 |
| **打点采样式的位置检查反复假阳性** | 洞口位置检查对好模型也误报 13~14 处 | 四版尝试全部失败（见下） | **删掉这个检查**。反复假阳性的检查比没有检查更糟：消耗信任、掩盖真信号 |
| **用正则批量改代码会改坏结构** | Python 文件里留下零散 `]`，语法错误 | 结构化编辑不能用正则（它对上下文一无所知） | 老老实实逐个精确替换，或重写文件 |
| **PowerShell `Set-Content -Encoding UTF8` 会把中文变乱码** | 整个文件的中文变成 `鐢熸垚涓€寮?` | 读入时按 ANSI 解码、写出时按 UTF-8 编码，字节被重解释 | 非 ASCII 内容**绝不用 shell 文本处理**，一律用编辑器工具 |

## 完整链路（截至 Round 7）

```
图纸图像(平面/立面)
    │
    ├─ plan_probe.py ──── 量图：墙线检测 / 裁剪放大 / 比例换算
    │
    ├─ extract_plan.py ── 提取：像素 → 毫米 → 结构化 JSON（单位闸门 + 墙厚打回）
    │                     └ 水平墙与竖直墙的洞口都识别
    │
    ├─ 疑问清单 ───────── 从 source/confidence 自动生成，先问后建
    │
    ├─ build_from_json.py / build_from_plan.rb ── 生成几何
    │     楼板·房间地面天花·内外墙·门洞窗洞·门扇窗框玻璃·楼梯·立面轮廓
    │
    ├─ check_geometry.py ─ 逐构件核对世界坐标
    ├─ measure 实测 ─────── 期望值从数据推导，不硬编码
    └─ view_mode.py ────── 审查视图（平面审查 / 只看结构 / 分层）

自检工具：
    test_bridge_protocol.py   桥协议 21 项
    verify_reading.py         读图能力边界（像素→毫米）
    verify_pipeline.py        全链路集成 8/8（合成图纸 → 提取 → 对比真值）
```

### 3. 立面轮廓要"坐落"在基面上（`base_z`），不要用绝对标高硬怼

女儿墙、屋面构件应当声明它坐在什么之上：

```json
"base_z": 2950,
"profile": [[0, 0], [6000, 0], [6000, 450], [0, 450]]
```

即"坐在 2950 的屋面板顶面上，自身高 450"。

**反面教材**（我踩过）：把 `2800` 直接写进轮廓 → 女儿墙与屋面板
**Z 向重叠 150mm**，两者穿模。

### 4. 顶板必须抬到**最高楼面之上**

```json
"envelope_ceiling": { "thickness": 150, "z": 3000 }
```

默认标高 = `max(墙顶, 所有楼板顶面)`。若建筑里有夹层且其高度超过墙顶，
把顶板放在墙顶就会与夹层相撞（实测：夹层 2800..2920 ∩ 顶板 2800..2950，
**重叠 120mm**）。用 `"z"` 显式指定可覆盖默认值。

### 5. 接口检查（`diag_joints.py`）

量四类接口 + 重叠分类：

| 检查 | 判据 |
|---|---|
| 内墙 ↔ 外墙 | 应有搭接（负缝）或齐平（零缝），不能有正缝 |
| 门窗料 | 按"墙名/洞口名"归组，位置应与洞口一致 |
| 楼梯 ↔ 楼板 | 末级顶面应与到达楼面齐平 |
| 楼板 ↔ 外墙 | 应有搭接，不能有缝 |
| 主体重叠 | 区分三类：**支座搭接**（楼梯落在楼板上，合理）、**转角接头**（垂直构件互相穿透，合理）、**非预期穿模**（三向都大，报错） |

判定"合理重叠 vs 穿模"的经验规则：
**平面内小重叠（<400mm）+ 全高重叠 = 转角接头；三个方向都有可观重叠 = 真穿模。**

## 几何配合的三条硬约定（用户指出缺陷后定下的）

这三条是**建筑常识**，不是我的偏好。违反任何一条，模型看起来就有毛病。

### 1. 墙要闭合成直角，不能缺角也不能简单叠加

**墙厚居中于轴线**时，两面成直角的外墙会在转角各缺一个 `(t/2)²` 的空洞。
实测证据（修之前）：南墙 `x=0..6000`、西墙 `x=-120..120`
→ 西南角 `(-120,-120)` 被 **0 面墙**覆盖，四个角全中。

修法：把墙在**与其他墙相接**的端部沿轴线延伸**半个自身墙厚**。
两端各延伸半厚 ⇒ 恰好覆盖到外角，相邻墙在转角搭接，外表面连续。

- 只在"确有别的墙接在这里"时延伸（用点到线段距离判定，容差 60mm）
- 外轮廓因此精确：6000 跨 → 6240 外包络（每端多 120）
- **不要**用 `index(wall)` 在循环里定位，也不要每面墙重算一遍全部相接关系

### 2. 天花板要盖在墙顶上，或与墙严丝合缝

**按房间生成天花有根本弱点**：它只盖到房间内轮廓，盖不住墙体本身，
墙顶会露出一圈。

所以生成一块**整层顶板** `ROOF-整层顶板`：用所有墙的**原始轴线范围 + 半墙厚**
做连续板，z 区间 `[墙顶, 墙顶+厚]`，与墙体齐平不重叠。

- 出挑用 `"envelope_ceiling": {"eave": 300, "thickness": 150}` 指定
- `"envelope_ceiling": false` 可关掉
- ⚠️ 包络要用**原始轴线**再加半厚。用"已延伸过的轴线"再加半厚会把半厚加两次
  （实测：顶板变成 6480×8480，比正确的 6240×8240 各多 240）

### 3. 自动检查（防止以后改回去）

`check_geometry.py` 现在会检查：

- 外墙四个角是否各被 **≥2 面墙**覆盖（抓缺角）
- 天花板底面是否**等于**墙顶标高（抓错位）
- 是否有构件低于地面
- 模型整体范围是否与数据声明的吻合

任何一条不过，退出码非 0。

## 能力清单（截至 Round 9）

| 构件 | 支持 | 说明 |
|---|---|---|
| 楼板 / 房间地面 / 天花 | ✅ | 实体板，标高语义见下表 |
| 外墙 / 内墙 | ✅ | 任意角度直墙，墙厚居中于轴线 |
| 门洞 / 窗洞 | ✅ | 拆块法（不用布尔），带窗台高 |
| **门扇 / 窗框 / 玻璃** | ✅ | opt-in（`"joinery": true`） |
| **楼梯** | ✅ | 实心踏步逐级堆叠，rise/tread 从数据推 |
| 立面轮廓（女儿墙/坡屋顶/山墙） | ✅ | `(u,z)` 剖面拉伸，支持洞口 |
| 屋顶面（坡屋面几何） | ❌ | 需用户给形式；目前可用立面轮廓表达 |
| 家具 / 材质贴图 | ❌ | 按用户政策"润色要发话"，未实现 |

## 读图能力（实测边界，别越界使用）

| 能可靠读出 | 误差 |
|---|---|
| 建筑总尺寸 | ≤4mm |
| 轴线位置 | ≤2mm |
| **水平墙洞口** 起点/宽度 | ≤6mm |
| **竖直墙洞口** 起点/宽度 | ≤9mm |

| 不可靠 / 未实现 | 说明 |
|---|---|
| **墙厚** | 相对误差 5~10%，**必须读标注或问用户**，不许量 |
| 洞口类型（门/窗） | 窗可判（洞口内 ≥3 条贯穿线 → `window`/`medium`）；<br>**门与净洞口在图像层面无法区分**，一律 `door`/`low` 并问用户 |
| 弧形洞口、飘窗、转角窗 | 未实现 |
| 斜墙 / 弧墙的洞口 | 未实现 |
| 房间轮廓 | 由墙线围合推断，有隔墙时需人工核对 |
| 文字内容（房间名/编号） | 无 OCR，靠视觉读 + 疑问清单兜底 |

### 洞口类型判别的实测依据

`diag_opening_type.py` 在已知真值的合成图纸上量出来的：

| 洞口 | 真值 | 洞口内贯穿线数 |
|---|---|---|
| 南墙 M1 | 门 | **1** |
| 南墙 C1 | 窗 | **4** |
| 东墙 C2 | 窗 | **3** |

所以阈值取 **≥3 ⇒ 窗**。这是**保守用法**：只在有正向证据时下结论；
没有证据时说"判不出来"而不是猜。判为窗只给 `medium`（真图窗符号线数可能不同），
且窗高/窗台高仍标为推定值要用户确认。

## 各构件的标高语义（`box_on_ground` 建的是 `[z0, z0+h]`）

| 构件 | 期望区间 | 传参 |
|---|---|---|
| 楼板（`floors[].z` 是**顶面**） | `[z, z+厚]` | `z0 = z` |
| 房间地面 | `[z, z+厚]` | `z0 = z` |
| 房间天花 | `[z+层高, z+层高+厚]` | `z0 = z + ceiling` |
| 墙体 | `[base_z, base_z+高]` | `z0 = base_z` |
| 楼梯第 i 级 | `[0, i×rise]` | 从地面长到该级顶面 |
| 门窗框料 | `[洞口底, 洞口顶]` | 用 `box_plate` |

**不要**为了"厚度向下"而传 `z - 厚`——那会把构件挂到地面以下（踩过）。

## 建几何的正确姿势（血泪版）

```ruby
# ✅ 对：先把面收进组，再在组内按法线方向推拉
face  = ents.add_face(四个角点)
group = ents.add_group(face)
face.pushpull(face.normal.z >= 0 ? h : -h)   # 地面矩形法线朝下，所以要取反
group.name = 'DSH-某面墙'

# ❌ 错：先推拉再回头收集实体成组
face.pushpull(h)
group = ents.add_group(ents.to_a.last(10))   # last(10) 是任意实体，必错
```

### reload 的五次迭代（值得单独记住）

| 版本 | 做法 | 结果 |
|---|---|---|
| v1 | `DshBridge.const_defined?(:Handlers)` | 沿祖先链误判 → `NameError: Object::Handlers` |
| v2 | `remove_const` + `module_eval` | 留下"Handlers 不存在"的窗口 → **进程静默崩溃** |
| v3 | 临时模块验证 + `const_set` | 常量路径写错，被自家防线拦下（拦对了） |
| v4 | 路径修对 | reload 报成功，**之后所有 handler 全废**（词法作用域污染） |
| **v5** | `Ripper` 语法预检 + **就地重开生产模块** | ✅ 稳定，可反复调用 |

结论：**"先加载一份副本用于验证"这条路从原理上不通**——副本要么不能拿到生产用，
要么它的词法作用域与生产不一致。正确做法是让生产代码本身就地更新，
把"文件被写坏"这个唯一残留风险用**只解析不执行**的语法检查挡住。

热重载的边界：`dsh_handlers.rb` 可以随时热重载；`dsh_bridge.rb`（基础设施）改动**必须重启 SketchUp**。
万一 reload 方法本身坏了，可以用 `dsh_bridge_patch.rb` 在服务存活期间把方法级修正推进去：

```python
c.ruby("load '<工作区目录>/dsh_bridge_patch.rb'", undo=False)
c.reload()
```
