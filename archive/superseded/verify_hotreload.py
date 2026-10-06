#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""现场修补 + 热重载 + 验证 changed/delta。

流程：
  1. load 热补丁，修好 DshBridge.reload（原版 const_defined? 沿祖先链误判）
  2. 用修好的 reload 热加载新 dsh_handlers.rb（不起重启 SketchUp）
  3. 验证 changed / delta / preview / undo / history 是否说真话

跑法：python verify_hotreload.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sk_client import SC, BridgeError  # noqa: E402

PATCH = r"E:/deepseek工作区/sketchup-bridge/dsh_bridge_patch.rb"


def main() -> int:
    c = SC(timeout=60)

    print("== 0) 先确认桥还活着")
    try:
        p = c.ping()
        print(f"   ✅ 桥 v{p['version']} / SketchUp {p['sketchup']}")
    except BridgeError as e:
        print(f"   ❌ {e}")
        return 1

    print()
    print("== 1) 推送热补丁，修好 reload")
    try:
        r = c.ruby(f"load '{PATCH}'", undo=False, want_values=True)
        print(f"   changed={r['changed']} | puts: {r['output'].strip()}")
        if r.get("values"):
            print(f"   返回值: {list(r['values'].values())}")
    except BridgeError as e:
        print(f"   ❌ {e.code}: {str(e)[:400]}")
        return 1

    print()
    print("== 2) 用补好的 reload 热加载命令层")
    try:
        r = c.reload()
        print(f"   reloaded={r['reloaded']} | 命令数 {len(r['actions'])}")
        print(f"   新增 {r['added']} | 移除 {r['removed']}")
    except BridgeError as e:
        print(f"   ❌ {e.code}: {str(e)[:400]}")
        return 1

    print()
    print("== 3) changed / delta 现在说真话了吗（建一根柱子）")
    try:
        r = c.ruby(
            [
                "m = Sketchup.active_model",
                "e = m.entities",
                "f = e.add_face([Geom::Point3d.new(2000.mm, 0, 0), Geom::Point3d.new(2400.mm, 0, 0),",
                "                Geom::Point3d.new(2400.mm, 400.mm, 0), Geom::Point3d.new(2000.mm, 400.mm, 0)])",
                "f.pushpull(-1600.mm)",
                'g = e.add_group(f); g.name = "DSH-验证柱"',
                'puts "建好 #{g.name}"',
            ],
            op_name="DSH 验证柱",
        )
        print(f"   changed      = {r['changed']}")
        print(f"   delta        = {r['delta']}")
        print(f"   operation    = {r['operation']}")
        print(f"   counts_after = {r['counts_after']}")
        print(f"   puts         = {r['output'].strip()}")
    except BridgeError as e:
        print(f"   ❌ {e.code}: {str(e)[:400]}")

    print()
    print("== 4) preview 干跑（执行后立刻撤销）")
    try:
        r = c.ruby(
            [
                "m = Sketchup.active_model",
                "m.entities.add_circle(Geom::Point3d.new(3000.mm, 0, 0), Geom::Vector3d.new(0, 0, 1), 300.mm)",
            ],
            op_name="DSH 干跑圆",
            preview=True,
        )
        print(f"   changed={r['changed']} | delta={r['delta']}")
        print(f"   preview_undo = {r.get('preview_undo')}")
    except BridgeError as e:
        print(f"   ❌ {e.code}: {str(e)[:300]}")

    print()
    print("== 5) undo 真的能用吗")
    try:
        u = c.undo(1)
        print(f"   undone={u['undone']} | delta={u['delta']}")
    except BridgeError as e:
        print(f"   ❌ {e.code}: {str(e)[:200]}")

    print()
    print("== 6) history 如实报告能力边界")
    try:
        h = c.history()
        ok = [k for k, v in h["available_methods"].items() if v]
        no = [k for k, v in h["available_methods"].items() if not v]
        print(f"   可用   : {ok}")
        print(f"   不可用 : {no}")
        print(f"   当前计数: {h['counts']}")
    except BridgeError as e:
        print(f"   ❌ {e.code}: {str(e)[:200]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
