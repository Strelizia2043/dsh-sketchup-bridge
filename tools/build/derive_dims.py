#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""建筑尺寸推导计算器 —— 把"能算出来的"算出来，算不出来的明确说不出来。

设计原则（来自用户的要求）：
  * 能用数学推出来的，必须**真的推**，并写出算式
  * 推不出来的，**不许凑数**，直接告诉用户"这个我算不出来，请给我数值"
  * 单位不明时，**先问用户**，不按惯例假定（建筑图 mm、家居图 cm，差 10 倍）

用法示例：
    # 墙厚：外墙轴线 200cm，内墙轴线 160cm
    python derive_dims.py wall-thickness --outer 200 --inner 160 --unit cm

    # 已知轴线与墙厚，求房间净尺寸
    python derive_dims.py clear --axis 3600 --thickness 240 --sides 2 --unit mm

    # 批量：从一份尺寸链里找出能推的和不能推的
    python derive_dims.py audit --file dims.json
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
    for _d in ['.', 'tools/cad', 'tools/img']:
        _p = _op.normpath(_op.join(_cur, _d))
        if _p not in _sys.path:
            _sys.path.insert(0, _p)


_dsh_bootstrap()

import argparse
import json
import sys

UNIT_TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0}


def to_mm(v: float, unit: str) -> float:
    if unit not in UNIT_TO_MM:
        raise SystemExit(f"未知单位 {unit!r}，只支持 mm / cm / m")
    return v * UNIT_TO_MM[unit]


def fmt_mm(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


# ------------------------------------------------------------------ 算式

def wall_thickness(outer: float, inner: float, unit: str, mode: str) -> dict:
    """由"外墙轴线总长"与"内墙轴线间距"反推墙厚。

    用户给的规则：t = (外墙轴线总长 - 内墙轴线间距) / 2
    几何含义：房间尺寸标注到轴线时，房间两侧各占半个墙厚。

    但也支持另一种常见标注方式（内墙之间是净距）：
        t = (外墙轴线总长 - 净距) / 4
    """
    o = to_mm(outer, unit)
    i = to_mm(inner, unit)
    diff = o - i
    if diff <= 0:
        return {
            "ok": False,
            "why": f"外墙轴线 {fmt_mm(o)}mm 不大于内墙轴线 {fmt_mm(i)}mm，无法推出墙厚",
            "need_from_user": "请直接告诉我墙厚",
        }
    if mode == "axis":
        t = diff / 2.0
        formula = f"({fmt_mm(o)} - {fmt_mm(i)}) / 2 = {fmt_mm(t)}mm"
        note = "假设内墙尺寸标注到轴线（房间两侧各占半个墙厚）"
    elif mode == "clear":
        t = diff / 4.0
        formula = f"({fmt_mm(o)} - {fmt_mm(i)}) / 4 = {fmt_mm(t)}mm"
        note = "假设内墙之间标的是净距（两侧各有一个完整墙厚）"
    else:
        return {"ok": False, "why": f"未知模式 {mode!r}"}

    res = {
        "ok": True,
        "wall_thickness_mm": round(t, 1),
        "wall_thickness_original_unit": round(t / UNIT_TO_MM[unit], 3),
        "formula": formula,
        "mode": mode,
        "note": note,
        "source": "derived",
        "confidence": "high" if mode == "axis" else "medium",
    }
    if t < 60 or t > 600:
        res["warning"] = (f"推出墙厚 {fmt_mm(t)}mm 不太常见（一般 100~400mm）。"
                          f"很可能标注方式不是我以为的那种，请确认。")
        res["confidence"] = "low"
    if abs(t - round(t / 10) * 10) > 1:
        res.setdefault("warnings", []).append(
            f"推出值 {fmt_mm(t)}mm 不是 10mm 的整数倍，实际图纸上墙厚通常是整数，请核对")
    return res


def clear_size(axis: float, thickness: float, sides: int, unit: str) -> dict:
    """由轴线尺寸与墙厚求净尺寸。"""
    a = to_mm(axis, unit)
    t = to_mm(thickness, unit)
    clear = a - sides * t / 2.0
    if clear <= 0:
        return {"ok": False, "why": f"净尺寸算出来是 {fmt_mm(clear)}mm，不可能。墙厚或轴线有误",
                "need_from_user": "请核对轴线尺寸与墙厚"}
    return {
        "ok": True,
        "axis_mm": a,
        "thickness_mm": t,
        "clear_mm": round(clear, 1),
        "formula": f"{fmt_mm(a)} - {sides} × {fmt_mm(t)}/2 = {fmt_mm(clear)}mm",
        "source": "derived",
        "confidence": "high",
    }


def total_from_segments(segments, unit: str) -> dict:
    """尺寸链求和（总尺寸 = 各分段之和），用于核对图纸标注是否自洽。"""
    total = sum(to_mm(s, unit) for s in segments)
    return {
        "ok": True,
        "segments_mm": [round(to_mm(s, unit), 1) for s in segments],
        "total_mm": round(total, 1),
        "formula": " + ".join(fmt_mm(to_mm(s, unit)) for s in segments) + f" = {fmt_mm(total)}mm",
        "source": "derived",
    }


def check_chain(declared_total: float, segments, unit: str, tol: float = 1.0) -> dict:
    """核对：图纸声明的总尺寸 vs 分段之和。不一致就报警——这是抓图错的关键手段。"""
    s = total_from_segments(segments, unit)
    d = to_mm(declared_total, unit)
    diff = s["total_mm"] - d
    return {
        "ok": abs(diff) <= tol,
        "declared_total_mm": round(d, 1),
        "segments_sum_mm": s["total_mm"],
        "difference_mm": round(diff, 1),
        "formula": s["formula"],
        "verdict": ("✅ 尺寸链自洽" if abs(diff) <= tol
                    else f"⚠️ 分段之和比声明总尺寸多 {fmt_mm(diff)}mm，图纸标注可能漏了一段或我读错了一位数字"),
    }


# ------------------------------------------------------------------ 审计

def audit(units_declared: bool, dims: list) -> dict:
    """批量审计一份尺寸清单：哪些能推、哪些不能推、哪些必须问用户。

    dims 里每项形如：
      {"name": "南外墙厚", "value": null, "derivable": true,
       "from": ["外墙轴线长 200cm", "内墙轴线间距 160cm"], "rule": "wall_thickness"}
    """
    blocked, ready = [], []
    for d in dims:
        if d.get("value") is not None:
            ready.append({"name": d["name"], "value": d["value"], "source": "dim"})
        elif d.get("derivable"):
            ready.append({"name": d["name"], "source": "derived",
                          "from": d.get("from"), "rule": d.get("rule")})
        else:
            blocked.append({
                "name": d["name"],
                "why": "图上没有标注，也无法用已确认的尺寸推出",
                "ask_user": f"请告诉我「{d['name']}」是多少（{d.get('unit_hint', 'mm 或 cm 请注明')}）",
            })
    return {
        "units_declared": units_declared,
        "unit_gate": ("通过" if units_declared
                      else "❌ 未声明单位 → 按规则打回，先问用户单位"),
        "can_build": len(blocked) == 0 and units_declared,
        "ready": ready,
        "must_ask_user": blocked,
    }


# ------------------------------------------------------------------ CLI

def main() -> int:
    ap = argparse.ArgumentParser(description="建筑尺寸推导计算器")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("wall-thickness", help="由外墙轴线与内墙轴线反推墙厚")
    p1.add_argument("--outer", type=float, required=True)
    p1.add_argument("--inner", type=float, required=True)
    p1.add_argument("--unit", default=None, help="mm / cm / m；不填则拒绝计算并要求用户说明")
    p1.add_argument("--mode", default="axis", choices=["axis", "clear"])

    p2 = sub.add_parser("clear", help="由轴线尺寸与墙厚求净尺寸")
    p2.add_argument("--axis", type=float, required=True)
    p2.add_argument("--thickness", type=float, required=True)
    p2.add_argument("--sides", type=int, default=2)
    p2.add_argument("--unit", default=None)

    p3 = sub.add_parser("chain", help="尺寸链求和 / 核对")
    p3.add_argument("--segments", type=float, nargs="+", required=True)
    p3.add_argument("--declared-total", type=float, default=None)
    p3.add_argument("--unit", default=None)

    p4 = sub.add_parser("audit", help="批量审计（读 JSON）")
    p4.add_argument("--file", required=True)

    args = ap.parse_args()

    # 单位闸门：没有单位就不算——这是用户明确要求的
    if args.cmd in ("wall-thickness", "clear", "chain") and not args.unit:
        print(json.dumps({
            "ok": False,
            "blocked_by": "unit_gate",
            "why": "没有声明单位，拒绝计算",
            "forbidden_reason": "建筑图常用 mm，家居图常用 cm，两者差 10 倍，绝不能按惯例假定",
            "ask_user": "请告诉我图纸的单位是 mm 还是 cm（或 m）",
        }, ensure_ascii=False, indent=2))
        return 2

    if args.cmd == "wall-thickness":
        print(json.dumps(wall_thickness(args.outer, args.inner, args.unit, args.mode),
                         ensure_ascii=False, indent=2))
    elif args.cmd == "clear":
        print(json.dumps(clear_size(args.axis, args.thickness, args.sides, args.unit),
                         ensure_ascii=False, indent=2))
    elif args.cmd == "chain":
        out = total_from_segments(args.segments, args.unit)
        if args.declared_total is not None:
            out["chain_check"] = check_chain(args.declared_total, args.segments, args.unit)
        print(json.dumps(out, ensure_ascii=False, indent=2))
    elif args.cmd == "audit":
        with open(args.file, encoding="utf-8") as f:
            data = json.load(f)
        print(json.dumps(audit(data.get("units_declared", False), data.get("dims", [])),
                         ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
