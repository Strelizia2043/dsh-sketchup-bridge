#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""参数扫描：用一批不同参数的合成图纸，批量量出提取精度。

为什么必须做（上一轮的教训）：
单一合成图会**系统性地掩盖它刚好能过的缺陷**。
1:50 那张图在线长门槛上只有 1.25 倍余量，所以"门槛用长边"这个 bug
二十多轮没被发现——换成 1:100 立刻暴露。

所以这里扫一批参数（比例、单位、长宽比、墙厚、洞口尺寸、内墙位置），
每张图都有**从参数算出的已知真值**，逐项比误差。

真值定义（都是**轴线到轴线**）：
    宽 = W_MM        高 = H_MM        内墙轴线 x = INT_X
    洞口：u 从所在墙的起点量起，w 为净宽
"""

from __future__ import annotations


import os
import sys

import json
import subprocess

# --- DSH 路径修正（重组后自动加，见 fix_imports.py）
def _dsh_bootstrap():
    """把依赖目录加进 sys.path（重组目录后必需）。

    ⚠️ 两个坑：
      1. 不能依赖模块级的 `import os` —— 本函数在文件顶部就被调用，
         那时 `import os` 还没执行。所以在**函数体内** import。
      2. 不能假设 `os.path.dirname(__file__)` 就是依赖所在目录：
         脚本在 tools/ 子目录，而 sk_client.py 在**根目录**，要逐级上溯。
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

# 工具定位：重组目录后脚本在 tools/* 下，用 tool() 按名字找（见 dsh_paths.py）
from dsh_paths import tool as _tool, tool_rel as _tool_rel

def _op_root():
    import os.path as _o
    _c = _o.dirname(_o.abspath(__file__))
    for _ in range(5):
        if _o.exists(_o.join(_c, 'sk_client.py')):
            return _c
        _p = _o.dirname(_c)
        if _p == _c:
            break
        _c = _p
    return _o.path.dirname(_o.path.abspath(__file__))

# 工作区根目录（含 sk_client.py 的那一层）。脚本搬到 tools/ 子目录后，
# 产物与基准图的路径必须以**根目录**为基准，不能用 __file__ 所在目录。
ROOT = _op_root()


HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
WORK = os.path.join(HERE, "sweep_out")
TOL = 60.0     # 与集成测试一致的容差


def variant(name: str, **kw) -> dict:
    """一个扫描方案。默认值来自 make_test_drawing.py 的默认方案。"""
    v = {"name": name, "w": 6000, "h": 4800, "scale": 50, "units": "mm",
         "ext_t": 240, "int_t": 120,
         "m1": 900, "c1": 1500, "c2": 1200, "m2": 800,
         "int_x": 3600, "m1_u": 900, "c1_u": 2600, "m2_v": 1900}
    v.update(kw)
    return v


VARIANTS = [
    variant("基准 1:50 mm"),
    variant("1:100 cm标注", scale=100, units="cm"),
    variant("1:20 放大", scale=20),
    variant("1:200 缩小", scale=200),
    variant("横长 9000×3000", w=9000, h=3000),
    # 窄长房：洞口起点必须按 3000 的墙长给（造图器现在会校验越界）
    variant("竖高 3000×9000", w=3000, h=9000, int_x=1800,
            m1_u=350, c1_u=1300, m2_v=3600, m1=800, c1=900),
    variant("正方形 6000×6000", w=6000, h=6000),
    variant("厚墙 370/240", ext_t=370, int_t=240),
    variant("薄墙 120/60", ext_t=120, int_t=60),
    # 大洞口：M1 与 C1 之间要留出实心段，所以起点拉开
    variant("大洞口 2400", m1=1400, c1=1400, m1_u=300, c1_u=2200),
    variant("小洞口 600", m1=600, c1=600, c2=600, m2=600),
    variant("内墙靠左 x=1200", int_x=1200),
    variant("内墙靠右 x=5400", int_x=5400),
    variant("内墙居中 x=3000", int_x=3000),
    variant("小房子 3000×2400", w=3000, h=2400, int_x=1800, m1=700, c1=900,
            m2=700, c2=800, m1_u=300, c1_u=1300, m2_v=700),
    # 洞口过大：南墙两个洞口加起来占掉墙的大部分，实心段很短
    variant("超大洞口 4500", w=6000, h=4800, m1=2000, c1=2000, m1_u=200, c1_u=2400),
]


def gen(v: dict, out: str) -> None:
    cmd = [PY, _tool("make_test_drawing.py"), out,
           "--scale", str(v["scale"]), "--units", v["units"],
           "--w", str(v["w"]), "--h", str(v["h"]),
           "--ext-t", str(v["ext_t"]), "--int-t", str(v["int_t"]),
           "--m1", str(v["m1"]), "--c1", str(v["c1"]),
           "--c2", str(v["c2"]), "--m2", str(v["m2"]),
           "--int-x", str(v["int_x"]),
           # 洞口起点必须显式传：造图器的默认值按墙长比例算，
           # 而扫描台的真值表里有自己的 m1_u/c1_u/m2_v，不传就对不上。
           "--m1-u", str(v["m1_u"]), "--c1-u", str(v["c1_u"]),
           "--m2-v", str(v["m2_v"])]
    r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300)
    if r.returncode != 0:
        tail = (r.stdout or "").strip().splitlines()
        raise RuntimeError("造图失败: " + (" / ".join(tail[-2:])[:160] if tail else "未知"))


def probe_span(img: str) -> tuple[float, float, int, int]:
    """返回 (竖墙跨距px, 横墙跨距px, 竖线条数, 横线条数)。

    ⚠️ 挑墙的判据必须与 `extract_plan._pick_walls` **一致**（相对厚度），
    否则测试台会比被测对象更严，报出"墙线不足"而提取其实成功了。
    我第一版就在这里写死 `thickness_px >= 5`，于是 1:20 那张图
    （最厚 10px、墙 3px）在扫描台被判死刑，与提取结果矛盾。
    """
    sys.path.insert(0, HERE)
    import extract_plan as EP
    # 线长门槛也要与提取器一致（按各方向 10%，取宽松的那个）
    mr = EP._line_min_run(img)
    r = subprocess.run([PY, _tool("plan_probe.py"), img,
                        "--lines", "--min-run", str(mr), "--max-lines", "40"],
                       cwd=HERE, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300)
    d = json.loads(r.stdout)
    v, h, _ = EP._pick_walls(d["vertical_lines"], d["horizontal_lines"])
    if len(v) < 2 or len(h) < 2:
        return 0.0, 0.0, len(v), len(h)
    return v[-1]["center"] - v[0]["center"], h[-1]["center"] - h[0]["center"], len(v), len(h)


def extract(img: str, calib_px: float, out: str, v: dict) -> tuple[dict | None, str]:
    cmd = [PY, _tool("extract_plan.py"), img,
           "--calib", str(v["w"]), "--calib-px", f"{calib_px:.2f}",
           "--unit", "mm", "--outer-t", str(v["ext_t"]), "--inner-t", str(v["int_t"]),
           "--name", v["name"], "--out", out]
    r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=400)
    if r.returncode != 0:
        tail = (r.stdout or "").strip().splitlines()
        return None, (tail[-1][:70] if tail else f"退出码 {r.returncode}")
    with open(out, encoding="utf-8") as f:
        return json.load(f), ""


def measure(data: dict, v: dict) -> dict:
    """从提取结果取出可比对的量。"""
    out = {}
    ws = data.get("walls") or []
    xs, ys = [], []
    for w in ws:
        for p in (w.get("from"), w.get("to")):
            if p:
                xs.append(float(p[0])); ys.append(float(p[1]))
    if xs and ys:
        out["W"] = max(xs) - min(xs)
        out["H"] = max(ys) - min(ys)
    # 内墙
    for w in ws:
        fx, fy = float(w["from"][0]), float(w["from"][1])
        tx, ty = float(w["to"][0]), float(w["to"][1])
        if abs(fx - tx) < 1 and abs(fy - ty) > 500:
            if 1 < fx < v["w"] - 1:
                out["INT_X"] = fx
    # 南墙洞口（按 u 排序）
    if ws:
        south = min(ws, key=lambda w: min(float(w["from"][1]), float(w["to"][1])))
        ops = sorted(south.get("openings") or [], key=lambda o: float(o.get("u", 0)))
        for i, key in enumerate(("OP1", "OP2")):
            if i < len(ops):
                out[f"{key}_U"] = float(ops[i].get("u", 0))
                out[f"{key}_W"] = float(ops[i].get("width", 0))
    # 东墙上的窗
    for w in ws:
        fx, fy = float(w["from"][0]), float(w["from"][1])
        tx, ty = float(w["to"][0]), float(w["to"][1])
        if abs(fx - tx) < 1 and abs(fy - ty) > 500 and (w.get("openings") or []):
            if abs(fx - max(xs or [0])) < 2:
                o = w["openings"][0]
                out["C2_U"] = float(o.get("u", 0))
                out["C2_W"] = float(o.get("width", 0))
    return out


def truth(v: dict) -> dict:
    return {"W": v["w"], "H": v["h"], "INT_X": v["int_x"],
            "OP1_U": v["m1_u"], "OP1_W": v["m1"],
            "OP2_U": v["c1_u"], "OP2_W": v["c1"],
            "C2_U": v["h"] / 2 - v["c2"] / 2, "C2_W": v["c2"]}


KEYS = ["W", "H", "INT_X", "OP1_U", "OP1_W", "OP2_U", "OP2_W", "C2_U", "C2_W"]


def main() -> int:
    os.makedirs(WORK, exist_ok=True)
    rows = []
    for i, v in enumerate(VARIANTS):
        img = os.path.join(WORK, f"v{i:02d}.png")
        js = os.path.join(WORK, f"v{i:02d}.json")
        try:
            gen(v, img)
        except Exception as e:  # noqa: BLE001
            rows.append((v["name"], None, f"造图失败 {e}"))
            continue
        span_v, _span_h, nv, nh = probe_span(img)
        if span_v <= 0:
            rows.append((v["name"], None, f"墙线不足（竖{nv} 横{nh}）"))
            continue
        try:
            data, err = extract(img, span_v, js, v)
        except Exception as e:  # noqa: BLE001
            rows.append((v["name"], None, f"提取异常 {e}"))
            continue
        if data is None:
            rows.append((v["name"], None, err))
            continue
        got = measure(data, v)
        tv = truth(v)
        errs = {}
        for k in KEYS:
            if k in got and k in tv:
                errs[k] = got[k] - tv[k]
        rows.append((v["name"], errs, None))

    hdr = f"{'方案':<20}" + "".join(f"{k:>9}" for k in KEYS)
    print(hdr)
    print("-" * len(hdr))
    worst = {}
    bad = []
    for name, errs, err in rows:
        if err:
            print(f"{name:<20}  ❌ {err}")
            bad.append((name, err, {}))
            continue
        line = f"{name:<20}"
        over = []
        for k in KEYS:
            if k in errs:
                e = errs[k]
                mark = "" if abs(e) <= TOL else "!!"
                line += f"{e:>7.0f}{mark:<2}"
                worst[k] = max(worst.get(k, 0), abs(e))
                if abs(e) > TOL:
                    over.append(f"{k} {e:+.0f}")
            else:
                line += f"{'—':>9}"
        if over:
            bad.append((name, "", over))
        print(line)

    print()
    print(f"容差 ±{TOL:.0f}mm；!! = 超差；— = 没提取到")
    print()
    if worst:
        print("各量最大误差：")
        for k in KEYS:
            if k in worst:
                print(f"  {k:<8} {worst[k]:>8.0f} mm")
    print()
    if bad:
        print(f"⚠️ {len(bad)} 个方案有问题：")
        for name, err, over in bad:
            print(f"  {name}: {err or ('超差 ' + ', '.join(over))}")
    else:
        print("✅ 全部方案均在容差内")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
