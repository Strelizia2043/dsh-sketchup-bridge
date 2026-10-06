#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""桥协议的离线自测——**不需要 SketchUp**。

用一个假服务器完全模仿桥的行为（换行分隔 JSON、单客户端、按行回传），
把客户端的每条路径都过一遍：正常、鉴权失败、分片到达、连接被关闭、
超时、未知命令、中文往返、大 payload。

跑法：
    python test_bridge_protocol.py
"""

from __future__ import annotations

# --- DSH 路径修正（重组后自动加，见 fix_imports.py）
def _dsh_bootstrap():
    """把依赖目录加进 sys.path（重组目录后必需）。

    ⚠️ 两个坑：
      1. 不能依赖模块级的 `import os` —— 本函数在文件顶部就被调用，
         那时 `import os` 还没执行（第一版栽在这：NameError: name 'os' is not defined）。
         所以在**函数体内** import。
      2. 不能假设 `os.path.dirname(__file__)` 就是依赖所在目录：
         脚本移到 tools/ 子目录后，依赖（sk_client.py / version.json）在**根目录**。
         所以要逐级上溯，找到含 sk_client.py 的那一层。
    """
    import os.path as _op
    import sys as _sys
    _cur = _op.dirname(_op.abspath(__file__))
    for _ in range(5):
        if _op.exists(_op.join(_cur, 'sk_client.py')):
            break
        _parent = _op.dirname(_cur)
        if _parent == _cur:
            break
        _cur = _parent
    for _d in ['.', 'tools/cad', 'tools/img', 'tools/build']:
        _p = _op.normpath(_op.join(_cur, _d))
        if _p not in _sys.path:
            _sys.path.insert(0, _p)


_dsh_bootstrap()

import json
import socket
import sys
import threading
import time
import unittest

# 工作区根目录：从本文件位置向上找含 sk_client.py 的那一层。
# **不写死路径** —— 原来这里是 r"E:\deepseek工作区\sketchup-bridge"，
# 换机器、换目录就废了。上面的 _dsh_bootstrap() 已把根目录加进 sys.path，
# 这里再算一个常量给下面的"文件检查"测试用。
def _dsh_root():
    # 注意：`import os.path as _o` 之后 `_o` **就是** path 模块本身，
    # 不能再写 `_o.path.abspath` —— 那是 ntpath.path，不存在（我刚踩过）。
    import os.path as _o
    _c = _o.dirname(_o.abspath(__file__))
    for _ in range(5):
        if _o.exists(_o.join(_c, 'sk_client.py')):
            return _c
        _p = _o.dirname(_c)
        if _p == _c:
            break
        _c = _p
    return _o.dirname(_o.abspath(__file__))


_DSH_ROOT = _dsh_root()

from sk_client import SC, BridgeError  # noqa: E402

# ⚠️ 这里**不能写死 token**。
#
# 原来写的是 "dsh-su-2026"，而客户端现在从 dsh_workspace.json 读 token
# （首次运行由桥随机生成）—— 于是假桥和客户端用不同的串，**整组测试报 auth 失败**。
# 症状看着像"token 机制坏了"，其实是测试没跟上机制变化。
#
# 现在直接复用客户端解析到的值。这一条**必须是同一个来源**：
# 第二版我在这里另写了一个 "dsh-test-token-0000000000" 作兜底，
# 而客户端的兜底是另一个串 —— 结果**全新克隆**（没有配置文件）跑测试时
# 又是 2 失败 8 错误。所以兜底值统一由 sk_client.PLACEHOLDER_TOKEN 提供。
import sk_client  # noqa: E402

TOKEN = sk_client.TOKEN


class FakeBridge(threading.Thread):
    """假桥。mode 控制异常行为。"""

    def __init__(self, mode: str = "normal", token: str = TOKEN):
        super().__init__(daemon=True)
        self.mode = mode
        self.token = token
        self.received: list[dict] = []
        self.raw_lines: list[bytes] = []
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(8)
        self.port = self.srv.getsockname()[1]
        self._stop = False

    def run(self):
        while not self._stop:
            try:
                conn, _ = self.srv.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn: socket.socket):
        try:
            conn.settimeout(5)
            buf = b""
            while b"\n" not in buf:
                chunk = conn.recv(65536)
                if not chunk:
                    return
                buf += chunk
            line, _, rest = buf.partition(b"\n")
            self.raw_lines.append(line)

            if self.mode == "close":
                conn.close()
                return
            if self.mode == "slow":
                time.sleep(30.0)  # 远超任何测试超时，确保"该超时就一定超时"

            req = json.loads(line.decode("utf-8"))
            self.received.append(req)

            if self.mode == "garbage":
                conn.sendall(b"this is not json\n")
                return

            payload = self._handle(req)
            data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")

            if self.mode == "chunked":
                for i in range(0, len(data), 3):  # 切成 3 字节一片，考验客户端缓冲
                    conn.sendall(data[i:i + 3])
                    time.sleep(0.001)
            else:
                conn.sendall(data)
            _ = rest
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _handle(self, req: dict) -> dict:
        if req.get("token") != self.token:
            return {"id": req.get("id"), "ok": False,
                    "error": {"code": "auth", "message": "token 不正确"}}
        action = req.get("action")
        args = req.get("args") or {}
        if action == "ping":
            return {"id": req["id"], "ok": True,
                    "result": {"data": {"pong": True, "version": "1.0.0", "ruby": "3.2.2",
                                        "sketchup": "26.0.429", "actions": ["eval", "info", "ping"]},
                               "ms": 1.2}}
        if action == "eval":
            code = args.get("code")
            if isinstance(code, list) and any("boom" in str(c) for c in code):
                return {"id": req["id"], "ok": False,
                        "error": {"code": "ruby_error",
                                  "message": "RuntimeError: boom\n(dsh(0)):1:in `eval'"}}
            out = ""
            if isinstance(code, list) and any("puts" in str(c) for c in code):
                out = "你好，SketchUp —— ünïcode ✓\n"
            if args.get("big"):
                out = "你好，SketchUp —— ünïcode ✓\n" * 200
            return {"id": req["id"], "ok": True,
                    "result": {"data": {"ms": 3.5, "changed": True, "preview": False,
                                        "output": out, "model_entities": 7, "selection": 0},
                               "ms": 4.0}}
        if action == "reload":
            return {"id": req["id"], "ok": True,
                    "result": {"data": {"reloaded": True, "actions": ["eval", "info", "ping"],
                                        "added": [], "removed": []}, "ms": 2.0}}
        if action == "status":
            return {"id": req["id"], "ok": True,
                    "result": {"data": {"version": "1.0.0", "port": self.port, "client": True},
                               "ms": 0.5}}
        return {"id": req.get("id"), "ok": False,
                "error": {"code": "unknown_action", "message": f"未知命令 {action!r}"}}

    def stop(self):
        self._stop = True
        try:
            self.srv.close()
        except OSError:
            pass


class TestProtocol(unittest.TestCase):
    def setUp(self):
        self.bridge = FakeBridge()
        self.bridge.start()
        time.sleep(0.05)
        self.c = SC(port=self.bridge.port, timeout=5.0)

    def tearDown(self):
        self.bridge.stop()

    # ---------------------------------------------------------- 正常路径

    def test_ping(self):
        r = self.c.ping()
        self.assertTrue(r["pong"])
        self.assertEqual(r["sketchup"], "26.0.429")

    def test_request_shape(self):
        """客户端必须发一行、以换行结尾、带 token 和自增 id。"""
        self.c.ping()
        self.c.ping()
        lines = self.bridge.raw_lines
        self.assertEqual(len(lines), 2)
        self.assertFalse(lines[0].endswith(b"\r"))
        self.assertFalse(lines[0].endswith(b" "))
        reqs = self.bridge.received
        self.assertEqual(reqs[0]["token"], TOKEN)
        self.assertNotEqual(reqs[0]["id"], reqs[1]["id"])

    def test_ruby_output_and_unicode(self):
        r = self.c.ruby('puts "你好，SketchUp —— ünïcode ✓"')
        self.assertIn("你好，SketchUp", r["output"])
        self.assertIn("ünïcode", r["output"])
        self.assertTrue(r["changed"])
        self.assertIsNotNone(r["_ms"])

    def test_ruby_accepts_string_and_list(self):
        r1 = self.c.ruby("a = 1")
        self.assertIn("output", r1)
        r2 = self.c.ruby(["a = 1", "b = 2"])
        self.assertIn("output", r2)
        sent = self.bridge.received[-1]["args"]["code"]
        self.assertEqual(sent, ["a = 1", "b = 2"])

    def test_big_payload(self):
        """大 payload 必须完整往返（假服务器见 args.big 就吐 200 行）。"""
        r = self.c.call("eval", {"code": ["1"], "big": True})
        self.assertIn("output", r)
        self.assertGreater(len(r["output"]), 1000)
        self.assertEqual(r["output"].count("你好，SketchUp"), 200)

    def test_chunked_reply(self):
        """回传被切成 3 字节一片也必须能正确拼回来。"""
        self.bridge.mode = "chunked"
        r = self.c.ping()
        self.assertTrue(r["pong"])

    def test_reload(self):
        r = self.c.reload()
        self.assertTrue(r["reloaded"])
        self.assertEqual(r["added"], [])

    def test_status(self):
        r = self.c.status()
        self.assertEqual(r["version"], "1.0.0")

    # ---------------------------------------------------------- 错误路径

    def test_bad_token(self):
        c = SC(port=self.bridge.port, token="wrong-token", timeout=5.0)
        with self.assertRaises(BridgeError) as cm:
            c.ping()
        self.assertEqual(cm.exception.code, "auth")

    def test_unknown_action(self):
        with self.assertRaises(BridgeError) as cm:
            self.c.call("nope")
        self.assertEqual(cm.exception.code, "unknown_action")
        self.assertIn("nope", cm.exception.message)

    def test_ruby_error_is_surfaced(self):
        with self.assertRaises(BridgeError) as cm:
            self.c.ruby("boom")
        self.assertEqual(cm.exception.code, "ruby_error")
        self.assertIn("RuntimeError", cm.exception.message)

    def test_connection_refused(self):
        c = SC(port=1, timeout=2.0)  # 1 号端口必然连不上
        with self.assertRaises(BridgeError) as cm:
            c.ping()
        self.assertEqual(cm.exception.code, "connect")
        self.assertIn("SketchUp", cm.exception.message)

    def test_connection_closed_mid_command(self):
        b = FakeBridge(mode="close")
        b.start()
        time.sleep(0.05)
        c = SC(port=b.port, timeout=3.0)
        with self.assertRaises(BridgeError) as cm:
            c.ruby("something")
        self.assertEqual(cm.exception.code, "closed")
        b.stop()

    def test_timeout(self):
        b = FakeBridge(mode="slow")
        b.start()
        time.sleep(0.05)
        c = SC(port=b.port, timeout=0.4)
        with self.assertRaises(BridgeError) as cm:
            c.ping()
        self.assertEqual(cm.exception.code, "timeout")
        b.stop()

    def test_convenience_wrappers_do_not_override_timeout(self):
        """回归测试：便利方法曾经硬写超时值，把构造函数配的超时盖掉了。

        症状是"配置的超时形同虚设"，卡住时要干等默认的十几秒——这会直接破坏
        "操作顺手"这个目标。所以这里盯死：所有便利方法都必须透传 self.timeout。
        """
        b = FakeBridge(mode="slow")
        b.start()
        time.sleep(0.05)
        c = SC(port=b.port, timeout=0.4)
        for name, invoke in (
            ("ping", lambda: c.ping()),
            ("status", lambda: c.status()),
            ("info", lambda: c.info()),
            ("ruby", lambda: c.ruby("1 + 1")),
            ("history", lambda: c.history()),
            ("reload", lambda: c.reload()),
        ):
            t0 = time.time()
            with self.assertRaises(BridgeError) as cm:
                invoke()
            dt = time.time() - t0
            self.assertEqual(cm.exception.code, "timeout", f"{name} 没有按配置超时")
            self.assertLess(dt, 2.0, f"{name} 等了 {dt:.1f} 秒，说明内部覆盖了配置的超时")
        b.stop()

    def test_garbage_reply(self):
        b = FakeBridge(mode="garbage")
        b.start()
        time.sleep(0.05)
        c = SC(port=b.port, timeout=3.0)
        with self.assertRaises(BridgeError) as cm:
            c.ping()
        self.assertEqual(cm.exception.code, "bad_reply")
        b.stop()


class TestNoSketchUpRequired(unittest.TestCase):
    """这些是不依赖桥的纯逻辑检查。"""

    def test_latest_shot_helper(self):
        import os
        from sk_client import latest_shot
        p = latest_shot(os.path.join(_DSH_ROOT, "shots"))
        self.assertTrue(p is None or p.lower().endswith((".png", ".jpg")))

    def test_ruby_files_are_ascii_safe_utf8(self):
        """桥的四个 .rb 必须是合法 UTF-8（Ruby 会按 magic comment 解析）。"""
        import os
        # .rb 文件现在在 dsh_bridge/ 子目录（装机包）里
        base = os.path.join(_DSH_ROOT, "dsh_bridge")
        for name in ("dsh_bridge.rb", "dsh_handlers.rb", "dsh_loader.rb", "dsh_parts.rb"):
            path = os.path.join(base, name)
            with open(path, "rb") as f:
                raw = f.read()
            raw.decode("utf-8")  # 解码失败会直接抛
            # ⚠️ 判据要**容忍 CRLF**。
            # 原来只查 b"end\n"，而手工程序编辑（某些编辑器/工具）会把文件写成
            # CRLF，于是这条检查报"不完整"——**是检查太脆，不是文件坏了**。
            # Ruby 解析 CRLF 完全没问题，所以这里两边都接受；
            # 真正要防的是"写入被截断"，那表现为**结尾没有 end**。
            text = raw.decode("utf-8")
            code = [l for l in text.splitlines()
                    if l.strip() and not l.strip().startswith("#")]
            self.assertTrue(code, f"{name} 是空的")
            self.assertEqual(
                code[-1].strip(), "end",
                f"{name} 最后一行不是 end，而是 {code[-1].strip()[:50]}（疑似被截断）")

    def test_bridge_does_not_shutdown_write_side(self):
        """回归测试：桥不能在 close 之前 shutdown(SHUT_WR)。

        Windows 上"先 shutdown 再 close"、而对端还有未读数据时，内核发的是 RST 而不是
        FIN，会把刚写出去的回包丢掉。症状是桥"每连必断、客户端 recv 立刻拿到 b''"。
        我加过一次、当场把桥弄瘫，所以这里钉死它。
        """
        import os
        path = os.path.join(_DSH_ROOT, "dsh_bridge", "dsh_bridge.rb")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        code_lines = [
            ln for ln in src.splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        code = "\n".join(code_lines)
        self.assertNotIn(
            "shutdown", code,
            "dsh_bridge.rb 里出现了 shutdown 调用——它会让回包被 RST 丢掉，必须只用 close",
        )

    def test_bridge_has_idle_reclaim(self):
        """回归测试：必须有空闲回收，否则一条残骸连接会堵死整个桥。"""
        import os
        path = os.path.join(_DSH_ROOT, "dsh_bridge", "dsh_bridge.rb")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        self.assertIn("IDLE_TIMEOUT", src)
        self.assertIn("close_client", src)
        self.assertIn("const_defined?(:Handlers, false)", src)

    def test_ruby_files_are_complete(self):
        """结构完整性检查——不数 end，改验"关键定义在不在"。

        我先后写过两版"数 end 是否配平"，都因为去注释/去字符串的正则不可靠而虚报
        （Ruby 字符串与注释里到处是撇号和插值）。所以放弃猜语法，改成三条不会误报的检查：
          1. UTF-8 可解码
          2. 文件以 end 收尾（写入被截断时这是最先暴露的地方）
          3. 关键定义存在（每个文件真正承重的部分）
        """
        import os
        # .rb 文件现在在 dsh_bridge/ 子目录（装机包）里
        base = os.path.join(_DSH_ROOT, "dsh_bridge")
        required = {
            "dsh_bridge.rb": ["module DshBridge", "class Server", "def dispatch",
                              "def reload", "IDLE_TIMEOUT"],
            "dsh_handlers.rb": ["module Handlers", "ACTIONS['eval']", "ACTIONS['ping']",
                                "ACTIONS['shot']", "ACTIONS['info']", "def to_mm"],
            "dsh_loader.rb": ["module Panel", "module Menu", "def page", "def build_toolbar"],
            "dsh_parts.rb": ["module DshParts", "def wall", "def slab_with_holes",
                            "def spiral_stair"],
        }
        for name, needles in required.items():
            path = os.path.join(base, name)
            with open(path, "rb") as f:
                raw = f.read()
            src = raw.decode("utf-8")  # 解码失败直接抛
            # 末尾的注释说明不算代码，先剔掉再判断收尾（这个检查脆过一次：注释把 end 挤走了）
            code_lines = [
                ln for ln in src.splitlines()
                if ln.strip() and not ln.strip().startswith("#")
            ]
            self.assertTrue(code_lines, f"{name} 是空的")
            self.assertEqual(
                code_lines[-1].strip(), "end",
                f"{name} 最后一行代码不是 end，很可能写入被截断（末行：{code_lines[-1]!r}）",
            )
            for needle in needles:
                self.assertIn(needle, src, f"{name} 缺少关键定义：{needle}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
