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

    print(f"\n{'=' * 52}")
    print(f"  合计失败：{total}")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
