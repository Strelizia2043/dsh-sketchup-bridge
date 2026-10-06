#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端验收脚本：info -> 建几何 -> 截图 -> 撤销历史。

跑法（SketchUp 必须开着、桥必须在跑）：
    python verify_e2e.py
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sk_client import SC, BridgeError  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def step(title):
    print()
    print(f"== {title}")


def main() -> int:
    c = SC(timeout=60)

    step("0) ping")
    try:
        p = c.ping()
        print(f"   ✅ 桥 v{p['version']} / SketchUp {p['sketchup']} / Ruby {p['ruby']}")
        print(f"   {len(p['actions'])} 条命令")
    except BridgeError as e:
        print(f"   ❌ {e}")
        return 1

    step("1) 模型现状")
    try:
        i = c.info(scope="top", limit=10)
        ct = i["counts"]
        print(f"   顶层实体 {ct['top_level']} | 面 {ct['faces']} | 组 {ct['groups']} "
              f"| 组件 {ct['components']} | 定义 {ct['definitions']}")
        if i.get("model_bbox"):
            print(f"   模型范围(mm) {i['model_bbox']['size_mm']}")
        print(f"   Tag {i['lists']['tags'][:8]}")
        for e in i["entities"][:6]:
            print(f"     - {e.get('type')} {e.get('name') or ''} {e.get('size_mm') or ''}")
    except BridgeError as e:
        print(f"   ❌ info: {e.code} | {str(e)[:200]}")

    step("2) 让 DSH 自己建几何（运行 demo_build.rb）")
    try:
        r = c.run_file(os.path.join(HERE, "demo_build.rb"), op_name="DSH 建三根柱子")
        print(f"   changed={r['changed']} | 耗时 {r['_ms']}ms | 顶层实体 {r['model_entities']}")
        for line in str(r.get("output", "")).strip().splitlines():
            print(f"   puts> {line}")
    except BridgeError as e:
        print(f"   ❌ eval: {e.code}\n{str(e)[:600]}")

    step("3) 从 DSH 侧截图")
    shot = None
    try:
        s = c.shot("dsh-first-look", width=1400, height=900)
        shot = s.get("path")
        print(f"   {shot}")
        print(f"   {s.get('bytes')} 字节 | 相机(mm) {s.get('camera_used_mm')}")
    except BridgeError as e:
        print(f"   ❌ shot: {e.code}\n{str(e)[:600]}")

    step("4) 撤销历史（确认我的操作是一步）")
    try:
        h = c.history(limit=6)
        print(f"   撤销栈长度 {h['undo_stack_length']}")
        print(f"   最近操作 {h['recent']}")
    except BridgeError as e:
        print(f"   ❌ history: {e.code}")

    print()
    print("=" * 60)
    if shot and os.path.exists(shot):
        print(f"截图就绪，可供 DSH 查看：{shot}")
        return 0
    print("没有拿到截图，需要继续排查。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
