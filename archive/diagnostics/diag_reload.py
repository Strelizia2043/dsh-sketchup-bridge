#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reload 断连的稳健诊断：每一步单独发、单独看状态，用 Ruby rescue 抓真实报错。"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sk_client import SC, BridgeError  # noqa: E402


def show(label, fn):
    try:
        print(f"{label}: {fn()}")
    except BridgeError as e:
        print(f"{label}: ❌ [{e.code}] {str(e)[:220]}")


def main() -> int:
    c = SC(timeout=25)

    print("== 0) 基线")
    show("ping", lambda: c.ping()["version"])
    show("status", lambda: {k: v for k, v in c.status().items()
                            if k in ("requests", "served", "failed", "last_action", "last_error")})

    print()
    print("== 1) reload 内部到底哪一步炸（用 Ruby rescue 抓）")
    ruby = "\n".join([
        "begin",
        "  path = 'E:/deepseek工作区/sketchup-bridge/dsh_handlers.rb'",
        "  src = File.read(path)",
        "  puts 'a) 读到文件 ' + src.length.to_s + ' 字符'",
        "  had = DshBridge.const_defined?(:Handlers, false)",
        "  puts 'b) const_defined?(false) = ' + had.to_s",
        "  puts 'c) 祖先链误判检查 const_defined?() = ' + DshBridge.const_defined?(:Handlers).to_s",
        "  old = had ? DshBridge::Handlers::ACTIONS.keys.sort : []",
        "  puts 'd) 旧命令数 = ' + old.length.to_s",
        "  DshBridge.send(:remove_const, :Handlers) if had",
        "  puts 'e) remove_const 完成'",
        "  DshBridge.module_eval(src, path, 1)",
        "  puts 'f) module_eval 完成，新命令数 = ' + DshBridge::Handlers::ACTIONS.length.to_s",
        "rescue Exception => e",
        "  puts 'ERR ' + e.class.to_s + ': ' + e.message",
        "  puts (e.backtrace || []).reject { |l| l.include?('RubyStdLib') }.first(8).join(\" | \")",
        "end",
    ])
    show("step-trace", lambda: "\n     ".join(c.ruby(ruby, undo=False)["output"].strip().splitlines()))

    print()
    print("== 2) 炸完之后桥还在吗")
    show("status", lambda: {k: v for k, v in c.status().items()
                            if k in ("requests", "served", "failed", "last_action", "last_error")})
    show("ping", lambda: c.ping()["version"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
