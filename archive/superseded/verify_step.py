#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分步验收：先只 ping；确认活着之后再单发一条 reload；最后核心功能 + 截图。

设计原则：**一次只发一条命令，每一步都先确认桥还活着。**
上一轮我在同一个调用里连发两条 reload，可能就是触发崩溃的原因。

跑法：python verify_step.py [step]
    step = 1 ping / 2 reload / 3 core / all（默认 all）
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sk_client import SC, BridgeError  # noqa: E402

LOG = r"E:\deepseek工作区\sketchup-bridge\bridge.log"


def tail_log(n=25):
    if not os.path.exists(LOG):
        return "   (还没有日志文件)"
    with open(LOG, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    return "\n".join(f"   | {ln}" for ln in lines[-n:])


def alive(c) -> bool:
    try:
        c.ping(timeout=15)
        return True
    except BridgeError as e:
        print(f"   ❌ 桥不响应: [{e.code}]")
        return False


def main() -> int:
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    c = SC(timeout=30)

    print("=== 步骤 1：桥活着吗（只发一条 ping）")
    try:
        p = c.ping(timeout=15)
        print(f"   ✅ 桥 v{p['version']} / SketchUp {p['sketchup']} / Ruby {p['ruby']} / {len(p['actions'])} 条命令")
    except BridgeError as e:
        print(f"   ❌ [{e.code}] {str(e)[:250]}")
        print("   日志尾部：")
        print(tail_log())
        return 1

    if step in ("2", "all"):
        print()
        print("=== 步骤 2：单发一条 reload（发完立刻确认桥还活着）")
        try:
            r = c.reload(timeout=30)
            print(f"   ✅ reloaded={r['reloaded']} 命令数={len(r['actions'])} "
                  f"safe_swap={r.get('safe_swap')}")
            print(f"      新增 {r['added']} / 移除 {r['removed']}")
        except BridgeError as e:
            print(f"   ❌ [{e.code}] {str(e)[:250]}")
            print("   日志尾部（看崩在哪条命令）：")
            print(tail_log())
            return 1

        time.sleep(0.5)
        print("   ── reload 之后再确认一次：", end="")
        print("✅ 桥还在" if alive(c) else "❌ 桥死了")

        print("   日志尾部：")
        print(tail_log(14))

    if step in ("3", "all"):
        print()
        print("=== 步骤 3：核心功能（建几何 + changed/delta）")
        try:
            r = c.ruby(
                [
                    "m = Sketchup.active_model",
                    "e = m.entities",
                    "f = e.add_face([Geom::Point3d.new(0, 0, 0), Geom::Point3d.new(600.mm, 0, 0),",
                    "                Geom::Point3d.new(600.mm, 600.mm, 0), Geom::Point3d.new(0, 600.mm, 0)])",
                    "f.pushpull(-900.mm)",
                    'g = e.add_group(f); g.name = "DSH-验收块"',
                    'puts "建好 #{g.name}"',
                ],
                op_name="DSH 验收块",
            )
            ok = r["changed"] is True and bool(r["delta"])
            print(f"   {'✅' if ok else '❌'} changed={r['changed']} delta={r['delta']}")
            print(f"      operation={r['operation']}")
            print(f"      puts: {r['output'].strip()}")
        except BridgeError as e:
            print(f"   ❌ [{e.code}] {str(e)[:300]}")

        print()
        print("=== 步骤 4：preview 干跑")
        try:
            r = c.ruby(
                ["m = Sketchup.active_model",
                 "m.entities.add_circle(Geom::Point3d.new(3000.mm, 0, 0), Geom::Vector3d.new(0, 0, 1), 400.mm)"],
                op_name="DSH 干跑圆", preview=True,
            )
            print(f"   ✅ changed={r['changed']} delta={r['delta']} | {r.get('preview_undo')}")
        except BridgeError as e:
            print(f"   ❌ [{e.code}] {str(e)[:300]}")

        print()
        print("=== 步骤 5：截图回传")
        try:
            s = c.shot("dsh-verified", width=1400, height=900, timeout=120)
            print(f"   ✅ {s['path']} ({s['bytes']} 字节)")
        except BridgeError as e:
            print(f"   ❌ [{e.code}] {str(e)[:300]}")

    print()
    print("=== 桥日志（最近 20 条）")
    print(tail_log(20))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
