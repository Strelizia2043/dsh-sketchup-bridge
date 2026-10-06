#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DXF → plan JSON：配置驱动版（把实测图纸的尺寸写进配置文件，不写进代码）。

为什么要拆出"配置"这一层：
第一版（dxf_to_planjson.py）把**这一张图的尺寸直接写死在代码里**——
5000、50、1481.53、2554.82…… 换一张图就全废，等于一次性脚本。
现在把所有图纸相关的量放进 `cad_map.json`，代码只负责"读配置 + 换算 + 产出"。

配置字段
────────
  units            单位（必须与图纸一致；DXF 坐标是无量纲的数，单位要靠人给）
  plan_name        模型名
  envelope         建筑**外皮**范围 {x0,y0,x1,y1}
  wall_thickness   外墙厚
  inner_thickness  内墙厚（缺省 = wall_thickness）
  wall_height      墙高（平面图不标，必须人给）
  door_height      门高（同上）
  floor_thickness  地板厚
  walls            墙列表：[{"name","axis":"h"/"v","at":中线位置,"thickness",
                            "span":[起,止]（可选）,"openings":[...]}]
  openings         洞口的定义方式见下

洞口写在**所属墙**里，用沿线局部坐标 u（从该墙 span 起点量起）：

  {"type":"door","u":3050,"width":1481.53,"height":2400,"sill":0,"label":"西-门"}

⚠️ 最容易错的一步：**中线 vs 外皮**
  生成器把"建筑外轮廓"定义为：所有墙**中线**的包络 + 该边墙的半厚。
  所以外皮在 0..5000 时，外墙中线必须在 25..4975。
  本脚本按这个约定自动把 envelope 缩进半厚——**不要自己再缩一次**。
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
import json
import os
import sys


def build(cfg: dict) -> dict:
    env = cfg["envelope"]
    x0, y0, x1, y1 = (float(env[k]) for k in ("x0", "y0", "x1", "y1"))
    W, H = x1 - x0, y1 - y0
    T = float(cfg.get("wall_thickness", 50))
    TI = float(cfg.get("inner_thickness", T))
    WH = float(cfg.get("wall_height", 3000))
    DH = float(cfg.get("door_height", 2400))
    FT = float(cfg.get("floor_thickness", 50))
    units = cfg.get("units", "mm")

    basis = ("坐标来自 DXF 实体几何（组码 10/11/20/21），单位为"
             f"{units}；外轮廓由配置给出，墙厚/墙高由配置给出")

    walls = []
    for w in cfg.get("walls") or []:
        axis = w["axis"]
        at = float(w["at"])
        th = float(w.get("thickness", TI if w.get("inner") else T))
        span = w.get("span")
        if span:
            a, b = float(span[0]), float(span[1])
        else:
            # 缺省：沿整个建筑范围（外墙用外皮范围，会自动缩半厚）
            a, b = 0.0, (W if axis == "h" else H)
        # 外皮 → 中线：两端各缩半厚。
        # 只对**贴外皮**的墙做（外墙，或用 on_envelope 显式指定）；
        # 内墙给的是自己面线的起止，不能再缩，否则会短半个墙厚。
        if w.get("on_envelope", not w.get("inner", False)):
            a += th / 2.0
            b -= th / 2.0

        if axis == "h":
            frm, to = [x0 + a, y0 + at], [x0 + b, y0 + at]
        else:
            frm, to = [x0 + at, y0 + a], [x0 + at, y0 + b]

        entry = {"name": w["name"], "from": frm, "to": to,
                 "thickness": round(th, 2), "height": WH,
                 "source": "dim", "confidence": "high", "basis": basis}

        ops = []
        # u 的基准核对 —— 必须做，否则洞口会**静默漂移**。
        #
        # 踩过：洞口 u 是从墙的 `from` 端量起的。我把约定从"矩形边界"
        # 改成"中线"之后，`from` 端从 y=0 变成 y=25，u 却仍按旧基准写，
        # 三个洞口全部漂了 25mm。**没有任何报错**，只能靠核对发现。
        #
        # 所以这里：若配置给了 `abs`（洞口在建筑坐标里的绝对位置），
        # 就换算成 u；否则用 u 并在超出墙长时报错。
        wall_len = ((to[0] - frm[0])**2 + (to[1] - frm[1])**2) ** 0.5
        for o in w.get("openings") or []:
            if "abs" in o:
                base = frm[0] if axis == "h" else frm[1]
                u_val = float(o["abs"]) - base
            else:
                u_val = float(o["u"])
            if u_val < -0.01 or u_val + float(o["width"]) > wall_len + 0.01:
                raise SystemExit(
                    f"❌ 墙 {w['name']} 的洞口 {o.get('label','?')} 超出墙范围："
                    f"u={u_val:.2f} 宽={o['width']} 墙长={wall_len:.2f}。"
                    f"（若你给的是绝对位置，请改写成 \"abs\" 字段）")
            oo = {"type": o.get("type", "door"),
                  "u": round(u_val, 2),
                  "width": round(float(o["width"]), 2),
                  "height": float(o.get("height", DH)),
                  "sill": float(o.get("sill", 0)),
                  "label": o.get("label", o.get("type", "洞")),
                  "source": o.get("source", "dim"),
                  "confidence": o.get("confidence", "high"),
                  "basis": o.get("basis", "洞口位置与净宽由配置给出（源自图纸实测）")}
            if o.get("note"):
                oo["note"] = o["note"]
            ops.append(oo)
        if ops:
            entry["openings"] = ops
        walls.append(entry)

    names = [w["name"] for w in walls]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise SystemExit(f"❌ 墙名重复：{dup}")

    return {
        "meta": {
            "name": cfg.get("plan_name", "读自 DXF"),
            "units": units,
            "scale_basis": f"DXF 实体坐标；外轮廓 {W:.2f}×{H:.2f} {units}",
            "assumptions": cfg.get("assumptions") or [
                f"墙高 {WH}{units}（平面图不标墙高，取配置值）",
                f"门高 {DH}{units}",
            ],
        },
        "floors": [{
            "name": "F1-地板", "z": 0, "thickness": FT,
            "polygon": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
            "source": "dim", "confidence": "high",
        }],
        "walls": walls,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="DXF/实测尺寸 → plan JSON（配置驱动）")
    ap.add_argument("config", help="cad_map.json 之类的配置")
    ap.add_argument("--out", default="plan_from_cad.json")
    a = ap.parse_args()

    with open(a.config, encoding="utf-8") as f:
        cfg = json.load(f)
    data = build(cfg)

    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    n_op = sum(len(w.get("openings") or []) for w in data["walls"])
    print(f"已写出 {a.out}：{len(data['walls'])} 面墙 / {n_op} 个洞口")
    for w in data["walls"]:
        no = len(w.get("openings") or [])
        print(f"  {w['name']:<16} {str(w['from']):<20} → {str(w['to']):<20} "
              f"厚{w['thickness']:<7} 洞口{no}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
