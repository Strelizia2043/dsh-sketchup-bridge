#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看版本。**唯一权威是 version.json**，别的地方不许写死。

    python version.py            # 概况
    python version.py --all      # 含组件与测试明细
    python version.py --bump patch|minor|major   # 升版本并写回

为什么要有这个脚本：在此之前，"当前第几版"这个问题**给不出可信答案**——
`dsh_bridge.rb` 里写死 `VERSION='1.0.0'` 而从没更新过（实际至少改过 5 版），
文档里同时存在「最后更新 Round 9」和「Round 34」两种说法。
一份权威 + 一个能问的入口，比让每个文件各写一个版本号可靠。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VJSON = os.path.join(HERE, "version.json")


def load() -> dict:
    with open(VJSON, encoding="utf-8") as f:
        return json.load(f)


def bump(v: str, kind: str) -> str:
    a, b, c = (int(x) for x in v.split("."))
    if kind == "major":
        return f"{a + 1}.0.0"
    if kind == "minor":
        return f"{a}.{b + 1}.0"
    return f"{a}.{b}.{c + 1}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="含组件与测试明细")
    ap.add_argument("--bump", choices=["major", "minor", "patch"])
    a = ap.parse_args()

    d = load()
    p = d["project"]

    if a.bump:
        old = p["version"]
        new = bump(old, a.bump)
        p["version"] = new
        with open(VJSON, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        print(f"项目版本 {old} → {new}")
        print("（记得在 project.version_note 里补一行说明这次改了什么）")
        return 0

    print("=" * 68)
    print(f"  {p['name']}   v{p['version']}")
    print("=" * 68)
    for line in p.get("version_note") or []:
        print(f"    {line}")
    print()
    print(f"    轮次：第 {d['rounds']['current']} 轮（与版本号正交）")
    print(f"    版本管理：{p.get('vcs')}")
    print()

    if not a.all:
        print("    加 --all 看组件与测试明细")
        return 0

    print("── 组件 ──────────────────────────────────────────────")
    for c in d["components"]:
        print(f"    {c['name']:<24} v{c['version']:<8} {c['role']}")
    print()
    print("── 测试 ──────────────────────────────────────────────")
    tot = 0
    for t in d["tests"]:
        n = t["items"]
        tot += n
        badge = f"{n} 项" if n else "数量随模型"
        print(f"    {t['name']:<24} {badge:<12} {t['covers']}")
    print(f"    {'':<24} {'合计 %d 项' % tot if tot else ''}")
    print()
    print("── 组件备注 ──────────────────────────────────────────")
    for c in d["components"]:
        if c.get("note"):
            print(f"    · {c['name']}：{c['note']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
