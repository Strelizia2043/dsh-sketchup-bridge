#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重启后可用性验证：**全新进程**跑一遍完整链路。

为什么要单独做这一条：
前 33 轮的验证都在"同一个进程、同一个会话"里跑的，
所有路径、缓存、模型状态都是热的。而用户真正关心的是
**"关掉 DSH、关掉 SketchUp，再打开还能不能用"**。

⚠️ **本脚本会重建模型，默认禁止直接跑。**
   踩过：它跑之前会 `build_from_json.py shop_plan.json --confirm`
   （把合成测试模型建进当前文档），跑完又 `save(_boot_check.skp)`
   （把当前文档的路径和标题都改掉）。结果用户看到的是
   "最开始写插件试验时候那个模型"，而他自己的两层楼被顶掉了。
   **测试不许污染用户看得见的状态。**
   所以现在：默认只做"不碰模型"的检查；要跑建模那几步必须显式加
   `--touching-model`，而且脚本会**记下原路径并在结束时存回**。
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
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# ⚠️ 重组目录后这里必须是**工作区根目录**，不是本脚本所在目录：
# 脚本在 tests/，而 sk_client.py / cad/ / models/ / 各工具都在根目录。
# 我第一版直接用 HERE，结果全新进程里 rom sk_client import SC 报
# ModuleNotFoundError，而且产物被写到 tests/cad/ 下去了。
def _find_root(start):
    cur = start
    for _ in range(5):
        if os.path.exists(os.path.join(cur, 'sk_client.py')):
            return cur
        cur = os.path.dirname(cur)
    return start

ROOT = _find_root(HERE)
PY = sys.executable
# 是否允许"重建并另存当前模型"的危险步骤（默认否）
TOUCHING_MODEL = "--touching-model" in sys.argv


def _find_plugin_dir():
    """找 SketchUp 的 Plugins 目录。**不写死路径** —— 换机器也能跑。

    顺序：
      1. dsh_workspace.json 里 plugin_dir（install.py 装的时候会填）
      2. 扫 %APPDATA%\\SketchUp\\SketchUp *\\SketchUp\\Plugins，取最新的
      3. 都没有就返回 None（调用方给出"先跑 install.py"的提示）
    """
    import glob as _glob
    cfg = os.path.join(ROOT, 'dsh_workspace.json')
    try:
        with open(cfg, encoding='utf-8') as fp:
            pd = (json.load(fp) or {}).get('plugin_dir') or ''
        if pd and os.path.isdir(pd):
            return pd
    except Exception:
        pass
    appdata = os.environ.get('APPDATA') or os.path.expanduser('~')
    found = sorted(_glob.glob(os.path.join(
        appdata, 'SketchUp', 'SketchUp *', 'SketchUp', 'Plugins')))
    return found[-1] if found else None


def fresh(*args, timeout=900):
    """在**全新进程**里跑一个脚本（模拟"刚重启，什么都没热身"）。

    ⚠️ 第一个参数若是**裸脚本名**，会自动到 tools/ 各子目录里找。
    为什么必须这样：重组目录后脚本搬到了 tools/cad|img|build/，
    而调用处写的还是 `fresh("dxf_import.py", ...)` —— python 找不到文件时
    只打印 `can't open file` 并返回退出码 2，**不会产生 Traceback**，
    于是"没崩溃"的断言会把它判成 ✅。实测这条假通过藏了两项测试。
    """
    argv = list(args)
    if argv and argv[0].endswith('.py') and not os.path.isabs(argv[0]) \
            and not os.path.exists(os.path.join(ROOT, argv[0])):
        for sub in ('tools/cad', 'tools/img', 'tools/build', 'tests'):
            cand = os.path.join(ROOT, sub, argv[0])
            if os.path.exists(cand):
                argv[0] = os.path.relpath(cand, ROOT)
                break
    r = subprocess.run([PY, *argv], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return r.returncode, r.stdout or "", r.stderr or ""


class Check:
    def __init__(self):
        self.items = []

    def ok(self, name, cond, detail=""):
        self.items.append((name, bool(cond), detail))

    def report(self, title):
        print(f"\n== {title}")
        bad = 0
        for n, good, d in self.items:
            print(f"   {'✅' if good else '❌'} {n}" + (f"   {d}" if d else ""))
            bad += 0 if good else 1
        return bad


def main() -> int:
    total = 0
    c = Check()

    # ── 1. 桥能被全新进程连上
    rc, o, e = fresh("-c",
                     "import sys; sys.path.insert(0, r'%s')\n"
                     "from sk_client import SC\n"
                     "p = SC(timeout=30).ping()\n"
                     "print('OK', p['version'], p['sketchup'], len(p['actions']))" % ROOT)
    c.ok("全新进程能连上桥", rc == 0 and o.strip().startswith("OK"),
         o.strip().splitlines()[0] if o.strip() else e.strip()[:120])

    # ── 2. 每个 Python 工具都能在全新进程里单独启动（不依赖会话状态）
    #
    # ⚠️ 有些用例需要**示例图纸**，而真实图纸不进仓库（见 .gitignore 里的 cad/）。
    #    所以这里对每个用例声明它需要的输入文件；缺了就**跳过并说明原因**，
    #    而不是报失败 —— 否则别人克隆下来跑必挂，还看不出为什么。
    #    要完整跑这些用例，自己放一张 DXF 到 cad/ 下即可。
    tools = [
        ("dxf_import.py", ["examples/drawings/shop_plan.dxf"], ["examples/drawings/shop_plan.dxf"]),
        ("cad_to_plan.py", ["examples/cad_map_example.json", "--out", "cad/_boot_plan.json"],
         ["examples/cad_map_example.json"]),
        ("intake_check.py", ["shots/test_plan.png", "--calib-mm", "6000"], []),
        ("extract_plan.py", ["shots/test_plan.png", "--calib", "6000", "--calib-px", "453.5",
                             "--unit", "mm", "--outer-t", "240", "--inner-t", "120",
                             "--out", "cad/_boot_img_plan.json"], []),
    ]
    for name, args, needs in tools:
        # 先确认依赖的输入文件都在（缺图纸就跳过，不算失败）
        missing = [f for f in needs if not os.path.exists(os.path.join(ROOT, f))]
        if missing:
            print(f"   ⏭  {name} 跳过：缺少输入 {', '.join(missing)}"
                  f"（真实图纸不进仓库；自备一张放到 cad/ 下即可跑）")
            continue
        # 再确认脚本真的找到并存在 —— 否则"没崩溃"是假通过
        exists = (os.path.exists(os.path.join(ROOT, name))
                  or any(os.path.exists(os.path.join(ROOT, d, name))
                         for d in ('tools/cad', 'tools/img', 'tools/build', 'tests')))
        rc, o, e = fresh(name, *args)
        # 这些工具"图纸不合格"时会返回非 0，那是**正常**的；只看有没有崩溃。
        # ⚠️ 另外必须排除 "can't open file"：python 找不到脚本时返回 2、
        #    而且**不产生 Traceback**，只查崩溃会把它判成通过（实测藏过两项）。
        crashed = ("Traceback" in e or "SyntaxError" in e or "ImportError" in e
                   or "can't open file" in e)
        c.ok(f"{name} 能在全新进程运行", exists and not crashed,
             ("脚本没找到（查过根目录与 tools/*）" if not exists
              else "崩溃了：" + e.strip().splitlines()[-1][:100] if crashed
              else f"退出码 {rc}"))

    # ── 3. 产物真的落在磁盘上
    for f in ("cad/_boot_plan.json", "cad/_boot_img_plan.json"):
        p = os.path.join(ROOT, f)
        c.ok(f"产物 {f} 已落盘", os.path.exists(p),
             f"{os.path.getsize(p)} B" if os.path.exists(p) else "不存在")

    # ── 4~6. 会重建并另存当前模型的检查 —— **默认跳过**
    #
    # 为什么默认跳过：这几步会把合成测试模型建进当前文档，
    # 再把文档另存成 `_boot_check.skp`（路径和标题一起改掉）。
    # 实测后果：用户看到的是"最开始写插件试验时候那个模型"，
    # 而他自己的两层楼工作文档被顶掉了。
    #
    # **测试不许污染用户看得见的状态。**
    if not TOUCHING_MODEL:
        print("\n== 4~6. 建模 / 几何自检 / 存盘")
        print("   ⏭  已跳过（未加 --touching-model）")
        print("      这几步会重建并另存当前模型；要跑请显式加该参数，"
              "脚本会记下原路径并在结束时存回")
    else:
        print(f"\n   ⚠️ 已启用 --touching-model：会重建并另存当前模型")
        # ── 4. 生成器在全新进程里能建模（最关键的一环）
        rc, o, e = fresh("build_from_json.py", "shop_plan.json", "--confirm")
        c.ok("build_from_json.py 能建模", rc == 0 and "构件" in o,
             [l.strip() for l in o.splitlines() if "构件" in l][:1][0]
             if "构件" in o else e[:120])

        # ── 5. 几何自检通过
        rc, o, e = fresh("check_geometry.py", "shop_plan.json")
        c.ok("check_geometry.py 通过", rc == 0,
             [l.strip() for l in o.splitlines() if "逐一核对" in l][:1][0][:90]
             if "逐一核对" in o else f"退出码 {rc}")

        # ── 6. 模型能存成 .skp 再读回（重启后模型还在）
        #
        # ⚠️ 这一条曾经**破坏用户的工作文档**，必须小心：
        #
        # 踩过：本脚本第 4 步会 `build_from_json.py shop_plan.json --confirm` 重建模型，
        # 第 6 步又 `c.save(path='models/_boot_check.skp')`——而 SketchUp 的 save
        # 会把**当前文档**的路径和标题都改成那个文件。结果用户看到的是
        # 「最开始写插件试验时候那个模型」（合成测试住宅，6120×4916），
        # 而他自己的两层楼工作文档被顶掉了。
        #
        # 修法：把当前文档状态记下来，测完**存回原路径**；原文档没路径（新建未存）
        # 就明确提示，不假装无事发生。**测试不许污染用户看得见的状态。**
        before = fresh("-c",
                       "import sys, json; sys.path.insert(0, r'%s')\n"
                       "from sk_client import SC\n"
                       "c = SC(timeout=60)\n"
                       "out = c.ruby('m=Sketchup.active_model; "
                       "puts [m.path.to_s, m.title.to_s, m.entities.length.to_s].join(\"|\")', undo=False)\n"
                       "print(out.get('output','').strip())" % ROOT)[1].strip().splitlines()[-1]
        b_path, b_title, b_n = (before.split("|") + ["", "", ""])[:3]
        print(f"   （测试前文档：{b_title or '(未命名)'}  {b_n} 个实体"
              f"{'  路径 ' + b_path if b_path else ''}）")

        # ⚠️ 路径不能写死（原来是 E:/deepseek工作区/...）—— 换机器就跑不了。
        # 用 ROOT 推；注意 Windows 上是反斜杠，塞进 Ruby 单引号字符串前
        # 要转成正斜杠，否则 `\U` 之类会被当成转义（Ruby 单引号只转义 \\ 和 \'，
        # 但混着用很容易踩，统一换成正斜杠最省事）。
        _skp = os.path.join(ROOT, "models", "_boot_check.skp").replace("\\", "/")
        rc, o, e = fresh("-c",
                         "import sys; sys.path.insert(0, r'%s')\n"
                         "from sk_client import SC\n"
                         "c = SC(timeout=180)\n"
                         "r = c.save(path='%s', overwrite=True)\n"
                         "print('SAVED', r['path'], r['bytes'])" % (ROOT, _skp))
        c.ok("模型能存成 .skp", rc == 0 and "SAVED" in o, o.strip()[:120])
        skp = os.path.join(ROOT, "models", "_boot_check.skp")
        c.ok(".skp 文件确实存在于磁盘", os.path.exists(skp),
             f"{os.path.getsize(skp)} B" if os.path.exists(skp) else "不存在")

        # 把文档存回原路径，并删掉临时文件，尽量把状态还原
        if b_path:
            fresh("-c",
                  "import sys; sys.path.insert(0, r'%s')\n"
                  "from sk_client import SC\n"
                  "SC(timeout=180).save(path=%r, overwrite=True)\n"
                  "print('restored')" % (ROOT, b_path.replace('\\', '/')))
            c.ok("测试后文档已存回原路径", True, b_path)
        else:
            print("   ⚠️ 测试前文档没有保存过路径，无法自动存回——"
                  "请自行确认当前模型是否是你想要的")

        # ── 7. 插件目录里四个文件都在、都被启动链路覆盖
        #
        # 插件目录**不写死**：换机器、装别的 SketchUp 版本都能跑。
        # 优先用 dsh_workspace.json 里 install.py 填好的值，
        # 否则自己扫 %APPDATA%\SketchUp\SketchUp *\SketchUp\Plugins。
        PLUG = _find_plugin_dir()
        import hashlib
        if PLUG is None:
            c.ok("找得到 SketchUp 插件目录", False,
                 "没找到 —— 先跑 python dsh_bridge/install.py")
        else:
            for n in ("dsh_bridge.rb", "dsh_handlers.rb", "dsh_loader.rb", "dsh_parts.rb"):
                a, b = os.path.join(PLUG, n), os.path.join(ROOT, n)
                if not os.path.exists(b):
                    b = os.path.join(ROOT, "dsh_bridge", n)
                if os.path.exists(a) and os.path.exists(b):
                    ha = hashlib.sha256(open(a, "rb").read()).hexdigest()
                    hb = hashlib.sha256(open(b, "rb").read()).hexdigest()
                    c.ok(f"插件 {n} 与工作区一致", ha == hb)
                else:
                    c.ok(f"插件 {n} 存在", False,
                         f"插件={os.path.exists(a)} 工作区={os.path.exists(b)}")

    total += c.report("重启后可用性（全部在全新进程里验证）")

    # 清理临时产物。
    # ⚠️ 必须容错：SketchUp 存完盘会持有文件句柄，Windows 上删不掉
    # （实测 WinError 32）。这跟"能不能用"无关，不该让它变成一个失败。
    for f in ("cad/_boot_plan.json", "cad/_boot_img_plan.json", "models/_boot_check.skp"):
        p = os.path.join(ROOT, f)
        try:
            if os.path.exists(p):
                os.remove(p)
        except OSError as ex:
            print(f"   （提示：临时文件 {f} 暂时删不掉：{ex.strerror}；"
                  f"SketchUp 释放句柄后即可删，不影响使用）")

    print()
    print("=" * 66)
    print("✅ 重启后一切可用" if total == 0 else f"❌ 有 {total} 项会在重启后出问题")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
