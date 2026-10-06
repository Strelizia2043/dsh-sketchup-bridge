#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""最终验收：reload 可用 + undo/preview 修好 + 建几何 + 截图。

每一步都先确认桥活着。这次不用重启 SketchUp——命令层走热重载。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sk_client import SC, BridgeError  # noqa: E402

LOG = r"E:\deepseek工作区\sketchup-bridge\bridge.log"
results: list[tuple[str, bool, str]] = []


def tail(n=10):
    if not os.path.exists(LOG):
        return "   (无日志)"
    with open(LOG, encoding="utf-8", errors="replace") as f:
        return "\n".join(f"   | {ln}" for ln in f.read().splitlines()[-n:])


def step(label, fn):
    try:
        detail = fn()
        results.append((label, True, str(detail)[:160]))
        print(f"   ✅ {label}: {detail}")
        return True
    except BridgeError as e:
        results.append((label, False, f"[{e.code}] {str(e)[:160]}"))
        print(f"   ❌ {label}: [{e.code}] {str(e)[:300]}")
        return False
    except Exception as e:  # noqa: BLE001
        results.append((label, False, f"{type(e).__name__}: {e}"))
        print(f"   ❌ {label}: {type(e).__name__}: {e}")
        return False


def main() -> int:
    c = SC(timeout=60)

    print("== 1) 连通性")
    step("ping", lambda: f"v{c.ping()['version']} / SU {c.ping()['sketchup']}")

    print()
    print("== 2) 热重载（把刚修好的 handler 推上去，不重启）")
    step("reload", lambda: f"命令数={len(c.reload()['actions'])} in_place={c.reload().get('in_place')}")
    step("reload 后仍活着", lambda: f"pong={c.ping(timeout=15)['pong']}")

    print()
    print("== 3) 撤销 API 探测（history 应如实报告）")
    def hist():
        h = c.history()
        avail = {k: v for k, v in h["available_methods"].items()}
        assert avail.get("Sketchup.undo") is True, f"Sketchup.undo 应为 True：{avail}"
        assert avail.get("Model#undo") is False, f"Model#undo 应为 False：{avail}"
        return f"Sketchup.undo={avail['Sketchup.undo']} Model#undo={avail['Model#undo']}"
    step("history 探测", hist)

    print()
    print("== 4) 建几何（跨行 Ruby 作为整体发送）")
    def build():
        # pushpull 会让原 face 引用失效（SketchUp 2026 实测），所以成组用新建实体
        code = "\n".join([
            "m = Sketchup.active_model",
            "e = m.entities",
            "pts = [Geom::Point3d.new(0, 0, 0), Geom::Point3d.new(700.mm, 0, 0),",
            "       Geom::Point3d.new(700.mm, 700.mm, 0), Geom::Point3d.new(0, 700.mm, 0)]",
            "e.add_face(pts).pushpull(-1100.mm)",
            "solid = e.to_a.last",
            'g = e.add_group(solid); g.name = "DSH-最终验收块"',
            'puts "建好 #{g.name} 高 1100mm"',
        ])
        r = c.ruby(code, op_name="DSH 最终验收块")
        assert r["changed"] is True, f"changed 应为 True：{r['changed']}"
        assert r["delta"], "delta 不应为空"
        return f"changed={r['changed']} delta={r['delta']} | {r['output'].strip()}"
    step("建几何", build)

    print()
    print("== 5) preview 干跑（这次真的能撤销了吗）")
    def preview():
        r = c.ruby(
            "\n".join([
                "m = Sketchup.active_model",
                "m.entities.add_circle(Geom::Point3d.new(4000.mm, 0, 0), Geom::Vector3d.new(0, 0, 1), 500.mm)",
            ]),
            op_name="DSH 干跑圆", preview=True,
        )
        note = str(r.get("preview_undo"))
        assert "已撤销" in note, f"preview 没能撤销：{note}"
        return f"delta={r['delta']} | {note}"
    step("preview 撤销", preview)

    print()
    print("== 6) 显式 undo 命令")
    def undo_cmd():
        u = c.undo(1)
        assert u["undone"] >= 1 or u["delta"], f"undo 没生效：{u}"
        return f"undone={u['undone']} delta={u['delta']}"
    step("undo", undo_cmd)

    print()
    print("== 7) 截图回传")
    shot = {}
    def take():
        s = c.shot("dsh-final", width=1400, height=900, timeout=120)
        shot.update(s)
        return f"{s['path']} ({s['bytes']} 字节)"
    step("shot", take)

    print()
    print("== 8) 桥日志")
    print(tail(12))

    print()
    print("=" * 64)
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"通过 {passed}/{len(results)} 项")
    for label, ok, detail in results:
        print(f"  {'✅' if ok else '❌'} {label}")
    if shot.get("path"):
        print(f"\n截图：{shot['path']}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
