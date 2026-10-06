#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构件库（dsh_parts.rb）的验证 —— 把这一轮踩过的坑钉成断言。

为什么单独一条：
这一轮给 designproject2 建模时踩的坑，几乎全是"**构件做错了但没报错**"：
  · 门被做成了窗（用了同一个函数，门也套了玻璃和窗框）
  · 楼板挖洞 `move_to(parent)` **静默失败**，母组是空的，板只剩第一块
  · 螺旋楼梯每级只占 22.5°，踏面 118mm 宽，顶视是**薄片堆叠**而不是楼梯
  · 内墙做长了几米（把"中庭是闭合方盒"想当然），楼梯被围成死角
  · 洞口 u 随墙端漂移 25~284mm

所以断言必须**量几何**（面积、分段、是否有玻璃），不能只看"有没有报错"。
"""

from __future__ import annotations

# --- DSH 路径修正（重组后自动加，见 fix_imports.py）
def _dsh_bootstrap():
    """把依赖目录加进 sys.path（重组目录后必需）。

    ⚠️ 两个坑：
      1. 不能依赖模块级的 `import os` —— 本函数在文件顶部就被调用，
         那时 `import os` 还没执行（第一版栽在这：NameError: name 'os' is not defined）。
         所以在**函数体内** import。
      2. 不能假设 `os.path.dirname(__file__)` 就是依赖所在目录：
         脚本移到 tools/ 子目录后，依赖（sk_client.py / version.json）在**根目录**。
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
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
TOUCHING_MODEL = "--touching-model" in sys.argv


def ruby(code: str, timeout=300):
    src = ("import sys; sys.path.insert(0, r'%s')\n"
           "from sk_client import SC\n"
           "print(SC(timeout=%d).ruby(%r, undo=False).get('output',''))"
           % (HERE, timeout, code))
    r = subprocess.run([PY, "-c", src], cwd=HERE, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=timeout + 120)
    return (r.stdout or "").strip()


import re


def kv(text: str) -> dict:
    """把 Ruby 输出里所有 `KEY=VALUE` 提出来。

    ⚠️ 不能用 `split("=", 1)` —— 一行常写成 `SEG=3 GLASS=1 FRAME=2`，
    那样第一个键会拿到 "3 GLASS=1 FRAME=2"（踩过，报 ValueError）。
    """
    return {k: v for k, v in re.findall(r"([A-Z_]+)=(\S+)", text)}


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


def main() -> int:
    if not TOUCHING_MODEL:
        print("== 构件库验证")
        print("   ⏭  已跳过：本测试会在**临时模型**里建构件，"
              "而当前入口只能作用于当前文档。")
        print("      确认当前文档没有要紧东西时，加 --touching-model 再跑。")
        return 0

    total = 0
    c = Check()

    # 在一个干净文档里做三组实验
    setup = '''
load 'E:/deepseek工作区/sketchup-bridge/dsh_parts.rb'
P = DshParts
m = Sketchup.active_model
m.entities.clear!
ents = m.entities
'''
    # ── A. 墙：门只留洞、窗有玻璃
    r = ruby(setup + '''
res = P.wall(ents, 'T-墙', 'h', 1000.0, 100.0, [0.0, 8000.0], 0.0, 2700.0,
             [{a: 500.0,  b: 1400.0, kind: 'door'},
              {a: 3000.0, b: 4500.0, kind: 'window', sill: 900.0, height: 1500.0}],
             door_h: 2100.0)
gs = ents.grep(Sketchup::Group)
door_zone = gs.select { |g| b=g.bounds; b.min.x*25.4 >= 400 && b.max.x*25.4 <= 1500 && b.min.z*25.4 < 2000 }
win_glass = gs.select { |g| g.name.to_s.include?('玻璃') }
puts "SEG=#{res[:solids]} GLASS=#{res[:glass]} FRAME=#{res[:frames]}"
puts "DOORZONE_SOLID=#{door_zone.count { |g| (g.bounds.max.z*25.4) <= 2200 }}"
puts "DOORZONE_GLASS=#{door_zone.count { |g| g.name.to_s.include?('玻璃') }}"
puts "GLASS_Z=#{win_glass.map { |g| (g.bounds.min.z*25.4).round }.inspect}"
''')
    vals = kv(r)
    c.ok("墙：门洞处**没有玻璃**", vals.get("DOORZONE_GLASS") == "0",
         f"门区玻璃数 = {vals.get('DOORZONE_GLASS')}（应为 0，门不该变窗）")
    c.ok("墙：窗有玻璃", vals.get("GLASS") == "1", f"玻璃数 {vals.get('GLASS')}")
    # 玻璃起点 = 窗台高(900) + 框厚(60) = 960。
    # 我第一版断言写成 900，**是我测错了**——库的行为是对的。
    c.ok("墙：窗玻璃起点 = 窗台高 + 框厚（900+60=960）",
         (vals.get("GLASS_Z") or "").find("960") >= 0,
         f"玻璃 Z 起点 {vals.get('GLASS_Z')}（窗台 900 + 框 60）")
    c.ok("墙：有门楣（门洞上方补墙）", int(vals.get("SEG", "0") or 0) >= 3,
         f"实墙段数 {vals.get('SEG')}")
    total += c.report("A. 墙开门窗（防『门变成窗』）")

    # ── B. 楼板挖洞：量总面积
    c2 = Check()
    r = ruby(setup + '''
gs = P.slab_with_holes(ents, 'T-板', 0, 0, 10000, 10000, 0, 100,
                       [[3500, 3500, 6500, 6500]])
tot = gs.sum { |g| (g.bounds.width*25.4) * (g.bounds.height*25.4) } / 1e6
puts "N=#{gs.size} AREA=#{tot.round(3)}"
''')
    vals = kv(r)
    c2.ok("楼板挖洞：拆成多块（不是一块填实）", int(vals.get("N", "0") or 0) >= 4,
         f"块数 {vals.get('N')}")
    c2.ok("★ 楼板挖洞：**总面积 = 100 − 9 = 91 m²**",
         abs(float(vals.get("AREA", "0") or 0) - 91.0) < 0.01,
         f"实测 {vals.get('AREA')} m²（这是唯一能发现『母组静默失败』的办法）")
    total += c2.report("B. 楼板挖洞（防『move_to 静默失败』）")

    # ── C. 螺旋楼梯：踏面要够宽、要能上到标高
    c3 = Check()
    r = ruby(setup + '''
gs2 = P.spiral_stair(ents, 'T-梯', 5000, 5000, 900, 0, 2800, steps: 16, total_deg: 420)
gs = ents.grep(Sketchup::Group)
treads = gs.select { |g| g.name.to_s.include?('踏') }
zs = treads.map { |g| (g.bounds.max.z*25.4) }
# 每级踏面在切向上的宽度（用"名字含踏"的组里、Z 最高的那一级的面积粗估）
top = treads.max_by { |g| g.bounds.max.z }
area = (top.bounds.width*25.4) * (top.bounds.height*25.4)
# 相邻踏面的朝向差（用各自最长边的方向角比较）
dirs = treads.sort_by { |g| g.bounds.max.z }.map do |g|
  b = g.bounds
  w = b.width*25.4; d = b.height*25.4
  # 用包围盒长宽比判朝向不够准，改用离心方向：从中心到该组中心的方位角
  c = g.bounds.center
  Math.atan2(c.y*25.4 - 5000.0, c.x*25.4 - 5000.0) * 180.0 / Math::PI
end
rot = dirs.each_cons(2).count { |a, b| ((a - b).abs % 360) > 5 }
maxr = treads.map { |g| b=g.bounds
  [[b.min.x*25.4-5000, b.max.x*25.4-5000].map(&:abs).max,
   [b.min.y*25.4-5000, b.max.y*25.4-5000].map(&:abs).max].max }.max
puts "STEPS=#{gs2[:steps]} TOP=#{zs.max.round} RISE=#{gs2[:rise].round(1)}"
puts "ROT=#{rot} MAXR=#{maxr.round}"
''')
    vals = kv(r)
    c3.ok("螺旋楼梯：级数正确", vals.get("STEPS") == "16", f"级数 {vals.get('STEPS')}")
    c3.ok("★ 螺旋楼梯：顶步到达二层楼面 2800",
         abs(float(vals.get("TOP", "0") or 0) - 2800) < 1,
         f"顶步 Z = {vals.get('TOP')}（到不了就是上不去）")
    # ⚠️ 第一版我测的是"顶步包围盒 > 1200"，**这是错的**：
    # 扇形跨 26°、半径 900 时弦长约 700，包围盒 748×809 本来就是对的。
    # 真正该测的是**相邻踏面在绕中心旋转**（那才是螺旋），
    # 以及踏面是**从中心扫出去的**（外缘到半径处）。
    c3.ok("★ 螺旋楼梯：相邻踏面在绕中心旋转（真的是螺旋）",
         int(vals.get("ROT", "0") or 0) >= 15,
         f"相邻朝向不同的踏面对数 = {vals.get('ROT')}（应≈15，即每级都转）")
    c3.ok("★ 螺旋楼梯：踏面从中心扫到半径处",
         float(vals.get("MAXR", "0") or 0) > 800,
         f"踏面外缘到中心最大距离 = {vals.get('MAXR')}mm（半径 900）")
    total += c3.report("C. 螺旋楼梯（防『薄片堆叠』）")

    print()
    print("=" * 66)
    print("✅ 构件库验证通过" if total == 0 else f"❌ 有 {total} 项未通过")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
