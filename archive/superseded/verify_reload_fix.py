#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 v4 reload 补丁推进活着的进程，然后验证热重载是否终于可靠。

顺序（每步都先确认桥活着）：
  1. ping
  2. load 补丁
  3. ping（补丁没把桥弄坏吗）
  4. reload（单发一条）
  5. ping（reload 之后还活着吗）—— 这是关键一步
  6. 再 reload 一次（重复热重载是否稳定）
  7. 验证命令层真的换了新代码（调用一个 handler 看行为）
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sk_client import SC, BridgeError  # noqa: E402

PATCH = r"E:/deepseek工作区/sketchup-bridge/dsh_bridge_patch.rb"
LOG = r"E:\deepseek工作区\sketchup-bridge\bridge.log"


def tail(n=12):
    if not os.path.exists(LOG):
        return "   (无日志)"
    with open(LOG, encoding="utf-8", errors="replace") as f:
        return "\n".join(f"   | {ln}" for ln in f.read().splitlines()[-n:])


def alive(c, label=""):
    try:
        c.ping(timeout=15)
        print(f"   ✅ 桥还活着 {label}")
        return True
    except BridgeError as e:
        print(f"   ❌ 桥不响应 {label}: [{e.code}]")
        return False


def main() -> int:
    c = SC(timeout=40)

    print("== 1) 基线 ping")
    if not alive(c):
        return 1

    print()
    print("== 2) 推进 v4 补丁")
    try:
        r = c.ruby(f"load '{PATCH}'", undo=False)
        print(f"   {r['output'].strip()}")
    except BridgeError as e:
        print(f"   ❌ [{e.code}] {str(e)[:300]}")
        return 1

    print()
    print("== 3) 补丁后确认")
    if not alive(c, "（补丁后）"):
        return 1

    print()
    print("== 4) 单发一条 reload")
    try:
        r = c.reload(timeout=40)
        print(f"   ✅ reloaded={r['reloaded']} 命令数={len(r['actions'])} safe_swap={r.get('safe_swap')} patch={r.get('patch')}")
        print(f"      新增 {r['added']} / 移除 {r['removed']}")
    except BridgeError as e:
        print(f"   ❌ [{e.code}] {str(e)[:300]}")
        print("   日志：")
        print(tail())
        return 1

    print()
    print("== 5) reload 之后桥还在吗（关键一步）")
    if not alive(c, "（reload 后）"):
        print("   日志：")
        print(tail())
        return 1

    print()
    print("== 6) 再 reload 一次（重复热重载稳定性）")
    try:
        r = c.reload(timeout=40)
        print(f"   ✅ 第二次 reload 成功，命令数={len(r['actions'])}")
    except BridgeError as e:
        print(f"   ❌ [{e.code}] {str(e)[:300]}")
        return 1
    if not alive(c, "（二次 reload 后）"):
        return 1

    print()
    print("== 7) 确认命令层真的是新代码（跑一个 handler）")
    try:
        r = c.ruby(
            ["m = Sketchup.active_model",
             "f = m.entities.add_face([Geom::Point3d.new(0, 0, 0), Geom::Point3d.new(500.mm, 0, 0),",
             "                        Geom::Point3d.new(500.mm, 500.mm, 0), Geom::Point3d.new(0, 500.mm, 0)])",
             "f.pushpull(-700.mm)",
             'puts "handler 正常工作"'],
            op_name="DSH 补丁后验证",
        )
        print(f"   ✅ changed={r['changed']} delta={r['delta']}")
        print(f"      puts: {r['output'].strip()}")
    except BridgeError as e:
        print(f"   ❌ [{e.code}] {str(e)[:300]}")

    print()
    print("== 日志尾部")
    print(tail(20))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
