#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""建房间 + 从 DSH 侧指定机位截图 + 量尺寸核对。

流程：清空 → 建 3×4m 房间（墙高2.8m，900×2100mm 门洞）→ 量净空 → 两个机位截图
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sk_client import SC, BridgeError  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> int:
    c = SC(timeout=90)

    print("== 1) 清空为干净基准（保留 Scale Figure 也无妨，一起清掉更干净）")
    try:
        r = c.erase(all_=True, confirm=True)
        print(f"   清掉 {r['erased']} 个顶层实体")
    except BridgeError as e:
        print(f"   ❌ [{e.code}] {str(e)[:200]}")
        return 1

    print()
    print("== 2) 建房间")
    try:
        r = c.run_file(os.path.join(HERE, "build_room.rb"), op_name="DSH 建房间")
        print(f"   ✅ changed={r['changed']}")
        print(f"   delta={r['delta']}")
        for line in str(r.get("output", "")).strip().splitlines():
            print(f"   puts> {line}")
    except BridgeError as e:
        print(f"   ❌ [{e.code}] {str(e)[:600]}")
        return 1

    print()
    print("== 3) 量尺寸核对（用 measure 验证净空是否真是 2800×3800×2800）")
    checks = [
        ("房间净宽 (X)", (100, 2000, 0), (2900, 2000, 0), 2800),
        ("房间净长 (Y)", (1500, 100, 0), (1500, 3900, 0), 3800),
        ("门洞宽度", (1100, 0, 1000), (2000, 0, 1000), 900),
        ("墙高（前墙左垛）", (500, 50, 0), (500, 50, 2800), 2800),
    ]
    for label, a, b, expect in checks:
        try:
            m = c.measure(a, b)
            got = m["distance_mm"]
            flag = "✅" if abs(got - expect) < 1.0 else "⚠️"
            print(f"   {flag} {label}: 实测 {got}mm（期望 {expect}mm）")
        except BridgeError as e:
            print(f"   ❌ {label}: [{e.code}] {str(e)[:150]}")

    print()
    print("== 4) 从 DSH 指定机位截图（3/4 视角，能看见门洞）")
    # 相机在房间前右上方，看向房间内部中心
    cam = {
        "eye": [5200, -4200, 3600],
        "target": [1500, 1800, 1200],
        "up": [0, 0, 1],
        "perspective": True,
        "fov": 45,
    }
    try:
        s = c.shot("room-34", width=1400, height=900, camera=cam, restore=True, timeout=120)
        print(f"   ✅ {s['path']} ({s['bytes']} 字节)")
    except BridgeError as e:
        print(f"   ❌ [{e.code}] {str(e)[:400]}")

    print()
    print("== 5) 再拍一张俯视，方便核对平面布局")
    cam2 = {
        "eye": [1500, 2000, 9000],
        "target": [1500, 2000, 0],
        "up": [0, 1, 0],
        "perspective": True,
        "fov": 40,
    }
    try:
        s = c.shot("room-top", width=1400, height=900, camera=cam2, restore=True, timeout=120)
        print(f"   ✅ {s['path']} ({s['bytes']} 字节)")
    except BridgeError as e:
        print(f"   ❌ [{e.code}] {str(e)[:400]}")

    print()
    print("== 6) 模型概览")
    try:
        i = c.info(scope="top", limit=10)
        print(f"   顶层 {i['counts']['top_level']} | 面 {i['counts']['faces']} | 组 {i['counts']['groups']}")
        print(f"   总范围 {i['model_bbox']['size_mm']} mm")
        for e in i["entities"][:8]:
            print(f"     - {e.get('type')} {e.get('name') or ''} {e.get('size_mm') or ''}")
    except BridgeError as e:
        print(f"   ❌ [{e.code}]")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
