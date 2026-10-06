#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用桥本身测两件事（都是刚暴露出来的真问题）：

A) 能不能把多行 Ruby 当**一个整体** eval —— 现在逐行 eval 导致跨行表达式必然语法错误
B) Sketchup::Model 到底有没有 undo/redo —— preview 和 undo 命令都依赖它，
   实测报 `undefined method 'undo'`
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sk_client import SC, BridgeError  # noqa: E402

PROBE = r'''
m = Sketchup.active_model
found = []
found << "undo=#{m.respond_to?(:undo)}"
found << "redo=#{m.respond_to?(:redo)}"
found << "undo_stack_length=#{m.respond_to?(:undo_stack_length)}"

# 看看 Sketchup::Model 上跟 undo 沾边的方法名
names = m.methods.map(&:to_s).grep(/undo|redo|operation/i).sort
found << "相关方法名=#{names.inspect}"

# 常量层面呢？
found << "Model 实例方法里含 undo 的=#{Sketchup::Model.instance_methods.grep(/undo/i).inspect}"
found << "Sketchup 模块里的=#{Sketchup.methods.grep(/undo/i).inspect}"
found << "UI 里的=#{UI.methods.grep(/undo/i).inspect}"

# 多行整体 eval 试验：这段跨两行，逐行发必然炸
src = "arr = [1, 2,\n       3]\narr.sum"
found << "跨行 eval 结果=#{eval(src)}"

puts found.join("\n")
'''

try:
    import ripper  # noqa: F401
except ImportError:
    pass


def main() -> int:
    c = SC(timeout=40)
    try:
        r = c.ruby(PROBE, undo=False)
        print(r["output"].strip())
    except BridgeError as e:
        print(f"❌ [{e.code}] {str(e)[:400]}")
        return 1

    print()
    print("-- 桥还在吗：", end="")
    try:
        c.ping(timeout=15)
        print("✅ 在")
    except BridgeError:
        print("❌ 死了")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
