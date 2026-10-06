# DSH 接手指南 —— 重启后从这份开始读

> **为什么有这份文件**：DSH 的对话记忆在重启后**会清空**，
> 但工作区的文件不会。所以"重启还能不能继续用"取决于
> **该知道的都写下来了没有**。
> 这份文件就是那根接力的棒子：**按顺序读，就能接上。**

---

## 0. 三十秒恢复上下文

```bash
python version.py            # 当前版本 + 组件 + 测试清单
python version.py --all      # 加上组件与测试明细
```

**版本权威只有一个文件：`version.json`。** 别的地方不许写死版本号
（这条是被坑出来的：`dsh_bridge.rb` 里曾长期写着 `VERSION='1.0.0'`，
而它实际至少改过 5 版，于是"现在第几版"给不出可信答案）。

---

## 1. 架构：目录结构（换机器也能照搬）

```
sketchup-bridge/                       ← 工作区根目录（含 sk_client.py）
│
├─ dsh_bridge/                         ← **发布包**：装到另一台机器只用这个目录
│    ├─ dsh_bridge.rb      基础设施（socket 服务 / 命令分发） ← 改它要重启 SketchUp
│    ├─ dsh_handlers.rb    命令实现层（18 条）              ← 可热重载
│    ├─ dsh_loader.rb      菜单/面板（非阻塞 HtmlDialog）
│    ├─ dsh_parts.rb       通用构件库（墙/楼板/楼梯/材质）    ← 可热重载
│    ├─ DSH-接手指南.md      这份文件
│    ├─ dsh_workspace.json 工作区定位（install.py 按实际位置写）
│    └─ install.py         **一键安装**
│
├─ sk_client.py                        ← 桥的 Python 客户端（所有操作都经过它）
├─ version.py / version.json           ← 版本权威
├─ dsh_workspace.json                  ← 定位文件的副本（方便就地查看）
├─ dsh_paths.py                        ← 工具定位器（tool() / ROOT）
│
├─ tools/
│    ├─ cad/    dxf_probe / dxf_detail / dxf_import / dxf_render / dxf_draw / cad_to_plan
│    ├─ img/    intake_check / extract_plan / plan_probe
│    └─ build/  build_from_json / check_geometry / view_mode / diag_joints / derive_dims
│
├─ tests/       test_bridge_protocol / test_degradation / test_sweep
│               verify_restart / verify_cad / verify_parts / verify_flow
│               verify_pipeline / verify_reading / make_test_drawing
│
├─ archive/     归档，**装机包不带**
│    ├─ one-off/       针对某一张图写死坐标的（cad_project2 等）
│    ├─ superseded/    被新脚本取代的验收脚本
│    └─ diagnostics/   开发期研究 SketchUp API 的
│
└─ cad/ shots/ models/ flow_out/ degrade_out/     ← 数据与产物
```

## 1b. 装到另一台机器

```bash
# 1) 把整个 sketchup-bridge 目录复制过去（含 dsh_bridge/ 和 tools/）
# 2) 在那台机器上跑：
python dsh_bridge/install.py
```

`install.py` 做四件事：
1. 扫出 SketchUp 的 Plugins 目录（`%APPDATA%\SketchUp\SketchUp *\SketchUp\Plugins`）
2. 复制 4 个 `.rb` + 指南 + `dsh_workspace.json`
3. **按实际位置重写 `dsh_workspace.json`** ← 这一步是换机器能用的关键
4. 自检：源文件完整性、文件齐全、能不能连上桥

```bash
python dsh_bridge/install.py --list       # 只列出找到的 Plugins 目录
python dsh_bridge/install.py --dry-run    # 只说要做什么
python dsh_bridge/install.py --uninstall  # 卸载
```

**路径不写死**：桥按四步定位工作区 ——
① `dsh_workspace.json` 的 `home` ② 环境变量 `DSH_WORKSPACE`
③ **从桥自身位置向上找 `sk_client.py`**（换机器自动成立）
④ 兜底 `插件目录/sketchup-bridge/`。

第③条最可靠：只要工作区结构照搬，**连配置文件都不需要**也能找对。

「改插件要重启」只对 `dsh_bridge.rb` 成立；
`dsh_handlers.rb` 和 `dsh_parts.rb` **发一条 `{"action":"reload"}` 就生效**。

---

## 2. 两条技术路线（先判断用户给的是什么）

| | **A. 图片路线** | **B. CAD 直读** |
|---|---|---|
| 输入 | 照片 / 截图 / 扫描件 | .dxf（ASCII） |
| 精度 | 实测 建筑尺寸 ±48mm、洞口位置 ±27mm | **实体坐标，±0.01mm** |
| 标定 | 必须给比例（`--calib-px`） | **不需要** |
| 墙厚 | **量不准**（5~10% 误差，必须问用户） | 读出来的 |
| 洞口类型 | 靠"洞口内贯穿线条数"猜 | **颜色/图层直接给出** |
| 硬前置 | 不能斜拍（2% 透视偏 132mm，七版修正全失败） | 不涉及 |
| 手册 | `HOWTO-读图建模.md` | `HOWTO-CAD直读建模.md` |

> **能拿到 CAD 就绝不要用图片。** 差的是数量级。

### 2b. 有一条**必须记住的边界**：读图只支持**平面图**

**立面图、剖面图 —— 不读。** 代码里**没有立面的识别入口**。

这一条要单独写出来，因为很容易误会：

| 容易误会的地方 | 事实 |
|---|---|
| 数据模型里有 `elevations` 字段 | 那是**女儿墙/坡屋顶/山墙的 `(u,z)` 剖面坐标**，由用户给或手工写 —— **不是从立面图识别出来的** |
| 文档写过"图纸图像(平面/立面)" | 那是早期 README 的**误导表述，已改正** |
| `build_from_plan.rb` 里有 `'elevation'` 分支 | 那是**建模**分支（按剖面拉伸成体），不是读图分支 |

**所以这些数从哪来？——问用户：**

| 缺的信息 | 现在的做法 |
|---|---|
| 层高 / 墙高 | 平面图上**不标注** → 必然是 `source: assumed` → **进疑问清单问你** |
| 门窗高度 / 窗台高 | 同上，问你 |
| 屋顶形式（平/单坡/双坡/四坡） | 按工作政策**必须问，绝不自选** |
| 坡度与屋脊方向 | 问你 |

**用户明确表示过：不做立面图识别，这些靠问就行**（第 39 轮确认）。
所以**不要再自己去"补"这个功能** —— 那是重复劳动，而且是用户已经排除的方向。

判断当前是否真的在问，跑：

```bash
python tools/build/build_from_json.py plan.json            # 只看疑问清单，不建模
python tools/build/build_from_json.py plan.json --confirm  # 确认后才建
```

---

## 3. 标准工作流（两条路线共用后半段）

```bash
# A 路线
python intake_check.py 图片.png --calib-mm 6000      # 先评估能不能读
python extract_plan.py 图片.png --calib ... --out plan.json

# B 路线
python dxf_import.py 图纸.dxf                        # 先探查：图层/颜色/实体
python cad_to_plan.py cad_map.json --out plan.json   # 配置驱动生成

# 共用
python build_from_json.py plan.json          # **只看疑问清单，不动模型**
python build_from_json.py plan.json --confirm [--discard]   # 确认后才建模
python check_geometry.py plan.json           # 逐构件核对
```

**`build_from_json.py` 默认不建模**（要 `--confirm`）；
而且**当前文档里有东西时默认拒绝清空**（要 `--discard`）。
这两道闸都是被坑出来的：
- 前者：原先"默认就建"，等于默认绕过"先确认后建模"
- 后者：测试脚本反复把用户正开着的文档换掉，用户以为"模型自己变成了最早的试验模型"

---

## 4. 构件库 `dsh_parts.rb`（本轮新增，可热重载）

给 designproject2 建模时，这些逻辑原本散在 `p2_*.rb` 一次性脚本里。现已固化：

```ruby
load '<工作区目录>/dsh_parts.rb'
P = DshParts

# 墙（门只留洞；窗有玻璃+上下框+窗台墙）—— 洞口用**沿墙的绝对坐标**给
P.wall(ents, 'W-南', 'h', 50, 100, [0, 8250], 0, 2700,
       [{a: 250, b: 2100, kind: 'door'},
        {a: 3200, b: 6750, kind: 'window', sill: 900, height: 1500}],
       mat_wall: silver, mat_glass: glass, mat_frame: frame)

# 楼板挖洞（不用布尔运算，拆无重叠矩形；用**面积**验证）
P.slab_with_holes(ents, 'F2-楼板', 0, 0, 8250, 8250, 2700, 100,
                  [[2250, 2250, 6100, 6100], [6067, 100, 8050, 2050]])

# 螺旋楼梯（扇形踏面，不是薄片堆叠）
P.spiral_stair(ents, 'ST', 7058, 1125, 900, 0, 2800, steps: 16, total_deg: 420)

# 材质：取或建（名字不存在**不抛异常**）；批量刷
P.mat(model, 'DSH_Silver', [176, 180, 186])
P.paint(groups, silver, 'W-')     # 返回刷了几组
```

**三条内置的约定**（每条都是踩坑换来的）：
1. 洞口用**绝对坐标**，不用 `u` —— `u` 从墙的 `from` 端量起，
   墙端一变 `u` 的基准就变，实测漂过 25~284mm，而且**没有任何报错**
2. **不用布尔运算**：带洞的墙/板一律拆成无重叠矩形
3. 组装**平铺命名**，不套母组 —— `sub.move_to(parent)` **静默失败**过
   （母组建出来了但里面是空的，板只剩第一块）

---

## 5. 验收：改完必须跑的验证

```bash
python verify_restart.py            # 重启后可用性（默认**不碰模型**）
python verify_parts.py              # 构件库（要加 --touching-model，会清空文档）
python verify_cad.py                # CAD 直读回归
python verify_flow.py               # 图片路线完整工作流
python verify_pipeline.py           # 全链路集成精度
python test_bridge_protocol.py      # 桥协议
python test_degradation.py          # 抗退化
python test_sweep.py                # 参数扫描
```

**跑之前先确认当前模型无关紧要**——`verify_parts.py` / `verify_flow.py` 会重建模型。
（`verify_restart.py` / `verify_cad.py` 默认跳过这些步骤。）

---

## 6. 必须记住的坑（每条都真踩过）

### 6.1 报错点 ≠ 出错点
`min`/`max` 带块在 SketchUp 的 Ruby 里被判成 `Array#min(n)`，
把**元素对**传进了块，于是 `w['thickness']` 里 `w` 是数组、静默取到 nil ——
**报错却出现在另一个函数**里。我一开始去改报错那个函数，方向完全错。
**修法**：用 `min_by`/`max_by`。

### 6.2 静默失败比报错危险
- `sub.move_to(parent)` 失败 → 母组是空的，**板只剩第一块**，没任何提示
- 洞口 `u` 基准变了 → 门整体漂移，没任何提示

**所以验证必须量几何**（面积、分段数、位置），不能只看"有没有报错"。

### 6.3 自洽 ≠ 正确
有一版顶板 5050×5050 而墙也是 5050 —— **模型内部完全自洽**（顶板严丝合缝盖住墙），
但建筑实际是 5000×5000。只有跟图纸标注对照才发现错。

### 6.4 单一测试图会掩盖缺陷
合成测试图内外墙厚度接近，于是"墙端延伸用自身半厚"这个 bug 一直藏着 ——
**它在两墙等厚时才是对的**。真实图纸（外墙 50 / 内墙 100）一次就暴露。

### 6.5 断言本身也要核对
我的测试曾断言"窗玻璃起点 = 900"，实际是 960（900 + 框厚 60）——
**库是对的，是我测错了**。
还有一次断言"螺旋踏面包围盒 > 1200"，而扇形跨 26°、半径 900 时弦长约 700
本来就是对的。**"测错了"比"做错了"更常见。**

### 6.6 判据只适用于一类构件时，容易忘记另一类
外墙的玻璃是**叠画在完整墙线上**的（所以不能用"墙线断开"判）；
内墙的门**恰恰表现为墙线断开**。
我用前者判了外墙、**却忘了去看内墙**，结果外墙 3 个洞口全对、**内墙 0 个门**。

### 6.7 想当然会把构件做长
我把"中庭"想成闭合方盒，把四壁都拉到建筑边缘；
图纸里只有西壁贯通，其余三面都短。**多做了 4400/1900/1950mm 的墙**，
把旋转楼梯围成了死角。
**修法**：把"实测覆盖区间 ↔ 模型区间"做成对照表，逐条比。

### 6.8 改代码的方式也会出错
- 用 PowerShell 内嵌长字符串改代码 → **引号转义失败**（多次）
- 用 `<<~` heredoc 构造替换文本 → **行首缩进被剥掉**，写进去的代码顶格
- 用 Ruby 跑 Python 语法 → 我在 `.rb` 里写了 `assert ... in ...`
- 用"从 A 切到 B"的下标区间删代码 → **边界里夹着小房间那段，一起删了**

**改完必须立刻看结果**（`read` 一下那几行），别假设替换成功了。

---

## 7. 环境事实

**这份文件要能跟着仓库走，所以不留本机专属路径** —— 下面用占位符，
实际值用 `python dsh_bridge/install.py --list` 和 `c.ping()` 随时问出来。

```
SketchUp    开发于 2026 (26.0.429)，自带 Ruby 3.2.2（2020+ 应当都能跑）
插件目录    %APPDATA%\SketchUp\SketchUp <版本>\SketchUp\Plugins   ← install.py 会自动找
工作区      <克隆下来的目录>          ← 桥按四步动态定位，不写死
桥          127.0.0.1:9877，token 在 dsh_workspace.json（**首次运行随机生成**）
            18 条命令
Python      3.9+；可用库：numpy / Pillow
            （**没有** ezdxf / cv2 / pymupdf —— DXF 解析是自己写的，所以不依赖它们）
```

**读 DWG**：这台机器的 `accoreconsole.exe`（DWG TrueView 自带）缺配置文件，
**转不了**。需要用户从 AutoCAD 里 `Ctrl+Shift+S` 另存为 **ASCII DXF**。

---

## 8. 这份指南是**强制**读的

新会话连上桥后，`ping` 会返回：

```json
"briefing": {
  "must_read": true,
  "name": "DSH-接手指南.md",
  "action": "briefing",
  "hint": "先执行 {\"action\":\"briefing\"} 读接手指南全文 …"
}
```

**在读过之前，`reload` 会被拒绝**（错误码 `briefing_required`）。

这不是提醒，是**硬门**。理由：一个不知道上面那些坑的新会话，
一上来就改代码并热重载，极可能把已经修好的问题重新引入
（比如又把门做成窗、又把 `min` 当 `min_by` 用、又忘了两个副本要同步）。

```python
from sk_client import SC
c = SC()
print(c.ping()['briefing'])   # 第一眼就看到 must_read
c.briefing()                  # 读全文，标记置位
c.reload()                    # 现在才允许改代码
```

三个设计细节，每个都是踩出来的：

| 细节 | 为什么 |
|---|---|
| 标记放**进程级全局变量** `$dsh_briefing_stamp` | 放 Handlers 的模块实例变量会被 `load` 清掉（`reload` 就是重新 load）；放 `DshBridge` 上也会被外层模块重建清掉 —— 那样会出现"读了 → reload → 又被拦"的死循环 |
| 指纹用**内容哈希**，不用 mtime | 插件目录与工作区两份指南内容相同但 mtime 不同；用 `mtime-size` 会让 reload 后指纹对不上，标记失效 |
| 指南改动后**自动要求重读** | 否则"读过一次"永久豁免，后来补进去的坑点就没人看了 |

机制都在 `dsh_handlers.rb` 里：`BRIEFING_PATHS` / `briefing_stamp` /
`briefing_read?` / `mark_briefing_read!` / `ACTIONS['briefing']`，
以及 `ACTIONS['reload']` 开头那道门。

**重启 SketchUp 后标记自然归零** —— 那正是"新会话必须重读"的时机。

---

## 9. 整理目录那次踩的坑（都记下来，别再犯）

这一版把散落的脚本重组进 `tools/*`、`tests/`、`archive/`，
过程中**引入的问题比解决的问题还多**，值得单独记一节。

### 9.1 移动文件必然破坏导入，而且**不报错**

`sys.path.insert(0, os.path.dirname(__file__))` 在文件与依赖同目录时是对的；
搬到 `tools/build/` 之后它指向自己，而 `sk_client.py` 在**根目录** →
`ImportError`。

更糟的是**反向的坑**：脚本搬走后调用处仍写 `fresh("dxf_import.py", ...)`，
python 找不到文件时**只打印 `can't open file` 并返回退出码 2，不产生 Traceback**，
而断言写的是"有没有崩溃" → **判成 ✅**。实测这条假通过藏了两项测试。

> **判据要能区分"脚本不存在"和"脚本运行出错"。**
> 现在 `fresh()` 会先解析脚本路径，并且断言里显式排除 `can't open file`。

### 9.2 用"补丁"修被补丁弄坏的文件，会一层套一层

我用正则给 5 个文件注入"路径修正"代码，连错四次：

| 次数 | 错法 | 后果 |
|---|---|---|
| 1 | `s.find('_dsh_bootstrap()')` 匹配到了 **def 那行** | 代码被插进函数体，def 被拆成两半 |
| 2 | 清理时留下**悬空的 docstring 残骸** | IndentationError |
| 3 | 再清理时留下**函数体残行**（`import os.path as _op` 悬空） | IndentationError |
| 4 | 去重脚本**把模块级 `import os` 一起删了** | NameError |

而且**修复脚本自己也写坏了两次**：我的 docstring 里含有三引号序列，
Python 提前结束字符串 → `SyntaxError: invalid character '（'`。

> **教训：反复打补丁会把文件变成看不懂的东西。**
> 最后是靠"按边界截断、重写整段"才干净。
> 而且**修复脚本也要先编译一次再跑**。

### 9.3 源码没有备份时，`.pyc` 能救回来

`import os` 被误删后我用 `dis` 反汇编 `__pycache__/*.pyc`，
把 `IMPORT_NAME` 操作数读出来，还原了原始导入清单。

**但 `.pyc` 只能给出模块名，给不出 `from PIL import ImageFilter` 这种组合。**
所以最终是靠"静态扫描 + 迭代按 NameError 补"（`ast` 提取已绑定名字与使用名字）。

### 9.4 双副本必然不同步

`dsh_handlers.rb` 在**工作区 `dsh_bridge/`** 和**插件目录**各有一份。
改了一份忘了另一份 → `reload` 把旧版加载回来，症状是"新功能消失了"。

**`install.py` 就是为了消灭这件事** —— 它只做单向复制，工作区是唯一真源。
改完代码跑一次 `python dsh_bridge/install.py` 即可。

### 9.5 行尾也会咬人

`edit` 工具写出的文件是 **CRLF**，而插件里其余是 LF。
测试里 `assertIn(b"end\n", raw)` 于是报"文件不完整"。

**是检查太脆，不是文件坏了** —— Ruby 解析 CRLF 毫无问题。
改成"最后一行是 `end`"（容忍行尾），同时把 `.rb` 统一成 LF。

