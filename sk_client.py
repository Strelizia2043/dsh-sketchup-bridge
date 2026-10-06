#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DSH <-> SketchUp 桥的 Python 客户端。

用法（命令行）：
    python sk_client.py ping                       # 通不通
    python sk_client.py status
    python sk_client.py info                       # 模型概览
    python sk_client.py ruby "puts Sketchup.version"
    python sk_client.py run path/to/script.rb      # 跑一个 .rb 文件
    python sk_client.py shot --name look1          # 截图，返回文件路径
    python sk_client.py reload                     # 热重载插件命令层（不用重启 SketchUp）
    python sk_client.py undo 1
    python sk_client.py shell                      # 交互式，边聊边建

用法（当库）：
    from sk_client import SC
    c = SC()
    print(c.ping())
    c.ruby("ents = Sketchup.active_model.entities")
    print(c.shot("first-look"))

约定：
  * 所有坐标与尺寸对外一律毫米，桥那边负责换算。
  * 每条命令默认被包成一个 SketchUp 操作，撤销时是一步。
  * ruby(..., preview=True) 是干跑：执行完立刻撤销，先看效果。
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time

HOST = "127.0.0.1"
PORT = 9877

# 还没装过桥时用的占位 token（**不是**安全凭据）。
#
# 为什么需要它：全新克隆下来 `dsh_workspace.json` 还不存在（那是 install.py
# 或桥首次运行时才生成的）。此时：
#   · 假桥（测试用）需要有个 token 才跑得起来
#   · 客户端也需要拿到**同一个值**，否则整组协议测试报 auth 失败
#
# 所以两边共用这个常量，而不是各写各的字符串
# （实测：测试里写 "dsh-test-token-0000000000"、客户端返回 ""，
#  结果全新克隆跑协议测试 2 失败 8 错误）。
#
# 装好之后这个值就没人用了 —— 真 token 由桥随机生成并写进配置文件。
PLACEHOLDER_TOKEN = "dsh-not-installed-yet"


def _project_dir() -> str:
    """工作区根目录（含本文件的那一层）。"""
    return os.path.dirname(os.path.abspath(__file__))


def _load_token() -> str:
    """从 dsh_workspace.json 读 token。

    这里原来写死 `TOKEN = "dsh-su-2026"` —— **所有安装共用同一个**，
    而且上传到公开仓库等于把钥匙公开。现在桥在首次运行时随机生成，
    两边都从这个文件读，所以不需要手工同步。

    读不到（还没装）时退回 `PLACEHOLDER_TOKEN`：
    · 对**真桥**它一定不对 → 报 auth 错误，这是对的（说明你还没装）
    · 对**测试里的假桥**它能对上 → 让协议测试在未安装状态下也能跑
    """
    p = os.environ.get("DSH_WORKSPACE_CONFIG") or os.path.join(
        _project_dir(), "dsh_workspace.json")
    try:
        with open(p, encoding="utf-8") as fp:
            tok = (json.load(fp) or {}).get("token") or ""
        return str(tok) or PLACEHOLDER_TOKEN
    except Exception:
        return PLACEHOLDER_TOKEN


TOKEN = _load_token()
SHOT_DIR = os.path.join(_project_dir(), "shots")


class BridgeError(RuntimeError):
    """桥返回的业务错误。"""

    def __init__(self, code: str, message: str, payload: dict | None = None):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.payload = payload or {}


class SC:
    """SketchUp 桥客户端。一条连接对一条命令，够简单也够稳。"""

    def __init__(
        self,
        host: str = HOST,
        port: int = PORT,
        token: str = TOKEN,
        timeout: float = 120.0,
        debug: bool = False,
    ):
        self.host = host
        self.port = port
        self.token = token
        self.timeout = timeout
        self.debug = debug
        self._seq = 0

    # ------------------------------------------------------------ 底层

    def call(self, action: str, args: dict | None = None, timeout: float | None = None):
        """发一条命令，返回 result.data；失败抛 BridgeError。

        超时默认用 self.timeout。便利方法**不会**偷偷覆盖它——曾经有过这个 bug：
        ping() 里硬写 15 秒，把构造函数配的超时盖掉了，结果卡住时要干等 15 秒。
        """
        self._seq += 1
        req = {
            "id": f"{int(time.time()*1000)}-{self._seq}",
            "token": self.token,
            "action": action,
            "args": args or {},
        }
        line = (json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8")
        tmo = self.timeout if timeout is None else timeout
        if tmo is None:
            tmo = 120.0
        t0 = time.time()

        try:
            sock = socket.create_connection((self.host, self.port), timeout=min(tmo, 10.0))
        except OSError as e:
            raise BridgeError(
                "connect",
                f"连不上 SketchUp 桥 {self.host}:{self.port}（{e}）。"
                f"请确认：① SketchUp 正在运行 ② 插件已加载 ③ 菜单 Plugins > DSH 桥 里显示「运行中」",
            ) from e

        try:
            try:
                sock.settimeout(tmo)
                sock.sendall(line)
                buf = bytearray()
                while b"\n" not in buf:
                    chunk = sock.recv(1 << 16)
                    if not chunk:
                        raise BridgeError(
                            "closed",
                            "桥关闭了连接（通常是 eval 里的 Ruby 抛错，或命令跑太久）。"
                            "请到 SketchUp 的 Ruby 控制台看报错原文。",
                        )
                    buf.extend(chunk)
                raw = buf.split(b"\n", 1)[0].decode("utf-8", "replace")
            except socket.timeout as e:
                # 必须放在 OSError 之前：socket.timeout 是 OSError 的子类
                raise BridgeError(
                    "timeout",
                    f"等待 {tmo:g} 秒没有回音。SketchUp 的 Ruby 跑在界面线程上，"
                    f"重命令会把窗口卡住；也可能是弹了模态对话框在等你点。",
                ) from e
            except OSError as e:
                raise BridgeError("io", f"和桥的通信中断（{e}）") from e
        finally:
            try:
                sock.close()
            except OSError:
                pass

        elapsed = (time.time() - t0) * 1000
        if self.debug:
            print(f"[debug] {action} {elapsed:.0f}ms {raw[:400]}", file=sys.stderr)

        try:
            reply = json.loads(raw)
        except json.JSONDecodeError as e:
            raise BridgeError("bad_reply", f"桥回传的不是 JSON：{raw[:300]!r}") from e

        if not reply.get("ok"):
            err = reply.get("error") or {}
            raise BridgeError(err.get("code", "unknown"), err.get("message", "未知错误"), reply)

        result = reply.get("result") or {}
        data = result.get("data")
        if isinstance(data, dict):
            data.setdefault("_ms", result.get("ms"))
        return data

    # ------------------------------------------------------------ 语义化封装
    # 全部透传 timeout=None（= 用 self.timeout），方便需要时精确控制等待时长。

    def ping(self, timeout: float | None = None):
        return self.call("ping", timeout=timeout)

    def status(self, timeout: float | None = None):
        return self.call("status", timeout=timeout)

    def reload(self, timeout: float | None = None):
        return self.call("reload", timeout=timeout)

    def briefing(self, timeout: float | None = None):
        """读接手指南全文（DSH-接手指南.md）。

        **新会话应当先调这个**：桥会拦住未读指南时的 reload
        （防止在不知道那些坑的情况下改代码）。
        读一次即可，标记存在 DshBridge 上，跨热重载存活。
        """
        return self.call("briefing", timeout=timeout or 120)

    def info(self, scope: str = "top", limit: int = 40, timeout: float | None = None, **kw):
        args = {"scope": scope, "limit": limit}
        args.update(kw)
        return self.call("info", args, timeout=timeout)

    def ruby(self, code, undo: bool = True, op_name: str = "DSH", preview: bool = False,
             want_values: bool = False, timeout: float | None = None):
        """执行 Ruby。code 可以是字符串或字符串列表。"""
        if isinstance(code, str):
            code = [code]
        return self.call(
            "eval",
            {"code": list(code), "undo": undo, "op_name": op_name,
             "preview": preview, "print": want_values},
            timeout=timeout,
        )

    def run_file(self, path: str, timeout: float | None = None, **kw):
        with open(path, "r", encoding="utf-8") as f:
            return self.ruby(f.read(), timeout=timeout, **kw)

    def shot(self, name: str | None = None, width: int = 1280, height: int = 800,
             camera: dict | None = None, restore: bool = True,
             render_mode: int | None = None, timeout: float | None = None):
        """截图。

        render_mode（可选，实测于 SketchUp 2026）：
            0 = 线框 / 1 = 单色（**不显示材质颜色**）/ 2 = 着色+贴图（默认，能看材质）
        想验证材质必须用 2；没有"显示材质本色但不加光照"的模式。
        """
        args = {"name": name, "width": width, "height": height, "restore": restore}
        if camera:
            args["camera"] = camera
        if render_mode is not None:
            args["render_mode"] = render_mode
        return self.call("shot", args, timeout=timeout)

    def shot_path(self, *a, **kw) -> str | None:
        r = self.shot(*a, **kw)
        p = r.get("path") if isinstance(r, dict) else None
        return p

    def save(self, path: str | None = None, overwrite: bool = False, timeout: float | None = None):
        args = {"overwrite": overwrite}
        if path:
            args["path"] = path
        return self.call("save", args, timeout=timeout)

    def undo(self, count: int = 1, timeout: float | None = None):
        return self.call("undo", {"count": count}, timeout=timeout)

    def redo(self, count: int = 1, timeout: float | None = None):
        return self.call("redo", {"count": count}, timeout=timeout)

    def history(self, limit: int = 25, timeout: float | None = None):
        return self.call("history", {"limit": limit}, timeout=timeout)

    def select(self, ids, timeout: float | None = None):
        return self.call("select", {"ids": ids if isinstance(ids, list) else [ids]}, timeout=timeout)

    def erase(self, ids=None, all_: bool = False, confirm: bool = False, timeout: float | None = None):
        if all_:
            args: dict = {"all": True, "confirm": confirm}
        else:
            args = {"ids": ids if isinstance(ids, list) else [ids]}
        return self.call("erase", args, timeout=timeout)

    def focus(self, ids=None, timeout: float | None = None):
        return self.call("focus", {"ids": ids} if ids else {}, timeout=timeout)

    def measure(self, a, b, timeout: float | None = None):
        return self.call("measure", {"from": list(a), "to": list(b)}, timeout=timeout)

    def import_file(self, path: str, timeout: float | None = None):
        return self.call("import", {"path": path}, timeout=timeout)

    def export(self, path: str, allow_outside: bool = False, timeout: float | None = None):
        return self.call("export", {"path": path, "allow_outside": allow_outside}, timeout=timeout)


def latest_shot(directory: str = SHOT_DIR) -> str | None:
    """最近一张截图（按修改时间）。看图前先拿它比较省事。"""
    if not os.path.isdir(directory):
        return None
    files = [
        os.path.join(directory, f)
        for f in os.listdir(directory)
        if f.lower().endswith((".png", ".jpg"))
    ]
    if not files:
        return None
    return max(files, key=os.path.getmtime)


# ---------------------------------------------------------------- CLI


def _print(obj):
    if isinstance(obj, (dict, list)):
        print(json.dumps(obj, ensure_ascii=False, indent=2))
    else:
        print(obj)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="DSH <-> SketchUp 桥客户端")
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--debug", action="store_true", help="把原始往返打到 stderr")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("ping")
    sub.add_parser("status")
    sub.add_parser("reload")
    sub.add_parser("history")

    pi = sub.add_parser("info")
    pi.add_argument("--scope", default="top", choices=["top", "all", "faces", "edges", "selection"])
    pi.add_argument("--limit", type=int, default=40)

    pr = sub.add_parser("ruby")
    pr.add_argument("code")
    pr.add_argument("--preview", action="store_true", help="干跑：执行后立刻撤销")
    pr.add_argument("--no-undo", action="store_true", help="不包成一个操作")
    pr.add_argument("--values", action="store_true", help="回传表达式的值")
    pr.add_argument("--op-name", default="DSH")

    pf = sub.add_parser("run")
    pf.add_argument("path")
    pf.add_argument("--preview", action="store_true")

    ps = sub.add_parser("shot")
    ps.add_argument("--name")
    ps.add_argument("--width", type=int, default=1280)
    ps.add_argument("--height", type=int, default=800)

    pu = sub.add_parser("undo")
    pu.add_argument("count", nargs="?", type=int, default=1)
    pd = sub.add_parser("redo")
    pd.add_argument("count", nargs="?", type=int, default=1)

    psa = sub.add_parser("save")
    psa.add_argument("path", nargs="?", default=None)
    psa.add_argument("--overwrite", action="store_true")

    sub.add_parser("shell")

    args = p.parse_args(argv)
    if not args.cmd:
        p.print_help()
        return 2

    c = SC(port=args.port, debug=args.debug)

    try:
        if args.cmd == "ping":
            _print(c.ping())
        elif args.cmd == "status":
            _print(c.status())
        elif args.cmd == "reload":
            _print(c.reload())
        elif args.cmd == "history":
            _print(c.history())
        elif args.cmd == "info":
            _print(c.info(scope=args.scope, limit=args.limit))
        elif args.cmd == "ruby":
            _print(c.ruby(args.code, undo=not args.no_undo, op_name=args.op_name,
                         preview=args.preview, want_values=args.values))
        elif args.cmd == "run":
            _print(c.run_file(args.path, preview=args.preview))
        elif args.cmd == "shot":
            r = c.shot(name=args.name, width=args.width, height=args.height)
            _print(r)
            if isinstance(r, dict) and r.get("path"):
                print(f"\n截图: {r['path']}")
        elif args.cmd == "undo":
            _print(c.undo(args.count))
        elif args.cmd == "redo":
            _print(c.redo(args.count))
        elif args.cmd == "save":
            _print(c.save(args.path, overwrite=args.overwrite))
        elif args.cmd == "shell":
            return _shell(c)
    except BridgeError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1
    return 0


def _shell(c: SC) -> int:
    print("DSH SketchUp shell —— 直接敲 Ruby；:shot :info :reload :undo :q")
    while True:
        try:
            line = input("su> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line in (":q", ":quit", "exit"):
            return 0
        try:
            if line == ":shot":
                _print(c.shot())
            elif line == ":info":
                _print(c.info())
            elif line == ":reload":
                _print(c.reload())
            elif line.startswith(":undo"):
                parts = line.split()
                _print(c.undo(int(parts[1]) if len(parts) > 1 else 1))
            else:
                _print(c.ruby(line))
        except BridgeError as e:
            print(f"✗ {e}")


if __name__ == "__main__":
    raise SystemExit(main())
