#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""干净的全流程验收：清空 → 建方块 → 截图 → 撤销 → 再截图。

设计要点（都是前面踩坑换来的）：
  * 每步之间都确认桥还活着
  * 跨行 Ruby 作为一个整体发送（不拆成多条——拆开必然语法错误）
  * 建几何时**先记录 face 的 entityID**，因为 pushpull 之后原 face 引用可能失效
    （实测报过 `TypeError: reference to deleted Entity`）
  * 用截图做视觉确认，而不是只信 changed/delta
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sk_client import SC, BridgeError  # noqa: E402


def alive(c, label=""):
    try:
        c.ping(timeout=15)
        print(f"   ✅ 桥活着 {label}")
        return True
    except BridgeError as e:
        print(f"   ❌ 桥不响应 {label}: [{e.code}]")
        return False


BUILD = "\n".join([
    "m = Sketchup.active_model",
    "e = m.entities",
    "pts = [Geom::Point3d.new(0, 0, 0), Geom::Point3d.new(1000.mm, 0, 0),",
    "       Geom::Point3d.new(1000.mm, 1000.mm, 0), Geom::Point3d.new(0, 1000.mm, 0)]",
    # 注意：SketchUp 2026 的 pushpull 会让原 face 引用失效
    # （实测 add_group(原 face) 报 `TypeError: reference to deleted Entity`），
    # 所以成组要用**新建的实体**，不要复用 pushpull 之前的引用。
    "e.add_face(pts).pushpull(-1000.mm)",
    "solid = e.to_a.last",
    'g = e.add_group(solid); g.name = "DSH-干净验收块"',
    "m.active_view.zoom_extents",
    'puts "建好 #{g.name}，顶层实体 #{e.length}"',
])


def main() -> int:
    c = SC(timeout=60)

    print("== 1) 连通性")
    if not alive(c):
        return 1

    print()
    print("== 2) 清空模型（一步，可撤销）")
    try:
        r = c.erase(all_=True, confirm=True)
        print(f"   清掉 {r['erased']} 个顶层实体，delta={r['delta']}")
    except BridgeError as e:
        print(f"   ❌ [{e.code}] {str(e)[:250]}")
        return 1
    time.sleep(0.4)

    print()
    print("== 3) 建一个 1000mm 方块")
    try:
        r = c.ruby(BUILD, op_name="DSH 干净验收块")
        print(f"   ✅ changed={r['changed']} delta={r['delta']}")
        print(f"      {r['output'].strip()}")
    except BridgeError as e:
        print(f"   ❌ [{e.code}] {str(e)[:400]}")
        return 1

    print()
    print("== 4) 截图（应该只有方块 + Scale Figure）")
    try:
        s = c.shot("clean-1-built", width=1200, height=800, timeout=120)
        print(f"   ✅ {s['path']}")
    except BridgeError as e:
        print(f"   ❌ [{e.code}] {str(e)[:250]}")

    print()
    print("== 5) 撤销一步，再截图（方块应该消失）")
    try:
        u = c.undo(1)
        print(f"   undone={u['undone']} delta={u['delta']}")
    except BridgeError as e:
        print(f"   ❌ [{e.code}] {str(e)[:250]}")
    time.sleep(0.4)
    try:
        s2 = c.shot("clean-2-undone", width=1200, height=800, timeout=120)
        print(f"   ✅ {s2['path']}")
    except BridgeError as e:
        print(f"   ❌ [{e.code}] {str(e)[:250]}")

    print()
    print("== 6) 重做回来，确认 redo 也可用")
    try:
        rd = c.redo(1)
        print(f"   redone={rd['redone']} delta={rd['delta']}")
    except BridgeError as e:
        print(f"   ⚠️ redo 不可用: [{e.code}] {str(e)[:150]}")

    print()
    if not alive(c, "（全流程结束）"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
