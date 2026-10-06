#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工具定位器 —— 给所有测试和脚本用。

**为什么需要它**：重组目录后脚本从平铺根目录搬到了
`tools/cad|img|build/`，而测试里到处写着

    TOOL = os.path.join(HERE, "cad_to_plan.py")     # ❌ 搬完就找不到

修一处漏一处。所以统一成 `tool("cad_to_plan.py")`：
先找根目录，再找各 tools 子目录，返回**绝对路径**（找不到返回 None）。

踩过：找不到脚本时 python 只打印 `can't open file` 并返回退出码 2，
**不产生 Traceback** —— 所以"只看有没有崩溃"的断言会把它判成通过。
用本模块能明确区分"脚本不存在"和"脚本运行出错"。
"""
from __future__ import annotations

import os

# 各工具子目录（顺序即查找优先级）
SUBDIRS = ('', 'tools/cad', 'tools/img', 'tools/build', 'tests')
MARK = '# --- DSH 路径修正（重组后自动加，见 fix_imports.py）'


def find_root(start: str | None = None) -> str:
    """向上找到含 sk_client.py 的那一层（工作区根目录）。"""
    cur = os.path.dirname(os.path.abspath(start or __file__))
    for _ in range(5):
        if os.path.exists(os.path.join(cur, 'sk_client.py')):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return os.path.dirname(os.path.abspath(start or __file__))


ROOT = find_root()


def tool(name: str) -> str | None:
    """按名字找脚本，返回绝对路径；找不到返回 None。"""
    for sub in SUBDIRS:
        p = os.path.normpath(os.path.join(ROOT, sub, name))
        if os.path.exists(p):
            return p
    return None


def tool_rel(name: str) -> str:
    """找脚本并返回**相对 ROOT 的路径**（给 subprocess 用，配 cwd=ROOT）。"""
    p = tool(name)
    return os.path.relpath(p, ROOT).replace('\\', '/') if p else name


def artifact(*parts: str) -> str:
    """产物的绝对路径（产物都落在根目录下，如 cad/xxx.json、models/xxx.skp）。"""
    return os.path.normpath(os.path.join(ROOT, *parts))


__all__ = ['ROOT', 'SUBDIRS', 'find_root', 'tool', 'tool_rel', 'artifact']
