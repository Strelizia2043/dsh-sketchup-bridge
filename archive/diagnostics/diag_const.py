#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用桥本身测 Ruby 语义：为什么匿名模块里 module_eval 后找不到 ACTIONS 常量。

这是纯语言行为测试，不碰模型，改了也不影响任何东西。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sk_client import SC, BridgeError  # noqa: E402

SNIPPET = r'''
src = <<~RUBY
  ACTIONS = {}
  module_function
  def foo; 1; end
  ACTIONS['a'] = lambda do |x, y|
    foo + x + y
  end
RUBY

lines = []
lines << "src 长度=#{src.length}"

tmp = Module.new
tmp.module_eval(src, "fake.rb", 1)
lines << "A) 匿名模块 module_eval 后:"
lines << "   const_defined?(:ACTIONS,false) = #{tmp.const_defined?(:ACTIONS, false)}"
lines << "   constants = #{tmp.constants.inspect}"
begin
  lines << "   tmp::ACTIONS.keys = #{tmp::ACTIONS.keys.inspect}"
  lines << "   lambda 可调用 = #{tmp::ACTIONS['a'].call(1, 2)}"
rescue => e
  lines << "   取 ACTIONS 失败: #{e.class}: #{e.message}"
end

# 对照实验：不用 heredoc，直接用普通字符串
plain = "ACTIONS = {}\nmodule_function\ndef bar; 2; end\nACTIONS['b'] = lambda { |x, y| bar + x + y }\n"
tmp2 = Module.new
tmp2.module_eval(plain, "plain.rb", 1)
lines << "B) 普通字符串 module_eval 后:"
lines << "   const_defined? = #{tmp2.const_defined?(:ACTIONS, false)}"
lines << "   tmp2::ACTIONS.keys = #{(tmp2::ACTIONS.keys rescue 'FAIL')}"

# 对照实验：module_exec（块形式）
tmp3 = Module.new
tmp3.module_eval do
  ACTIONS = { 'c' => lambda { |x, y| x + y } }
end
lines << "C) module_eval 块形式: const_defined? = #{tmp3.const_defined?(:ACTIONS, false)}"

puts lines.join("\n")
'''

CODE = [
    "lines_out = []",
    "begin",
    SNIPPET,
    "rescue Exception => e",
    "  puts 'ERR ' + e.class.to_s + ': ' + e.message",
    "end",
]


def main() -> int:
    c = SC(timeout=30)
    try:
        r = c.ruby(SNIPPET, undo=False)
        print(r["output"].strip())
    except BridgeError as e:
        print(f"❌ [{e.code}] {str(e)[:500]}")
        return 1

    print()
    print("── 桥还在吗：", end="")
    try:
        c.ping(timeout=15)
        print("✅ 在")
    except BridgeError:
        print("❌ 死了")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
