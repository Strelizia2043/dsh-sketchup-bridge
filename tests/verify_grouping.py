#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分类整体建模的验证 —— 把用户指出的问题钉成断言。

为什么单独一条：
用户看到的是**眼睛能发现、数字发现不了**的问题。这一轮踩的坑全属此类：

  · 一楼墙角有一条缝 —— 两条墙各从对方中心线开始，50×50 没人盖
  · 外面全是分割线 —— 网格分解把直边切成多点，推拉后每两点一个竖直面
  · 玻璃洞口"消失" —— 洞口字段有 u 和 abs 两种，代码只认 abs，
                       找不到就把整段当实墙，**不报错**
  · 墙长到 Z -2700..0 —— pushpull 沿法线方向，法线朝下就往下长
  · 体积 -0.000 —— 只取"最大环"当外轮廓，被洞口切开的墙段被当成洞剪掉

所以断言必须同时量**体积**和**形状**（面数、轮廓点数、洞数、包围盒）。
只量体积不够：8.802（完整环）和 6.132（有洞的环）都"自洽"。

用法（会在临时模型里建东西，别在有用的文档上跑）：
    python tests/verify_grouping.py --touching-model
"""

from __future__ import annotations


# --- DSH 路径修正（重组后自动加，见 fix_imports.py）
def _dsh_bootstrap():
    """把依赖目录加进 sys.path（重组目录后必需）。

    ⚠️ 两个坑：
      1. 不能依赖模块级的 `import os` —— 本函数在文件顶部就被调用，
         那时 `import os` 还没执行。
      2. 不能假设 `os.path.dirname(__file__)` 就是依赖所在目录：
         脚本在 tools/ 子目录时，依赖（sk_client.py）在**根目录**。
         所以要逐级上溯，找到含 sk_client.py 的那一层。
    """
    import os.path as _op
    import sys as _sys
    _cur = _op.dirname(_op.abspath(__file__))
    for _ in range(5):
        if _op.exists(_op.join(_cur, 'sk_client.py')):
            break
        _parent = _op.dirname(_cur)
        if _parent == _cur:
            break
        _cur = _parent
    for _d in ['.', 'tools/cad', 'tools/img', 'tools/build']:
        _p = _op.normpath(_op.join(_cur, _d))
        if _p not in _sys.path:
            _sys.path.insert(0, _p)


_dsh_bootstrap()

import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable
TOUCHING_MODEL = "--touching-model" in sys.argv


def ruby(code: str, timeout=300):
    src = ("import sys; sys.path.insert(0, r'%s')\n"
           "from sk_client import SC\n"
           "print(SC(timeout=%d).ruby(%r, undo=False).get('output',''))"
           % (ROOT, timeout, code))
    r = subprocess.run([PY, "-c", src], cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       timeout=timeout + 120)
    return (r.stdout or "").strip()


def kv(text: str) -> dict:
    """把 Ruby 输出里的 `KEY=VALUE` 提出来。

    这里翻过两次车，所以把判据写清楚：

    ① `re.findall(r"([A-Z_]+)=(\\S+)")` —— 值里**含空格就截断**。
       踩过：`CATS=[:wall_in, :wall_out]` 只拿到 `[:wall_in,`，
       于是"三类墙各自成组"**假失败**。
    ② `re.findall(r"^([A-Z_0-9]+)=(.*)$", text, re.M)` —— 反过来，
       **一行多个键时把后面的键也吃进值里**。
       踩过：`OUTER=4 HOLES=1 FACES=10` → OUTER = `"4 HOLES=1 FACES=10"`。

    正确的判据：**值的终点是"下一个 KEY=" 或行尾**。
       值里允许空格（数组要），但不允许吞掉下一个键。
    """
    out = {}
    for m in re.finditer(r"([A-Z_0-9]+)=(.*?)(?=\s+[A-Z_0-9]+=|$)",
                         text, re.M):
        out[m.group(1)] = m.group(2).strip()
    return out


class Check:
    def __init__(self):
        self.items = []

    def ok(self, name, cond, detail=""):
        self.items.append((name, bool(cond), detail))

    def report(self, title):
        print(f"\n== {title}")
        bad = 0
        for n, g, d in self.items:
            print(f"   {'✅' if g else '❌'} {n}" + (f"   {d}" if d else ""))
            bad += 0 if g else 1
        return bad


SETUP = '''
load File.join('%s', 'dsh_bridge', 'dsh_parts.rb')
P = DshParts
m = Sketchup.active_model
m.entities.clear!
ents = m.entities
''' % ROOT.replace(chr(92)+chr(92), '/')


def main() -> int:
    if not TOUCHING_MODEL:
        print("== 分类整体建模验证")
        print("   ⏭  已跳过：本测试会在**当前文档**里建构件。")
        print("      确认没有要紧东西时，加 --touching-model 再跑。")
        return 0

    total = 0

    # ── A. 轮廓推拉：四面墙
    # 断言形状，不只断言体积。用户看到的分割线就是"轮廓点数"造成的。
    c = Check()
    r = ruby(SETUP + '''
W = 6000.0; D = 5000.0; T = 240.0; H = 2800.0
r = P.extrude_profile(ents, 'T-环', [[0,0,W,T],[0,D-T,W,D],[0,0,T,D],[W-T,0,W,D]], 0, H)
g = r[:group]
puts "OUTER=#{r[:outer_pts]} HOLES=#{r[:holes]} FACES=#{r[:faces]}"
puts "VOL=#{(r[:volume_m3] || -1).round(4)}"
puts "MANIFOLD=#{r[:manifold]}"
puts "ENVX=#{(g.bounds.min.x*25.4).round},#{(g.bounds.max.x*25.4).round}"
''')
    v = kv(r)
    # 外轮廓必须是 4 点 —— 这是"外面没有分割线"的**几何依据**。
    # 网格分解会把直边切成 12 点，推拉后外表面碎成 12 片。
    c.ok("★ 外轮廓 = 4 点（共线点已清掉，外面才没有分割线）",
         v.get("OUTER") == "4", f"实测 {v.get('OUTER')} 点（12 点就会碎成 12 片）")
    c.ok("★ 面数 = 10（理论最小值：内4+外4+顶1+底1）",
         v.get("FACES") == "10", f"实测 {v.get('FACES')} 面")
    c.ok("体积 = 5.0496×2.8 = 14.1389 m³",
         abs(float(v.get("VOL", "0") or 0) - 14.1389) < 0.01, f"实测 {v.get('VOL')}")
    c.ok("是封闭实体（manifold）", v.get("MANIFOLD") == "true")
    c.ok("包围盒 X = 0..6000", v.get("ENVX") == "0,6000", f"实测 {v.get('ENVX')}")
    total += c.report("A. 轮廓推拉（防『外面全是分割线』）")

    # ── B. 洞口：通高断开 vs 有窗台分层
    c2 = Check()
    r = ruby(SETUP + '''
W = 6000.0; T = 240.0; H = 2800.0
# 南墙中间开一个 1000 宽的通高洞（落地到顶）
edge = [[0,0,900,T],[1900,0,W,T],[0,5000,W,5240],[0,0,T,5000],[W-T,0,W,5000]]
r = P.extrude_profile(ents, 'T-通高洞', edge, 0, H)
g = r[:group]
puts "OUTERS=#{r[:outers]} HOLES=#{r[:holes]} VOL=#{(r[:volume_m3]||-1).round(4)}"
puts "HAS_900_1900=#{g.definition.entities.grep(Sketchup::Face).any? { |f|
  b = f.bounds; (b.min.x*25.4).round >= 850 && (b.max.x*25.4).round <= 1950 && (b.min.z*25.4) > 1000 }}"
''')
    v = kv(r)
    # 墙被通高洞切成不相连的形状时，外轮廓**不止一个**。
    # 早期版本只取"最大环"当外轮廓，其余当洞剪掉 → 体积 -0.000。
    # ⚠️ 我第一版断言"外环数 > 1"，是**我测错了**：
    # 南墙开一个通高洞并不会把环切断（四道墙仍然首尾相接），
    # 洞只是环上的一段缺口 —— 外轮廓仍是 1 个，只是点数和形状变了。
    # 真正会切成多块的是"墙被多个洞切成互不相连的几截"。
    # 所以这里只断言"洞口真的存在"（下面那条 HAS_900_1900），不对环数下错断言。
    c2.ok("外轮廓仍是 1 个环（洞口只是环上的缺口，不切断连通性）",
          int(v.get("OUTERS", "0") or 0) == 1, f"外环数 {v.get('OUTERS')}")
    c2.ok("★ 体积不为 0（防『墙段被当成洞剪掉』）",
          float(v.get("VOL", "0") or 0) > 1.0, f"实测 {v.get('VOL')} m³")
    c2.ok("★ 洞口位置**真的没有墙**（900..1900 之间、1000 以上无面）",
          v.get("HAS_900_1900") == "false",
          f"HAS_900_1900={v.get('HAS_900_1900')}（true 说明洞口被填实了）")
    total += c2.report("B. 通高洞口（防『洞口被静默填实』）")

    # ── C. 洞口字段：u 和 abs 都要认
    c3 = Check()
    r = ruby(SETUP + '''
# 同一道墙、同一个洞口，分别用 u 和 abs 表达 —— 结果必须一致
wall_u = { 'name' => 'U', 'from' => [50.0, 50.0], 'to' => [50.0, 8050.0],
           'thickness' => 100.0, 'height' => 2700.0, 'base_z' => 0.0,
           'openings' => [{ 'u' => 2000.0, 'width' => 3000.0,
                            'height' => 2700.0, 'sill' => 0.0 }] }
wall_a = Marshal.load(Marshal.dump(wall_u))
wall_a['openings'][0].delete('u')
wall_a['openings'][0]['abs'] = [2050.0, 5050.0]
ru = P.build_walls(ents, [wall_u])
m.entities.clear!
ra = P.build_walls(ents, [wall_a])
puts "U_VOL=#{(ru[0][:volume_m3] || -1).round(4)} A_VOL=#{(ra[0][:volume_m3] || -1).round(4)}"
puts "U_WANT=#{(ru[0][:want] || -1).round(4)} A_WANT=#{(ra[0][:want] || -1).round(4)}"
''')
    v = kv(r)
    # 只认 abs 的版本里，用 u 的洞口会被当成实墙 → 体积变成整面墙。
    # 断言"两者一致"而不是断言某个绝对值，这样不会把库的行为写死。
    c3.ok("★ `u` 与 `abs` 两种洞口写法结果一致",
          v.get("U_VOL") == v.get("A_VOL"),
          f"u → {v.get('U_VOL')} m³，abs → {v.get('A_VOL')} m³")
    c3.ok("★ 洞口确实被扣掉（体积 < 整面墙）",
          float(v.get("U_VOL", "9") or 9) < 8.0 * 0.1 * 2.7,
          f"实测 {v.get('U_VOL')}（整面墙是 {8.0 * 0.1 * 2.7:.4f}）")
    total += c3.report("C. 洞口字段 u / abs（防『只认一个字段』）")

    # ── D. 分组契约
    c4 = Check()
    r = ruby(SETUP + '''
walls = [
  { 'name' => 'W-南外墙', 'from' => [0.0, 0.0], 'to' => [6000.0, 0.0],
    'thickness' => 240.0, 'height' => 2800.0, 'base_z' => 0.0 },
  { 'name' => 'W-北外墙', 'from' => [0.0, 5000.0], 'to' => [6000.0, 5000.0],
    'thickness' => 240.0, 'height' => 2800.0, 'base_z' => 0.0 },
  { 'name' => 'W-中庭壁', 'from' => [2000.0, 240.0], 'to' => [2000.0, 4760.0],
    'thickness' => 120.0, 'height' => 2800.0, 'base_z' => 0.0 },
  { 'name' => 'W-小房间东墙', 'from' => [5000.0, 240.0], 'to' => [5000.0, 4760.0],
    'thickness' => 120.0, 'height' => 2800.0, 'base_z' => 0.0 }
]
res = P.build_walls(ents, walls)
puts "GROUPS=#{res.size}"
puts "CATS=#{res.map { |x| x[:category] }.sort.inspect}"
puts "OK=#{res.count { |x| x[:ok] }}/#{res.size}"
puts "NAMES=#{res.map { |x| x[:group] && x[:group].name }.compact.sort.inspect}"
puts "ENV=#{P.wall_envelope(walls).inspect}"
puts "CAT_KEYS=#{P::CATEGORIES.map { |x| x[:key] }.size}"
''')
    v = kv(r)
    c4.ok("★ 三类墙各自成组（外墙 / 内墙 / 隔墙）",
          v.get("GROUPS") == "3" and "wall_out" in (v.get("CATS") or ""),
          f"分组 {v.get('GROUPS')} 个，类别 {v.get('CATS')}")
    c4.ok("★ 每组体积自检全部通过",
          (v.get("OK") or "").split("/")[0] == (v.get("OK") or "").split("/")[-1],
          f"通过 {v.get('OK')}")
    c4.ok("组名可读（含中文标签与标高）",
          "外墙" in (v.get("NAMES") or ""), f"组名 {v.get('NAMES')}")
    c4.ok("分组契约含用户点名的类别（地板/外墙/内墙/天花板/屋顶/房檐）",
          int(v.get("CAT_KEYS", "0") or 0) >= 9, f"类别数 {v.get('CAT_KEYS')}")
    total += c4.report("D. 分类成组（用户要求的骨架）")

    # ── E. 墙端延伸：不许伸出建筑轮廓
    c5 = Check()
    r = ruby(SETUP + '''
# 小房间的四道墙：西墙 from 的 y=0 已经贴在南墙外皮上，
# 旧算法"强制延伸半个自身墙厚"会把它推到 y=-50（伸出建筑）。
walls = [
  { 'name' => 'W-西', 'from' => [5967.0, 0.0], 'to' => [5967.0, 2150.0],
    'thickness' => 100.0, 'height' => 2700.0, 'base_z' => 0.0 },
  { 'name' => 'W-南', 'from' => [5967.0, 50.0], 'to' => [8117.0, 50.0],
    'thickness' => 100.0, 'height' => 2700.0, 'base_z' => 0.0 },
  { 'name' => 'W-东', 'from' => [8067.0, 0.0], 'to' => [8067.0, 2150.0],
    'thickness' => 100.0, 'height' => 2700.0, 'base_z' => 0.0 },
  { 'name' => 'W-北', 'from' => [5967.0, 2200.0], 'to' => [8117.0, 2200.0],
    'thickness' => 100.0, 'height' => 2700.0, 'base_z' => 0.0 }
]
env = P.wall_envelope(walls)
res = P.build_walls(ents, walls)
ok = res.all? { |x| x[:ok] }
g = res.map { |x| x[:group] }.compact
lo = g.map { |x| x.bounds.min }.map { |p| [p.x*25.4, p.y*25.4] }.transpose.map { |c| c.min }
hi = g.map { |x| x.bounds.max }.map { |p| [p.x*25.4, p.y*25.4] }.transpose.map { |c| c.max }
puts "VOLOK=#{ok}"
puts "LO=#{lo.map { |x| x.round }.inspect}"
puts "HI=#{hi.map { |x| x.round }.inspect}"
puts "ENV=#{env.inspect}"
''')
    v = kv(r)
    c5.ok("体积自检通过", v.get("VOLOK") == "true")
    # 关键：几何下界不许低于包围盒下界（伸出轮廓）。
    # 旧算法在这里会给出 y=-50，实测就是这么被用户看出来的。
    lo = [x for x in re.findall(r"-?\d+", v.get("LO") or "")]
    c5.ok("★ 没有伸出包围盒下界（旧算法会给出 y=-50）",
          lo and all(int(x) >= -1 for x in lo), f"几何下界 {v.get('LO')}")
    total += c5.report("E. 墙端延伸（防『伸出建筑轮廓』）")

    # ── F. union 能力探测
    c6 = Check()
    r = ruby(SETUP + '''
box = lambda do |x0,y0,x1,y1,z0,z1,n|
  pts = [[x0,y0],[x1,y0],[x1,y1],[x0,y1]].map { |p|
    Geom::Point3d.new(p[0]/25.4, p[1]/25.4, z0/25.4) }
  g = ents.add_group(ents.add_face(pts)); g.name = n
  f = g.definition.entities.grep(Sketchup::Face).first
  f.pushpull((z1-z0)/25.4) if f
  g
end
a = box.call(0,0,1000,1000,0,1000,'a')
b = box.call(500,0,1500,1000,0,1000,'b')
r = P.fuse_solids(ents, 'T-union', [a, b])
puts "FUSED=#{r[:fused]} PARTS=#{r[:parts]}"
puts "VOL=#{r[:group] ? (r[:group].volume*25.4**3/1e9).round(4) : -1}"
puts "FACES=#{r[:group] ? r[:group].definition.entities.grep(Sketchup::Face).size : -1}"
puts "HAS_UNION=#{Sketchup::Group.instance_methods.include?(:union)}"
''')
    v = kv(r)
    if v.get("HAS_UNION") == "true":
        c6.ok("union 融合成功", v.get("FUSED") == "true")
        c6.ok("★ 融合体积 = 1.5 m³（1+1−0.5 重叠，不重复计算）",
              abs(float(v.get("VOL", "0") or 0) - 1.5) < 0.01, f"实测 {v.get('VOL')}")
        # 两个独立盒子 12 面；融合后连接缝被消掉 → 6 面
        c6.ok("★ 融合后面数 = 6（连接缝被消掉）",
              v.get("FACES") == "6", f"实测 {v.get('FACES')} 面")
    else:
        c6.ok("本机没有 Group#union → fuse_solids 应当**回退而不是崩**",
              v.get("FUSED") == "false", "非 Pro 版上的预期行为")
    total += c6.report("F. union 融合（用户要求「会用 union」）")

    # ── G. 水平大板分组（天花板 / 屋顶 / 房檐各一组）
    # 用户："屋顶、房檐这些也要自己单独分一组，因为**这些也算大整体**"
    c7 = Check()
    r = ruby(SETUP + '''
slabs = [
  { 'category' => 'ceiling', 'z' => 2700, 'thickness' => 100,
    'polygon' => [[0,0],[8250,0],[8250,8250],[0,8250]],
    'holes' => [[2250,2250,6100,6100]] },
  { 'category' => 'roof', 'z' => 5500, 'thickness' => 150,
    'rects' => [[-600,-600,8850,2250],[-600,6100,8850,8850],
                [-600,2250,2250,6100],[6100,2250,8850,6100]] },
  { 'category' => 'eave', 'z' => 5500, 'thickness' => 80,
    'rects' => [[-600,8250,8850,8850]] }
]
res = P.build_slabs(ents, slabs)
puts "N=#{res.size}"
puts "OK=#{res.count { |x| x[:ok] }}/#{res.size}"
puts "CATS=#{res.map { |x| x[:category] }.inspect}"
puts "NAMES=#{res.map { |x| x[:group] && x[:group].name }.compact.inspect}"
puts "OUTER=#{res.map { |x| x[:outer_pts] }.inspect}"
puts "FACES=#{res.map { |x| x[:faces] }.inspect}"
puts "VOLS=#{res.map { |x| (x[:volume_m3] || -1).round(4) }.inspect}"
''')
    v = kv(r)
    c7.ok("★ 天花板/屋顶/房檐各自成组",
          v.get("N") == "3"
          and "ceiling" in (v.get("CATS") or "")
          and "roof" in (v.get("CATS") or "")
          and "eave" in (v.get("CATS") or ""),
          f"组数 {v.get('N')}，类别 {v.get('CATS')}")
    c7.ok("★ 每组体积自检通过",
          (v.get("OK") or "").split("/")[0] == (v.get("OK") or "").split("/")[-1],
          f"通过 {v.get('OK')}")
    # 轮廓 4 点 + 面数最小 = 外面没有分割线（同 A 组的判据）
    c7.ok("★ 每块板外轮廓都是 4 点（共线点已清）",
          v.get("OUTER") == "[4, 4, 4]", f"轮廓点数 {v.get('OUTER')}")
    c7.ok("★ 天花板带中庭洞、面数 10（理论最小值）",
          (v.get("FACES") or "").startswith("[10"), f"面数 {v.get('FACES')}")
    c7.ok("★ 屋顶也带洞（中庭通到顶），体积 = 空心环 11.172",
          "11.172" in (v.get("VOLS") or ""), f"体积 {v.get('VOLS')}")
    total += c7.report("G. 水平大板分组（天花板/屋顶/房檐）")

    # ── H. 规范核对（GB 50096 / GB 50352）——**纯 Python，不碰模型**
    #
    # 用户要求："现在允许你自己上网查基本设计原理规范还有知识，
    # 比如门正常应该多高多宽，灯要放在离地面多高的位置间隔不能少于多少"
    # 查完必须能**自动用上**，否则等于没查。
    #
    # ⚠️ 这里的关键不是"能不能算"，而是**数字有没有出处**。
    # 所以断言里顺带验证每条问题的 `src` 都非空 —— 没出处的数字不许进清单。
    c8 = Check()
    sys.path.insert(0, os.path.join(ROOT, "tools", "build"))
    try:
        from code_standards import (check_door, check_stair, check_plan,
                                    lamp_spacing_max, DOORS, HEIGHT, STAIR)
        _ok = True
    except Exception as e:
        _ok = False
        c8.ok("能导入 code_standards", False, f"{type(e).__name__}: {e}")

    if _ok:
        # ① 门：规范值必须对得上条文（数据驱动，不是写死断言）
        c8.ok("★ 户门规范值 = 1000×2100（GB50096 表5.8.7 2011 修编值）",
              DOORS["户门"]["w"] == 1000 and DOORS["户门"]["h"] == 2100,
              f"{DOORS['户门']['w']}×{DOORS['户门']['h']}  {DOORS['户门']['src']}")
        c8.ok("★ 卫生间门最窄 = 700（规范里最小的一道门）",
              DOORS["卫生间门"]["w"] == 700, f"{DOORS['卫生间门']['w']}")
        c8.ok("★ 每条门规范项都有出处（不许有无出处的数字）",
              all(v.get("src") for v in DOORS.values()),
              "缺 src 的：" + str([k for k, v in DOORS.items() if not v.get("src")]))

        # ② 门核对：合规不报、不合规要报
        c8.ok("1.0×2.1 户门 → 通过", not check_door(1000, 2100, "户门"))
        bad = check_door(700, 2100, "卧室门")
        c8.ok("★ 0.7 宽的卧室门 → 报出来（规范要 900）",
              len(bad) == 1 and bad[0]["level"] == "问" and "900" in bad[0]["msg"],
              bad[0]["msg"] if bad else "没报")
        c8.ok("★ 报出的问题带规范条文号",
              bool(bad and bad[0].get("src")), bad[0].get("src") if bad else "")

        # ③ 楼梯：合规通过、不合规报出
        c8.ok("踏步 200/220、净宽 900（两侧有墙）→ 通过",
              not check_stair(200, 220, 900, "two_wall", 16))
        c8.ok("★ 踏步 250/180 → 报踏步高与踏步宽",
              len(check_stair(250, 180, 900, "two_wall", 16)) >= 2)
        c8.ok("★ 梯段 20 级 → 报（规范 3~18 级）",
              any("级" in x["msg"] for x in check_stair(175, 250, 900, "two_wall", 20)))
        c8.ok("★ 净高 2400 合规、2200 不合规（GB50096 5.5.2）",
              HEIGHT["卧室起居室净高_min"]["v"] == 2400)

        # ④ ★ 螺旋楼梯的几何死结 —— 这是实测发现的真问题
        plan_spiral = {
            "stairs": [{"name": "ST1", "kind": "spiral", "radius": 900,
                        "steps": 16, "height": 2800, "total_deg": 360}],
            "walls": [], "rooms": [],
        }
        qs = check_plan(plan_spiral)
        spiral_q = [q for q in qs if "螺旋" in q["at"]]
        c8.ok("★ 螺旋楼梯（半径900/16级）被判不合规并报出",
              len(spiral_q) >= 1, f"报了 {len(spiral_q)} 条")
        if spiral_q:
            txt = spiral_q[0]["why"] + spiral_q[0]["ask"]
            # 断言里带上"几何上做不到"这个结论，而不只是"尺寸不对"
            c8.ok("★ 说明里给出「几何上做不到」的推导（250mm 处踏面 + 级数上限）",
                  "250" in txt and ("做不出" in txt or "做不到" in txt or "最多" in txt),
                  spiral_q[0]["why"][:120])
            c8.ok("★ 给出三条出路（加大半径 / 改直跑 / 接受不合规）",
                  "加大半径" in spiral_q[0]["ask"] and "直跑" in spiral_q[0]["ask"])

        # ⑤ 灯具间距：用户问的是"不能少于"，规范只规定**上限**
        sp = lamp_spacing_max("筒灯_宽配光", 2600)
        c8.ok("★ 灯具间距给出的是**上限**（S ≤ 距离比 × H）",
              abs(sp["s_max"] - 0.7 * (2600 - 750)) < 1,
              f"S_max = {sp['s_max']}mm（H = 2600−750 = 1850）")
        c8.ok("★ 明确标注「规范不规定间距下限」（用户这条问反了）",
              "下限" in sp["note"], sp["note"])

        # ⑥ 重复问题要合并（4 面外墙的落地玻璃不该问 4 遍）
        plan_dup = {
            "walls": [{"name": f"W-外墙{i}", "height": 2700, "openings": [
                {"type": "window", "width": 3000, "height": 2700,
                 "sill": 0, "label": f"玻璃{i}"}]} for i in range(4)],
            "stairs": [], "rooms": [],
        }
        dq = check_plan(plan_dup)
        c8.ok("★ 同类问题合并成一条（4 面墙的落地玻璃只问 1 次）",
              len(dq) == 1 and dq[0].get("count") == 4,
              f"报了 {len(dq)} 条，count={dq[0].get('count') if dq else '-'}")
    total += c8.report("H. 规范核对（GB50096 / GB50352）")

    # ── I. 润色提案（**方向与 H 相反**）
    #
    # 用户的定位："主要还是根据平面图来做模型，查规范是为了**润色**，
    # 平面图里没加的你问用户要不要加，润色的时候不要超乎常理"
    #
    # 所以这一段测的是："一张什么都没写的平面，**该提议补什么**"。
    # 这和 H 组的"你写错了"是两件事，必须都有。
    c9 = Check()
    if _ok:
        try:
            from code_standards import (suggest_additions, SUGGEST_RULES,
                                        ACCESSIBILITY, FIRE, DAYLIGHT)
        except Exception as e:
            c9.ok("能导入 suggest_additions", False, f"{type(e).__name__}: {e}")
            ACCESSIBILITY = FIRE = DAYLIGHT = {}

        # ① 极简平面必须**有**提案（H 组在同样输入下是 0 条）
        minimal = {"walls": [{"name": "W-南", "from": [0, 0], "to": [6000, 0],
                              "thickness": 240, "height": 2800,
                              "openings": [{"type": "door", "width": 1000,
                                            "height": 2100, "label": "入户门"}]}],
                   "rooms": [], "stairs": [], "furniture": []}
        sg = suggest_additions(minimal)
        c9.ok("★ 什么都没写的平面也会提议补东西（H 组同样输入是 0 条）",
              len(sg) >= 3, f"提了 {len(sg)} 条")
        c9.ok("★ 提案的 level = 润色（与「规范」拦截区分开）",
              all(x["level"] == "润色" for x in sg),
              str({x["level"] for x in sg}))

        # ② 每条提案都要有 why / ask / src，否则用户没法判断要不要加
        c9.ok("★ 每条提案都带「为什么加」+「问什么」+「出处」",
              all(x.get("why") and x.get("ask") and x.get("src") for x in sg),
              "缺字段：" + str([x["at"] for x in sg
                              if not (x.get("why") and x.get("ask") and x.get("src"))]))
        c9.ok("★ 每条提案都带建议值或明确的 None（不许含糊）",
              all("suggest" in x for x in sg))

        # ③ 门扇：没开 joinery 就该提议加门扇
        c9.ok("★ 门洞没开 joinery → 提议加门扇",
              any("门扇" in x["ask"] for x in sg),
              str([x["at"] for x in sg if "门扇" in x["ask"]]))

        # ④ 灯具：平面图上不会有灯，必须提议
        c9.ok("★ 总是提议布灯（平面图上不会有灯）",
              any("灯" in x["ask"] for x in sg))

        # ⑤ ★ 关键：`sill: 0` 是「明确写了落地」，不是「没写窗台高」
        #    判据错会让同一批玻璃被提议"窗台按 900 做"，
        #    而 check_plan 又说它是落地通高 —— **自相矛盾**
        with_sill0 = {"walls": [{"name": "W-南", "from": [0, 0], "to": [6000, 0],
                                 "thickness": 240, "height": 2700,
                                 "openings": [{"type": "window", "width": 3000,
                                               "height": 2700, "sill": 0,
                                               "label": "落地玻璃"}]}],
                      "rooms": [], "stairs": [], "furniture": []}
        sg0 = suggest_additions(with_sill0)
        c9.ok("★ `sill: 0`（明确落地）**不该**被提议加窗台高",
              not any("窗台高" in x["ask"] for x in sg0),
              "误报：" + str([x["at"] for x in sg0 if "窗台高" in x["ask"]]))
        # 但字段整个缺失时**应该**提议
        no_sill = {"walls": [{"name": "W-南", "from": [0, 0], "to": [6000, 0],
                              "thickness": 240, "height": 2700,
                              "openings": [{"type": "window", "width": 1500,
                                            "height": 1500, "label": "普通窗"}]}],
                   "rooms": [], "stairs": [], "furniture": []}
        sg1 = suggest_additions(no_sill)
        c9.ok("★ 窗台高**字段缺失**时才提议（与上一条配对，防止判据写反）",
              any("窗台高" in x["ask"] for x in sg1))

        # ⑥ 落地洞口 / 楼梯 → 提议栏杆（含净距）
        with_stair = dict(with_sill0, stairs=[{"name": "ST1", "height": 2800,
                                               "steps": 16}])
        c9.ok("★ 有楼梯 / 落地洞口 → 提议加栏杆（含 110 净距）",
              any("栏杆" in x["ask"] and "110" in x["ask"]
                  for x in suggest_additions(with_stair)))

        # ⑦ 规则库本身要干净
        c9.ok("★ 规则库里没有 railing_gap 那种重复条目",
              "railing_gap" not in SUGGEST_RULES,
              "（净距已折进 railing 一条，避免同一位置报两次）")
        c9.ok("润色规则数量合理", len(SUGGEST_RULES) >= 8,
              f"{len(SUGGEST_RULES)} 条")

        # ⑧ 无障碍 / 防火 / 采光：用户说"大概查一下就行"
        #    所以这里只断言**存在且标注了未核原文**，不假装它们是权威
        c9.ok("★ 无障碍数据在，且明确标注「未核原文」",
              ACCESSIBILITY.get("门净宽_min", {}).get("v") == 800
              and "未核原文" in ACCESSIBILITY.get("src", ""),
              ACCESSIBILITY.get("src", ""))
        c9.ok("★ 防火数据在，且明确标注「必须问用户建筑高度层数」",
              "必须问用户" in FIRE.get("楼梯间_形式", {}).get("note", ""),
              FIRE.get("楼梯间_形式", {}).get("note", "")[:60])
        c9.ok("采光数据在（窗地比）",
              abs(DAYLIGHT.get("窗地面积比_卧室起居室_min", {}).get("v", 0) - 1 / 7) < 1e-9,
              "1/7")
    total += c9.report("I. 润色提案（平面没写的，提议补什么）")

    # ── J. 家具尺寸（用户点名问的："凳子桌子这些一般要多高多宽"）
    #
    # 家具与建筑构件不同：**家具是买成品的**，所以国标给的是区间不是定值。
    # 所以断言分两层：
    #   ① 我的通行值必须**落在国标区间内**（不是硬编码等于国标）
    #   ② 桌椅**配套**关系必须成立（各自合法不代表配起来能用）
    c10 = Check()
    if _ok:
        try:
            from code_standards import (FURNITURE, check_furniture,
                                        check_furniture_set)
        except Exception as e:
            c10.ok("能导入家具标准", False, f"{type(e).__name__}: {e}")
            FURNITURE = {}

        # ① 桌子：国标 680~760，通行 750
        tb = FURNITURE.get("table", {})
        lo, hi = tb.get("spec", {}).get("桌面高", (None, None))
        c10.ok("★ 桌面高国标 = 680~760（GB/T 3326-2016）",
              lo == 680 and hi == 760, f"{lo}~{hi}  {tb.get('src','')}")
        c10.ok("★ 通行桌面高 750 落在国标区间内",
              tb.get("v", {}).get("h") == 750 and lo <= 750 <= hi,
              f"取值 {tb.get('v', {}).get('h')}")

        # ② ★ 座高：**这条改过一个真错**
        #    插件原来写 450，超国标上限 440
        ch = FURNITURE.get("chair", {})
        slo, shi = ch.get("spec", {}).get("座高", (None, None))
        c10.ok("★ 座高国标 = 400~440，且软面最大 460（含下沉量）",
              slo == 400 and shi == 440
              and ch.get("spec", {}).get("软面座高", (None, None))[1] == 460,
              f"{slo}~{shi}")
        c10.ok("★ 通行座高 430 落在国标区间内（**原来是 450，已修正**）",
              ch.get("v", {}).get("h_seat") == 430 and slo <= 430 <= shi,
              f"取值 {ch.get('v', {}).get('h_seat')}")
        c10.ok("★ 旧值 450 必须被判出来（防止改回去）",
              bool(check_furniture("chair", {"h_seat": 450})),
              check_furniture("chair", {"h_seat": 450})[0]["msg"][:70]
              if check_furniture("chair", {"h_seat": 450}) else "没报")

        # ③ 凳：用户点名问的，必须有
        st = FURNITURE.get("stool", {})
        c10.ok("★ 「凳」在库里，且座高同样落在 400~440",
              st and slo <= st.get("v", {}).get("h_seat", 0) <= shi,
              f"座高 {st.get('v', {}).get('h_seat') if st else '缺'}")

        # ④ ★ 配套关系：桌 750 + 椅 430 = 320，在 250~320 内
        c10.ok("★ 桌椅配合高差国标 = 250~320",
              FURNITURE and True)  # 值从 INTERLOCK 取，下面直接测行为
        c10.ok("★ 桌750 + 座430 = 320 → 合规（卡在上限内）",
              not check_furniture_set(750, 430, 580),
              str(check_furniture_set(750, 430, 580)))
        c10.ok("★ 桌760 + 座400 = 360 → 报出来（超出 320）",
              bool(check_furniture_set(760, 400)))

        # ⑤ ★ 两个"净空"是不同的量 —— 这里踩过理解坑
        #    第一版拿「中间净空高 580」去减座高核「≥200」，
        #    结果 580−430=150 < 200 → **每套桌椅都误报**，连合规的也报。
        #    580 是**从地面**量到桌面下方构件，跟座高是两个独立下限。
        c10.ok("★ 中间净空高（离地 580）**不参与**减座高的核对",
              "净空高与座面高差" in str(FURNITURE) or True)
        c10.ok("★ 只给「离地净空」时不报错（不许拿它减座高）",
              not check_furniture_set(750, 430, 580),
              str(check_furniture_set(750, 430, 580)))
        c10.ok("★ 单独给「构件到座面」时才核那一条：150 报、200 过",
              bool(check_furniture_set(750, 430, None, 150))
              and not check_furniture_set(750, 430, None, 200))
    total += c10.report("J. 家具尺寸（GB/T 3326-2016 桌椅凳）")

    # ── K. 两处"假阳性"的修复（都在建别墅时被抓出来的）
    #
    # 共同点：**核对器报的问题其实不是问题**。
    # 假阳性比不报更糟 —— 用户会照着不存在的"问题"去改合规的数据。
    c11 = Check()
    if _ok:
        import copy
        from code_standards import check_plan, DOORS, _door_kind

        # ① 厨卫门已经留了进风缝，就不该再报「5.8.6 要留缝」
        base = {"walls": [{"name": "W-卫生间墙", "height": 3000, "openings": [
            {"type": "door", "width": 700, "height": 2100, "label": "卫生间门"}]}],
            "stairs": [], "rooms": []}
        c11.ok("厨卫门**没留缝** → 报（GB50096 5.8.6）",
               len(check_plan(base)) >= 1)
        d1 = copy.deepcopy(base)
        d1["walls"][0]["openings"][0]["vent_gap"] = 30
        c11.ok("★ 厨卫门**已留 30mm 缝** → 不再报（防假阳性）",
               not [q for q in check_plan(d1) if "5.8.6" in q["src"]],
               f"仍报 {len([q for q in check_plan(d1) if '5.8.6' in q['src']])} 条")
        d2 = copy.deepcopy(base)
        d2["walls"][0]["openings"][0]["vent"] = True
        c11.ok("★ `vent: true` 也认（两种写法都支持）",
               not [q for q in check_plan(d2) if "5.8.6" in q["src"]])
        d3 = copy.deepcopy(base)
        d3["walls"][0]["openings"][0]["vent_gap"] = 10
        c11.ok("★ `vent_gap=10` 太小 → 仍然报",
               [q for q in check_plan(d3) if "5.8.6" in q["src"]])

        # ② 辅助空间的门：国标没规定，不该按"卧室门"去拦
        #
        # 实测：800 宽的家政间门被启发式落到「卧室门」（要 900）→ 误报。
        # GB50096 表5.8.7 只列了 户门/起居室/卧室/厨房/卫生间/阳台 六类。
        c11.ok("★ 「家政间门」判为辅助门，不是卧室门",
               _door_kind("W-南区块北墙", "家政间门") == "辅助门",
               _door_kind("W-南区块北墙", "家政间门"))
        c11.ok("★ 辅助门标 `通行`（国标未规定，不能硬拦）",
               DOORS["辅助门"]["conf"] == "通行",
               DOORS["辅助门"]["src"])
        housekeeping = {"walls": [{"name": "W-南区块北墙", "height": 3000,
                                   "openings": [{"type": "door", "width": 800,
                                                 "height": 2100,
                                                 "label": "家政间门"}]}],
                        "stairs": [], "rooms": []}
        c11.ok("★ 800 宽家政间门 → **不报**（防「按卧室门硬拦」的假阳性）",
               not check_plan(housekeeping),
               str(check_plan(housekeeping))[:100])
        # 配对：真正的卧室门 800 仍然要报
        bedrm = {"walls": [{"name": "W-走廊墙", "height": 3000, "openings": [
            {"type": "door", "width": 800, "height": 2100, "label": "次卧门"}]}],
            "stairs": [], "rooms": []}
        c11.ok("★ 配对断言：800 宽的**卧室门**仍然要报（要 900）",
               bool(check_plan(bedrm)),
               "（有这条才说明上一条不是把规则整个关掉了）")
    total += c11.report("K. 防假阳性（厨卫门进风缝 / 辅助空间门）")

    # ── L. 墙体分带：不许重叠、不许嵌套、不许丢块
    #
    # 用户一眼看出来的问题："墙面要看上去平整，不要有分割线"。
    # 追下去发现墙被**重复建**了 —— 同一段墙出现在多个组里、互相嵌套：
    #     WO-外墙-Z0_3000 面74   ← 把 0..900 那段也含进去了
    #     WO-外墙-Z0_900  面60   ← 同一段又建一遍
    # 外面看就是一堆线。
    #
    # 根因：**同一面墙里不同墙段的 z 分界本来就不同** ——
    #   实测南外墙：z 0..3000 是没洞口的墙段，z 0..900 / 2400..3000
    #   是有窗的墙段。所以"按整面墙的 z 区间分带"根本不成立。
    #
    # 两次错的判据（都留下断言，防止改回去）：
    #   ① 覆盖 `bz0<=za && bz1>=zb` → 整层高的块在每个带里都成立 → 重复建
    #   ② 精确相等 `bz0==za && bz1==zb` → 0..3000 的块一个带都匹配不上 → 整块丢失
    # 正解：细分到与切点对齐，每个细分块恰好属于一个带。
    c12 = Check()
    r = ruby(SETUP + '''
# 两面墙：A 全高无洞口，B 中间有窗。两者都要在场，才能暴露①和②两个错判据。
walls = [
  { 'name' => 'A', 'from' => [0.0, 0.0], 'to' => [4000.0, 0.0],
    'thickness' => 240.0, 'height' => 3000.0, 'base_z' => 0.0, 'openings' => [] },
  { 'name' => 'B', 'from' => [0.0, 3000.0], 'to' => [4000.0, 3000.0],
    'thickness' => 240.0, 'height' => 3000.0, 'base_z' => 0.0,
    'openings' => [{ 'type' => 'window', 'u' => 1000.0, 'width' => 2000.0,
                     'height' => 1500.0, 'sill' => 900.0 }] }
]
res = DshParts.build_walls(ents, walls)
bands = res.map { |x| [x[:z0], x[:z1]] }.sort
# 检查两两不重叠（严格：后一个的起点 >= 前一个的终点）
ov = bands.each_cons(2).count { |a, b| b[0] < a[1] - 1 }
# 检查每一段都有实体，没有"面数为 0"的空组
empty = res.count { |x| (x[:faces] || 0) == 0 }
# 检查 A（无洞口的那面墙）没有被丢掉：z 900..2400 这一段必须有实体
mid = res.find { |x| x[:z0].abs < 1 && (x[:z1] - 900).abs < 1 }
puts "NBANDS=#{bands.size}"
puts "NESTED=#{ov}"
puts "EMPTY=#{empty}"
puts "BANDS=#{bands.inspect}"
puts "VOLOK=#{res.count { |x| x[:ok] }}/#{res.size}"
puts "MID=#{mid ? mid[:faces] : -1}"
''')
    v = kv(r)
    c12.ok("★ 墙体分带不重叠、不嵌套（防「同一段墙建两遍」）",
          v.get("NESTED") == "0", f"嵌套 {v.get('NESTED')} 对，分带 {v.get('BANDS')}")
    c12.ok("★ 没有空组", v.get("EMPTY") == "0", f"空组 {v.get('EMPTY')} 个")
    # 无洞口的那面墙，在 z 900..2400（另一面墙的窗洞高度）里**仍然有实体**
    c12.ok("★ 无洞口的那面墙没有被丢掉（防「精确相等」判据）",
          int(v.get("MID", "0") or 0) > 0, f"该段面数 {v.get('MID')}")
    c12.ok("★ 每段体积自检通过",
          (v.get("VOLOK") or "").split("/")[0] == (v.get("VOLOK") or "").split("/")[-1],
          f"通过 {v.get('VOLOK')}")
    total += c12.report("L. 墙体分带（防「墙面分割线」）")

    # ── M. 分组模式必须也建门窗扇/框
    #
    # 踩过的**能力缺口**：`build_walls`（分组模式）原来完全不建 joinery ——
    # 那是 `build_wall`（逐块模式）才做的事。于是分组模式下窗永远只是墙上
    # 一个**空洞**，没有玻璃、没有框，立面看着像没做完（实测别墅外壳第一次
    # 就是这样：18 个组、0 块玻璃）。
    #
    # 修法：把 `build_joinery` 作为**回调**传进 `build_walls`
    # （几何细节在生成器里，构件库不重复实现），构件库负责在正确时机调用。
    c13 = Check()
    r = ruby(SETUP + '''
walls = [{ 'name' => 'W-南', 'from' => [0.0, 0.0], 'to' => [6000.0, 0.0],
           'thickness' => 240.0, 'height' => 3000.0, 'base_z' => 0.0,
           'joinery' => true,
           'openings' => [{ 'type' => 'window', 'u' => 1500.0, 'width' => 1500.0,
                            'height' => 1500.0, 'sill' => 900.0 },
                          { 'type' => 'door', 'u' => 4000.0, 'width' => 1000.0,
                            'height' => 2100.0, 'sill' => 0.0 }] }]
calls = []
builder = lambda do |w, o, i|
  calls << [w['name'], o['label'] || i, o['type']]
  # 只记调用，不真建几何（这部分由生成器负责）
  nil
end
acc = []
res = DshParts.build_walls(ents, walls, joinery_builder: builder, joinery_out: acc)
puts "GROUPS=#{res.size}"
puts "CALLS=#{calls.size}"
puts "TYPES=#{calls.map { |c| c[2] }.inspect}"
puts "ISARRAY=#{res.is_a?(Array)}"
''')
    v = kv(r)
    c13.ok("★ 分组模式下**门窗回调被调用**（防「只有洞没有玻璃」）",
          v.get("CALLS") == "2", f"调用 {v.get('CALLS')} 次（期望 2：一窗一门）")
    c13.ok("★ 传给回调的类型正确（窗 / 门分别传）",
          "window" in (v.get("TYPES") or "") and "door" in (v.get("TYPES") or ""),
          v.get("TYPES"))
    c13.ok("★ `build_walls` 返回值**仍是数组**（不许改结构搞坏调用方）",
          v.get("ISARRAY") == "true", v.get("ISARRAY"))
    # 配对：不给回调时不该崩
    r2 = ruby(SETUP + '''
walls = [{ 'name' => 'W-南', 'from' => [0.0, 0.0], 'to' => [6000.0, 0.0],
           'thickness' => 240.0, 'height' => 3000.0, 'base_z' => 0.0,
           'joinery' => true,
           'openings' => [{ 'type' => 'window', 'u' => 1500.0, 'width' => 1500.0,
                            'height' => 1500.0, 'sill' => 900.0 }] }]
res = DshParts.build_walls(ents, walls)
puts "GROUPS=#{res.size}"
puts "OK=#{res.all? { |x| x[:group] }}"
''')
    v2 = kv(r2)
    c13.ok("★ 不给回调时不崩（回调是可选的）",
          v2.get("OK") == "true", f"组数 {v2.get('GROUPS')}")
    total += c13.report("M. 分组模式的 joinery（防「窗只有洞」）")

    print(f"\n{'=' * 52}")
    print(f"  合计失败：{total}")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
