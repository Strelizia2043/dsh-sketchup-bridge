#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CAD（DXF）→ 建筑模型：统一入口。

为什么单独做这一条：它和"从图片量尺寸"是**两条完全不同的路**。

    图片路线（前 33 轮做的）        CAD 路线（本脚本）
    ────────────────────────       ──────────────────
    靠墨迹与纸张的对比找线          坐标是**精确值**（±0.01mm）
    要标定比例（--calib-px）        单位由图纸给定，**不需要标定**
    墙厚量不准（误差 5~10%）        墙厚是**读出来的**，不是量的
    洞口类型靠"贯穿线"猜            洞口类型由**颜色/图层直接给出**
    透视要人肉保证平拍              不涉及

结论：**能拿到 CAD 就绝不要用图片**。颜色语义一旦说清，
洞口判定从"猜"变成"读"——这是本路径最大的价值。

用法
────
    python dxf_import.py 图纸.dxf                       # 只探查，输出结构报告
    python dxf_import.py 图纸.dxf --map cad_map.json    # 按语义表分类并生成 plan JSON
    python dxf_import.py 图纸.dxf --map cad_map.json --out plan.json

语义表（--map）是一个 JSON，把"颜色/图层"映射到建筑含义：

    {
      "units": "mm",
      "wall_height": 3000,
      "door_height": 2400,
      "floor_thickness": 50,
      "envelope": {"x0": 0, "y0": 0, "x1": 5000, "y1": 5000},
      "roles": { "wall": [7], "door": [1, 10, 70], "window": [3],
                 "dimension": [2, 50] },
      "role_by_layer": { "0": "wall", "Layer1": "door" },
      "plan_name": "店面平面"
    }

  · `roles` 的键是建筑含义，值是 **AutoCAD 颜色号（ACI）** 列表。
  · `role_by_layer` 优先于 `roles`（图层名比颜色号更稳）。
  · `envelope` 给出建筑外轮廓（**外皮**坐标），脚本负责换算成中线——
    这是最容易错的一步，见文件末尾的"约定陷阱"。

为什么不把语义写死在代码里：**同一栋楼不同人用的颜色习惯不同**。
先跑一次不带 --map 的探查，看清图里有哪些颜色，再写映射表。
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
    for _d in ['.']:
        _p = _op.normpath(_op.join(_cur, _d))
        if _p not in _sys.path:
            _sys.path.insert(0, _p)


_dsh_bootstrap()

import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dxf_probe import read_pairs, decode_cn  # noqa: E402

# AutoCAD 颜色号 → 中文名（常用部分，仅用于报告可读性）
ACI_NAME = {
    1: "红", 2: "黄", 3: "绿", 4: "青", 5: "蓝", 6: "洋红", 7: "白/黑",
    8: "深灰", 9: "浅灰", 10: "红", 30: "橙", 50: "黄", 70: "红",
    250: "深灰", 251: "灰", 252: "浅灰", 253: "更浅灰", 254: "近白", 255: "白",
}


# ──────────────────────────────────────────────────────────── 解析

def parse_dxf(path: str):
    """返回 (实体列表, 块定义, 图层表)。

    实体形如 {"type","layer","color","block", 以及各类型自己的几何字段}。
    color 为 None 表示 BYLAYER（要用图层颜色解析）。
    """
    pairs = read_pairs(path)

    layers = {}
    i = 0
    while i < len(pairs):
        if pairs[i][0] == 0 and pairs[i][1] == "LAYER":
            a = collections.defaultdict(list)
            j = i + 1
            while j < len(pairs) and pairs[j][0] != 0:
                a[pairs[j][0]].append(pairs[j][1])
                j += 1
            nm = decode_cn((a.get(2) or ["?"])[0])
            try:
                layers[nm] = int(a[62][0])
            except (KeyError, ValueError, IndexError):
                layers[nm] = 7
            i = j
            continue
        i += 1

    ents, blocks = [], {}
    sect = None
    cur_block = None
    i = 0
    while i < len(pairs):
        c, v = pairs[i]
        if c == 0 and v == "SECTION":
            sect = pairs[i + 1][1] if i + 1 < len(pairs) else None
            i += 2
            continue
        if c == 0 and v == "ENDSEC":
            sect, cur_block = None, None
            i += 1
            continue
        if c == 0 and v == "BLOCK":
            a = collections.defaultdict(list)
            j = i + 1
            while j < len(pairs) and pairs[j][0] != 0:
                a[pairs[j][0]].append(pairs[j][1])
                j += 1
            cur_block = decode_cn((a.get(2) or ["*?"])[0])
            blocks.setdefault(cur_block, [])
            i = j
            continue
        if c == 0 and v == "ENDBLK":
            cur_block = None
            i += 1
            continue
        if c == 0 and v in ("LINE", "LWPOLYLINE", "POINT", "SOLID", "CIRCLE",
                            "ARC", "TEXT", "MTEXT", "INSERT", "DIMENSION"):
            etype = v
            a = collections.defaultdict(list)
            j = i + 1
            while j < len(pairs) and pairs[j][0] != 0:
                a[pairs[j][0]].append(pairs[j][1])
                j += 1

            def f(code, idx=0):
                try:
                    return float(a[code][idx])
                except (KeyError, ValueError, IndexError):
                    return None

            e = {"type": etype,
                 "layer": decode_cn((a.get(8) or ["0"])[0]),
                 "color": int(a[62][0]) if a.get(62) and a[62][0].strip() else None,
                 "block": cur_block}
            if etype == "LINE":
                e["p1"], e["p2"] = (f(10), f(20)), (f(11), f(21))
            elif etype == "LWPOLYLINE":
                e["pts"] = list(zip([float(x) for x in a.get(10, [])],
                                    [float(y) for y in a.get(20, [])]))
                e["closed"] = int(a[70][0]) if a.get(70) else 0
            elif etype == "SOLID":
                e["pts"] = [(f(10), f(20)), (f(11), f(21)),
                            (f(12), f(22)), (f(13), f(23))]
            elif etype == "INSERT":
                e["name"] = decode_cn((a.get(2) or ["?"])[0])
                e["at"] = (f(10), f(20))
            elif etype in ("MTEXT", "TEXT"):
                e["text"] = decode_cn("".join(a.get(1, [])) + "".join(a.get(3, [])))
                e["at"] = (f(10), f(20))
            elif etype == "DIMENSION":
                e["measure"] = f(42)
                e["text"] = decode_cn((a.get(1) or [""])[0])
                e["at"] = (f(10), f(20))
            ents.append(e)
            if cur_block:
                blocks[cur_block].append(e)
            i = j
            continue
        i += 1
    return ents, blocks, layers


def segs_of(e):
    """把一个实体拆成线段 [(P1, P2), ...]。"""
    t = e["type"]
    if t == "LINE" and e.get("p1") and e.get("p2"):
        return [(e["p1"], e["p2"])]
    if t == "LWPOLYLINE":
        p = [q for q in (e.get("pts") or []) if q and q[0] is not None]
        out = [(p[i], p[i + 1]) for i in range(len(p) - 1)]
        if len(p) > 2 and (e.get("closed") or p[0] != p[-1]):
            out.append((p[-1], p[0]))
        return out
    if t == "SOLID":
        p = [q for q in (e.get("pts") or []) if q and q[0] is not None]
        if len(p) >= 3:
            return [(p[i], p[(i + 1) % len(p)]) for i in range(len(p))]
    return []


def aci_of(e, layers):
    """解析实体**实际显示**的颜色号。

    ⚠️ 两个哨兵值必须处理，否则报告会误导人：
      · 62 = 0   → BYBLOCK（随块），实际显示取**所在图层**的颜色
      · 62 = 256 → BYLAYER（随层），同样取图层颜色
    我第一版把 0 当成"黑色"直接报出去，结果报告里出现
    「ACI=0 几何实体 93 个」，看起来像图里有一大堆黑实体——
    其实是 Layer2 的黄色标注。**错误的中间结果比没有结果更糟**，
    因为它会让我自己下一轮基于它做判断。
    """
    c = e.get("color")
    if c is None or c in (0, 256):
        return layers.get(e["layer"], 7)
    return c


# ──────────────────────────────────────────────────────────── 探查

def probe(ents, blocks, layers) -> int:
    print("=" * 70)
    print("DXF 结构探查（先看这个，再写语义表）")
    print("=" * 70)

    print(f"\n【图层】{len(layers)} 个")
    for nm, c in layers.items():
        print(f"   {nm:<20} ACI={c:<4} {ACI_NAME.get(c, '?'):<6} "
              f"实体数={sum(1 for e in ents if e['layer'] == nm)}")

    print(f"\n【实体类型】共 {len(ents)} 个")
    for t, n in collections.Counter(e["type"] for e in ents).most_common():
        print(f"   {t:<14} {n:>5}")

    print("\n【实际渲染颜色】(BYLAYER 已按图层解析)")
    by = collections.Counter()
    for e in ents:
        if e["type"] in ("LINE", "LWPOLYLINE", "SOLID"):
            by[aci_of(e, layers)] += 1
    for c, n in sorted(by.items()):
        print(f"   ACI={c:<4} {ACI_NAME.get(c, '?'):<6} 几何实体 {n:>4} 个")

    print("\n【建议的语义表骨架】把下面 roles 里的颜色号改成你图上的实际含义：")
    geom = sorted(by.keys())
    print(json.dumps({
        "units": "mm",
        "wall_height": 3000, "door_height": 2400, "floor_thickness": 50,
        "roles": {"wall": geom[:1], "door": geom[1:2], "window": geom[2:3],
                  "dimension": []},
        "role_by_layer": {},
    }, ensure_ascii=False, indent=2))
    return 0


# ──────────────────────────────────────────────────────────── 分类 → plan

def build_plan(ents, blocks, layers, m: dict) -> dict:
    roles = {k: set(v) for k, v in (m.get("roles") or {}).items()}
    layer_role = m.get("role_by_layer") or {}

    def role_of(e):
        if e["layer"] in layer_role:
            return layer_role[e["layer"]]
        aci = aci_of(e, layers)
        for r, acis in roles.items():
            if aci in acis:
                return r
        return "other"

    buckets = collections.defaultdict(list)
    for e in ents:
        if e["layer"] == "Defpoints":
            continue
        # 标注块（*D*）里是尺寸线，不是建筑
        if (e.get("block") or "").startswith("*D"):
            continue
        s = segs_of(e)
        if s:
            buckets[role_of(e)].append(s)

    print("【按语义分类】")
    for r in sorted(buckets):
        n = sum(len(v) for v in buckets[r])
        print(f"   {r:<12} {len(buckets[r]):>4} 个实体 / {n:>4} 条线段")

    if not buckets.get("wall"):
        print("\n❌ 没有识别到墙（role='wall'）。请用 --map 指定 wall 对应的颜色。")
        print("   提示：先跑不带 --map 的探查，看【实际渲染颜色】那一节。")
        return {}

    walls_segs = buckets["wall"]
    env = m.get("envelope")
    if env:
        ox, oy, ex, ey = env["x0"], env["y0"], env["x1"], env["y1"]
    else:
        xs = [c for s in walls_segs for seg in s for c in (seg[0][0], seg[1][0])]
        ys = [c for s in walls_segs for seg in s for c in (seg[0][1], seg[1][1])]
        ox, oy, ex, ey = min(xs), min(ys), max(xs), max(ys)
        print(f"\n⚠️ 没给 envelope，按墙线范围推断：{ox}..{ex} × {oy}..{ey}")
        print("   （若墙线是中线而非外皮，这个范围会偏小——务必核对）")

    ox, oy = round(ox, 3), round(oy, 3)
    W, H = round(ex - ox, 3), round(ey - oy, 3)
    print(f"\n【建筑外轮廓】{W} × {H}  （原点移到 {ox},{oy}）")

    # ── 墙：把"成对的面线"配对成墙矩形
    #
    # 图上墙通常画两条平行线（两个面）。配对规则：
    # 同向、间距在 (0, 400mm] 之间、投影重叠 —— 视为同一道墙的两个面。
    # 配不上的线（单线墙）按"线宽=厚度"无法恢复，此时用 wall_thickness 兜底。
    def key_of(seg):
        (x1, y1), (x2, y2) = seg
        horiz = abs(y1 - y2) < 1e-6
        vert = abs(x1 - x2) < 1e-6
        return ("h", round(min(y1, y2) - oy, 3)) if horiz else \
               (("v", round(min(x1, x2) - ox, 3)) if vert else None)

    lines = collections.defaultdict(list)
    for seg in walls_segs:
        k = key_of(seg)
        if k:
            lines[k].append(seg)

    # 相邻平行墙线配对
    coords = collections.defaultdict(list)   # 方向 → 该方向的坐标列表
    for (d, v) in lines:
        coords[d].append(v)
    for d in coords:
        coords[d] = sorted(set(coords[d]))

    max_t = float(m.get("max_wall_thickness", 400))
    pairs = []
    for d in coords:
        vs = coords[d]
        for a, b in zip(vs, vs[1:]):
            t = b - a
            if 0 < t <= max_t:
                pairs.append((d, a, b, t))

    print(f"\n【墙】配对出 {len(pairs)} 道（成对面线，间距 ≤{max_t}mm）")
    for d, a, b, t in pairs[:40]:
        print(f"   {'水平' if d == 'h' else '竖直'}  位置 {a:>9.2f}..{b:>9.2f}  厚 {t:>7.2f}")
    if len(pairs) > 40:
        print(f"   …… 还有 {len(pairs) - 40} 道")

    # ── 洞口：按语义取包围盒
    def boxes(role):
        out = []
        for seg in buckets.get(role) or []:
            xs = [c for s in seg for c in (s[0][0], s[1][0])]
            ys = [c for s in seg for c in (s[0][1], s[1][1])]
            out.append((min(xs) - ox, min(ys) - oy, max(xs) - ox, max(ys) - oy))
        return out

    doors, wins = boxes("door"), boxes("window")
    print(f"\n【洞口】门 {len(doors)} 个 / 窗 {len(wins)} 个")
    for tag, bs in (("门", doors), ("窗", wins)):
        for i, (x0, y0, x1, y1) in enumerate(bs, 1):
            w, h = x1 - x0, y1 - y0
            print(f"   {tag}{i}: X {x0:.2f}..{x1:.2f}  Y {y0:.2f}..{y1:.2f}   "
                  f"净尺寸 {max(w, h):.2f} × {min(w, h):.2f}")

    # ── 组装 plan JSON
    wall_h = float(m.get("wall_height", 3000))
    door_h = float(m.get("door_height", 2400))
    role_walls = []
    for idx, (d, a, b, t) in enumerate(pairs, 1):
        if d == "h":
            frm, to = [ox - ox, a], [W, a]           # 端点稍后按洞口裁剪
            frm, to = [0.0, (a + b) / 2], [W, (a + b) / 2]
        else:
            frm, to = [(a + b) / 2, 0.0], [(a + b) / 2, H]
        role_walls.append({"name": f"W-{'H' if d == 'h' else 'V'}{idx}",
                           "from": frm, "to": to, "thickness": t,
                           "height": wall_h, "source": "dim", "confidence": "high",
                           "basis": "墙线来自 DXF 实体坐标（成对平行线配对）"})

    plan = {
        "meta": {
            "name": m.get("plan_name", "读自 DXF"),
            "units": m.get("units", "mm"),
            "scale_basis": "DXF 实体坐标即真实尺寸（无需标定）",
            "assumptions": [
                f"墙高 {wall_h}（平面图不标墙高，取语义表给的默认值）",
                f"门高 {door_h}",
                "墙由成对平行线配对得到",
            ],
        },
        "floors": [{
            "name": "F1-地板", "z": 0,
            "thickness": float(m.get("floor_thickness", 50)),
            "polygon": [[0, 0], [W, 0], [W, H], [0, H]],
            "source": "dim", "confidence": "high",
        }],
        "walls": role_walls,
        "_openings_raw": {"doors": doors, "windows": wins},
        "_note": "洞口还需落到具体墙面上（点此脚本的 --auto-openings 或手工指定）",
    }
    return plan


def main() -> int:
    ap = argparse.ArgumentParser(description="DXF → 建筑模型 统一入口")
    ap.add_argument("dxf")
    ap.add_argument("--map", dest="mapfile", help="语义表 JSON")
    ap.add_argument("--out", help="输出 plan JSON")
    a = ap.parse_args()

    ents, blocks, layers = parse_dxf(a.dxf)
    if not a.mapfile:
        return probe(ents, blocks, layers)

    with open(a.mapfile, encoding="utf-8") as f:
        m = json.load(f)
    plan = build_plan(ents, blocks, layers, m)
    if not plan:
        return 1
    out = a.out or "cad_plan.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=1)
    print(f"\n已写出 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
