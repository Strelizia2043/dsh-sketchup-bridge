# DSH ⇄ SketchUp Bridge

让 AI 编码助手（[DSH](https://github.com/) 或任何能跑 Python 的 agent）
**直接操作 SketchUp 建模** —— 而且**从图纸开始**：

```
平面图（DXF / 图片）──读图──▶ 建筑描述 JSON ──建模──▶ SketchUp 模型
                                    ▲
                              疑问清单：不确定的先问你，不猜
```

不是"生成一段 Ruby 让你复制粘贴"，而是**真的在你正开着的 SketchUp 里建几何**，
每一步都能截图回看、量尺寸核对。

---

## 这东西能做什么

| 能力 | 说明 |
|---|---|
| **读 CAD 图纸** | DXF → 精确模型。**实测精度到 0**（实体坐标直读，不需要标定） |
| **读图片图纸** | 照片/截图 → 模型。实测 建筑尺寸 ±48mm、洞口位置 ±27mm |
| **按颜色语义理解图纸** | 图层/颜色自动分类：墙、门、窗、家具、标注 |
| **楼板挖洞、多楼层** | 中庭挑空、楼梯井，拆矩形实现（不用布尔运算） |
| **通用构件库** | 墙（门只留洞 / 窗带玻璃框）、螺旋楼梯、楼板、材质 |
| **几何自检** | 逐构件核对世界坐标，出问题报告异常项而不是刷屏 |
| **出图核对** | 任意机位截图，正投影/透视都行 |

## 它**不**做什么（重要的边界）

- **只读平面图**：**立面图 / 剖面图不读**（没有图像识别入口）。
  层高、门窗高度、屋顶形式这些“立面信息”**靠问你**。
- **不替你猜**：图纸里读不准的（墙厚、洞口类型、屋顶形式、层高）会**列成疑问清单问你**，
  而不是编一个数字。这是设计原则，不是缺陷。
- **图片路线有硬边界**：不能斜拍（2% 透视就偏 132mm，七种修正全部失败）；
  墙厚量图误差 5~10%，**必须**由你给或读标注。
- **没有 CV/CAD 库依赖**：只用 `numpy` + `Pillow`，DXF 解析是自己写的
  （不依赖 `ezdxf`）。好处是装上就能跑，代价是只支持正交外墙、矩形洞口。

---

## 安装

**要求**：SketchUp 2020+（开发于 2026）、Python 3.9+（`numpy`、`Pillow`）。

```bash
# 1. 克隆
git clone https://github.com/<你的用户名>/dsh-sketchup-bridge.git
cd dsh-sketchup-bridge

# 2. 一键安装（会自己找 SketchUp 的 Plugins 目录）
python dsh_bridge/install.py

# 3. 启动（或重启）SketchUp —— 插件在启动时加载

# 4. 自检
python tests/verify_restart.py
```

`install.py` 做四件事：找 Plugins 目录 → 复制 4 个 `.rb` + 指南 →
**按实际位置写定位文件** → 自检。

```bash
python dsh_bridge/install.py --list       # 只列出找到的 Plugins 目录
python dsh_bridge/install.py --dry-run    # 只说要做什么
python dsh_bridge/install.py --uninstall  # 卸载
```

装好后 SketchUp 里会多一个 **DSH Bridge** 工具栏。

### 手动安装（不想跑脚本）

把 `dsh_bridge/` 下的这些复制到你的 Plugins 目录：

```
Windows  %APPDATA%\SketchUp\SketchUp <版本>\SketchUp\Plugins
macOS    ~/Library/Application Support/SketchUp <版本>/SketchUp/Plugins
```

需要的是 `dsh_bridge.rb`、`dsh_handlers.rb`、`dsh_loader.rb`、`dsh_parts.rb`。
`dsh_workspace.json` 首次启动会自动生成（含随机 token）。

---

## 快速上手

```python
import sys; sys.path.insert(0, "<工作区路径>")
from sk_client import SC

c = SC()
print(c.ping())          # 桥活着吗、有哪些命令

# 直接执行 Ruby
c.ruby('Sketchup.active_model.entities.add_group', undo=True)

# 截图回看
c.shot("看看", width=1280, height=800)

# 读一张 DXF
#   python tools/cad/dxf_import.py 图纸.dxf
#   python tools/cad/cad_to_plan.py 配置.json --out plan.json
#   python tools/build/build_from_json.py plan.json            # 只看疑问清单
#   python tools/build/build_from_json.py plan.json --confirm  # 确认后建模
```

完整流程见 **[HOWTO-CAD直读建模.md](HOWTO-CAD直读建模.md)**（CAD 路线）
和 **[HOWTO-读图建模.md](HOWTO-读图建模.md)**（图片路线）。

---

## 安全设计

| 项 | 做法 |
|---|---|
| **监听地址** | 只绑 `127.0.0.1`，不对外网开放 |
| **鉴权** | 每次请求必须带 token。**首次运行随机生成**，每个安装不同 |
| **token 存放** | `dsh_workspace.json`，**已在 `.gitignore` 里**，不会提交 |
| **写盘范围** | 默认只允许工作区内；写到外面要显式 `allow_outside: true` |
| **清空模型** | `erase(all=True)` 必须带 `confirm: true` |
| **模型构建** | `build_from_json.py` 默认**不建模**（要 `--confirm`）；<br>当前文档非空时**拒绝清空**（要 `--discard`） |

> ⚠️ **token 就是钥匙。** 不要把它提交到版本库，也不要贴到公开的地方。
> 如果泄露了，删掉 `dsh_workspace.json` 里的 `token` 字段再重启 SketchUp 即可换新。

### 权限范围

桥能以你的身份执行**任意 Ruby**（`bpy` 的等价物是 SketchUp 的 Ruby API）。
也就是说，能连上桥的程序 = 能以你的权限操作你的电脑。

**这是设计使然，不是漏洞** —— 它就是个远程执行接口。
请只让你信任的 agent 连它，不要把这个端口暴露到局域网/公网。

---

## 仓库结构

```
dsh_bridge/          ← 装到另一台机器只需要这个目录
  dsh_bridge.rb        socket 服务（改它要重启 SketchUp）
  dsh_handlers.rb      18 条命令（可热重载）
  dsh_loader.rb        工具栏 / 面板
  dsh_parts.rb         通用构件库（墙 / 楼板 / 螺旋楼梯 / 材质）
  install.py           一键安装
  DSH-接手指南.md        **接手先读这份**：架构、坑、约定
sk_client.py         Python 客户端
dsh_paths.py         工具定位器
tools/cad/           DXF 解析、按颜色语义分类、生成 plan
tools/img/           进件评估、图片读图
tools/build/         建模驱动、几何校验、出图
tests/               回归测试（可直接跑，不需要 SketchUp 的也能跑）
archive/             开发期的一次性脚本（保留作参考，不参与运行）
```

---

## 运行测试

```bash
python tests/test_bridge_protocol.py    # 21 项，**不需要 SketchUp**
python tests/verify_restart.py          # 14 项，重启后可用性
python tests/verify_cad.py              # 16 项，CAD 直读回归
python tests/verify_flow.py             # 70 项，图片路线完整工作流
python tests/verify_pipeline.py         # 11 项，全链路精度
python tests/test_degradation.py        # 退化测试台
python tests/verify_parts.py --touching-model   # 构件库（会清空当前文档）
```

> ⚠️ `verify_parts.py` 和 `verify_flow.py` **会重建当前文档**。
> 跑之前确认 SketchUp 里没有要紧的东西。

> 📄 **有些用例需要示例图纸。** 真实图纸不进仓库（`.gitignore` 排除了 `cad/`），
> 所以 `verify_cad.py` 和 `verify_restart.py` 里依赖 DXF 的用例会**跳过并说明原因**，
> 不会报失败。想完整跑，自己放一张 ASCII DXF 到 `cad/` 下即可。

---

## 已知边界

- 图片路线：不能斜拍；墙厚不可量；只认正交外墙和矩形洞口
- `test_sweep.py` 有 4 个退化方案未通过（根因已记录，见 `抗退化实测.md`）
- 只支持 ASCII DXF。DWG 需要先用 AutoCAD 另存为 DXF
  （`accoreconsole` 在部分机器上缺配置，转不了）
- 弧墙、斜墙、弧形洞口未实现

---

## 文档

| 文件 | 内容 |
|---|---|
| **[DSH-接手指南.md](DSH-接手指南.md)** | **接手先读**：架构、两条技术路线、标准工作流、9 类踩过的坑 |
| [HOWTO-CAD直读建模.md](HOWTO-CAD直读建模.md) | DXF → 模型的完整流程 |
| [HOWTO-读图建模.md](HOWTO-读图建模.md) | 图片 → 模型的完整流程 |
| [plan_schema.md](plan_schema.md) | 建筑描述 JSON 的字段定义 |
| [reading_checklist.md](reading_checklist.md) | 读图前该确认什么 |
| [抗退化实测.md](抗退化实测.md) | 各种退化条件下读图精度实测数据 |

---

## 协议

MIT，见 [LICENSE](LICENSE)。

**不附带任何担保。** 它会以你的权限执行任意代码，请自行判断风险。
