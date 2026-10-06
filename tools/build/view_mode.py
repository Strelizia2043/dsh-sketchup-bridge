#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""切换/查询审查视图模式，并可顺手出图。

用法：
    python view_mode.py open                     # 平面审查：隐藏天花/夹层/立面/门窗扇框
    python view_mode.py structure --shot struct  # 只看结构
    python view_mode.py level --z 2900           # 只看标高 2900 以下
    python view_mode.py full                     # 全部恢复
    python view_mode.py status                   # 看看现在可见/隐藏了什么
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
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sk_client import SC, BridgeError  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RB = os.path.join(HERE, "view_modes.rb").replace("\\", "/")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["full", "open", "structure", "level", "status"])
    ap.add_argument("--z", type=float, default=None, help="level 模式的标高上限（毫米）")
    ap.add_argument("--shot", default=None, help="出图名（会拍俯视平行投影 + 3/4 视角）")
    args = ap.parse_args()

    c = SC(timeout=90)
    # 注意：插入 Ruby 字面量时 Python 的 None 要写成 Ruby 的 nil
    z_lit = "nil" if args.z is None else repr(float(args.z))
    code = "\n".join([
        f"load '{RB}'",
        "m = Sketchup.active_model",
        (f"puts JSON.generate(DshView.set(m, '{args.mode}', {z_lit}))"
         if args.mode != "status"
         else "puts JSON.generate(DshView.status(m))"),
    ])
    try:
        r = c.ruby(code, undo=False, timeout=60)
    except BridgeError as e:
        print(f"❌ [{e.code}] {str(e)[:400]}")
        return 1

    out = str(r.get("output", "")).strip()
    data = None
    idx = out.rfind("{")
    while idx != -1 and data is None:
        try:
            data = json.loads(out[idx:])
        except json.JSONDecodeError:
            idx = out.rfind("{", 0, idx)
    if data is None:
        print("⚠️ 没解析到结果：" + out[:400])
        return 1

    if args.mode == "status":
        print(f"可见 {data['visible']} 个组：{data['visible_names']}")
        print(f"隐藏 {data['hidden']} 个组：{data['hidden_names']}")
    else:
        print(f"视图模式 = {data['mode']}：隐藏 {data['hidden']} 个 / 可见 {data['shown']} 个")
        print(f"  {data['note']}")

    if args.shot:
        print()
        for name, cam in (
            (f"{args.shot}-plan", {"eye": [3000, 4000, 20000], "target": [3000, 4000, 0],
                                   "up": [0, 1, 0], "perspective": False}),
            (f"{args.shot}-34", {"eye": [9500, -8000, 7000], "target": [3000, 4000, 1200],
                                 "up": [0, 0, 1], "perspective": True, "fov": 45}),
        ):
            try:
                s = c.shot(name, width=1400, height=1000, camera=cam, timeout=120)
                print(f"  ✅ {s['path']}")
            except BridgeError as e:
                print(f"  ❌ {name}: [{e.code}] {str(e)[:150]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
