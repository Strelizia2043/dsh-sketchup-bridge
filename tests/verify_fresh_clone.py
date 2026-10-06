#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证"别人克隆后能不能装上" —— 模拟一个全新用户。

为什么需要这一步：**上传成功 ≠ 别人能用**。
我自己这台机器上什么都有（工作区、插件、配置、凭据），
所以"我这儿能跑"完全不能说明问题。

这个脚本从**零开始**模拟：
    克隆到临时目录 → 跑 install.py → 看它能不能自己找对路径

⚠️ 它**不碰** SketchUp 插件目录（用 --dry-run），只验证"找得到、算得对"。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

REPO = "https://github.com/Strelizia2043/dsh-sketchup-bridge.git"
PY = sys.executable

# 输出多时 PowerShell 会缓冲/吞掉尾部（实测用户那边"什么都没显示"）。
# 用行缓冲 + 结尾显式 flush 解决。
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass


def run(cmd, cwd=None, timeout=600):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return r.returncode, (r.stdout or ""), (r.stderr or "")


def main() -> int:
    # 找到**仓库根目录**：脚本在 tests/ 下，要往上找含 .git 的那一层
    def find_repo_root(start):
        cur = start
        for _ in range(5):
            if os.path.isdir(os.path.join(cur, ".git")):
                return cur
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
        return os.path.dirname(start)

    if "--local" in sys.argv:
        src = find_repo_root(os.path.dirname(os.path.abspath(__file__)))
        print(f"== 用本地目录模拟克隆（{src}）")
    else:
        src = REPO
        print(f"== 从 GitHub 克隆（{src}）")

    # 临时目录放在**工作区内**：沙箱不允许写系统临时目录
    # （实测 WinError 5 拒绝访问 C:\Users\...\Temp）。
    # 也允许用 --tmp <目录> 指定。
    if "--tmp" in sys.argv:
        tmp = sys.argv[sys.argv.index("--tmp") + 1]
        os.makedirs(tmp, exist_ok=True)
    else:
        tmp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "_clone_test")
        if os.path.exists(tmp):
            shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp, exist_ok=True)
    target = os.path.join(tmp, "dsh-sketchup-bridge")
    print(f"   临时目录: {tmp}")
    print()

    ok = True

    # 1. 克隆
    if "--local" in sys.argv:
        # 本地模拟：只复制 git 跟踪的文件（等价于 clone 拿到的东西）
        os.makedirs(target, exist_ok=True)
        r = subprocess.run(["git", "ls-files", "-z"], cwd=src,
                           capture_output=True, timeout=300)
        raw = (r.stdout or b"").decode("utf-8", "replace")
        files = [f for f in raw.split("\0") if f.strip()]
        for f in files:
            d = os.path.join(target, os.path.dirname(f))
            os.makedirs(d, exist_ok=True)
            shutil.copy2(os.path.join(src, f), os.path.join(target, f))
        print(f"  [OK] 模拟克隆完成：{len(files)} 个跟踪文件")
    else:
        rc, out, err = run(["git", "clone", "--depth", "1", src, target], timeout=900)
        print(f"  {'[OK]' if rc == 0 else '[X]'} 克隆   退出码 {rc}")
        if rc != 0:
            print("      " + (err or out).strip().splitlines()[-1][:120])
            return 1
        ok = ok and rc == 0

    # 2. clone 拿到的东西对不对（gitignore 该生效的生效了）
    print()
    print("== 2. 克隆内容检查")
    must_have = [
        "README.md", "LICENSE", "QUICKSTART.md", ".gitignore", ".gitattributes",
        "dsh_bridge/dsh_bridge.rb", "dsh_bridge/dsh_handlers.rb",
        "dsh_bridge/dsh_loader.rb", "dsh_bridge/dsh_parts.rb",
        "dsh_bridge/DSH-接手指南.md", "dsh_bridge/install.py",
        "sk_client.py", "version.json",
        "tools/cad/dxf_import.py", "tools/cad/cad_to_plan.py",
        "tools/img/intake_check.py", "tools/img/extract_plan.py",
        "tools/build/build_from_json.py", "tests/verify_restart.py",
        "examples/cad_map_example.json",
    ]
    for f in must_have:
        exists = os.path.exists(os.path.join(target, f))
        print(f"   {'[OK]' if exists else '[X]'} {f}")
        ok = ok and exists

    must_not = ["dsh_workspace.json", "dsh_bridge/dsh_workspace.json",
                "bridge.log", "cad/project2.dxf"]
    print("   -- 不该出现的东西 --")
    for f in must_not:
        exists = os.path.exists(os.path.join(target, f))
        print(f"   {'[X] 泄漏了!' if exists else '[OK]'} {f}  不存在")
        ok = ok and not exists

    # 3. 关键：install.py 在**陌生路径**下能不能自己算对
    print()
    print("== 3. install.py 在全新目录里的行为（--dry-run，不动你的插件目录）")
    rc, out, err = run([PY, os.path.join(target, "dsh_bridge", "install.py"), "--dry-run"],
                       cwd=target)
    tail = [l for l in out.splitlines() if l.strip()][:22]
    for l in tail:
        print("   " + l)
    # 判据：它算出的工作区根目录必须是**这个临时目录**，而不是我原来那台机器的路径
    good = target.replace("\\", "/") in out.replace("\\", "/")
    print()
    print(f"   {'[OK]' if good else '[X]'} 它自己算出的路径 = 克隆所在的真实位置"
          + ("" if good else "  ← 说明还有写死的路径！"))
    ok = ok and good

    # 4. 工具能不能在全新进程里起来（不需要 SketchUp 的那部分）
    print()
    print("== 4. 工具能否在陌生目录里启动")
    for tool in ("tools/cad/dxf_import.py", "tools/img/intake_check.py",
                 "tools/build/build_from_json.py"):
        rc, out, err = run([PY, os.path.join(target, tool), "--help"], cwd=target)
        crashed = "Traceback" in err or "ModuleNotFoundError" in err
        print(f"   {'[OK]' if not crashed else '[X]'} {tool}   退出码 {rc}")
        if crashed:
            print("      " + err.strip().splitlines()[-1][:110])
        ok = ok and not crashed

    # 5. 不需要 SketchUp 的测试能不能跑
    print()
    print("== 5. 不需 SketchUp 的测试")
    rc, out, err = run([PY, os.path.join(target, "tests", "test_bridge_protocol.py")],
                       cwd=target, timeout=300)
    last = [l for l in (out or "").splitlines() if l.strip()][-1:] or [""]
    print(f"   {'[OK]' if rc == 0 else '[X]'} test_bridge_protocol.py   {last[0][:70]}")
    ok = ok and rc == 0

    print()
    print("=" * 66)
    if ok:
        print("  ✅ 别人克隆下来可以正常安装和使用")
    else:
        print("  ❌ 有问题 —— 上面标 [X] 的项需要修")
    print(f"  （临时目录保留着，想手工看：{tmp}）")
    print("=" * 66)
    if ok:
        print()
        print("   " + "=" * 60)
        print("   >>>  成功：别人克隆下来可以正常安装和使用  <<<")
        print("   " + "=" * 60)
    else:
        print()
        print("   " + "=" * 60)
        print("   >>>  失败：上面标 [X] 的项需要修  <<<")
        print("   " + "=" * 60)
    sys.stdout.flush()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
