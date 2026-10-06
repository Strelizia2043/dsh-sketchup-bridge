#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键安装：把 DSH ↔ SketchUp 桥装到另一台机器上。

它做四件事：
  1. 找到 SketchUp 的 Plugins 目录（扫 %APPDATA%\\SketchUp\\SketchUp *\\SketchUp\\Plugins）
  2. 复制 4 个 .rb + 接手指南 + dsh_workspace.json
  3. 按**实际位置**重写 dsh_workspace.json（这一步是换机器能用的关键）
  4. 自检：文件齐全、路径定位、能不能连上桥

用法：
    python install.py                 # 自动找 Plugins，装，自检
    python install.py --list          # 只列出找到的 Plugins 目录
    python install.py --plugin-dir "C:\\...\\Plugins"
    python install.py --dry-run       # 只说要做什么，不动文件
    python install.py --uninstall     # 从 Plugins 里删掉装过的文件

**为什么需要重写 dsh_workspace.json**：
桥里原来把工作区路径写死成 'E:/deepseek工作区'，换机器就失效，
而且症状隐蔽（截图和产物悄悄写到别处，不报错）。
现在桥按四步定位，第一步就是读这个文件；安装时按实际位置填好，桥一次就能找对。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))          # dsh_bridge/ 目录
PROJECT = os.path.dirname(HERE)                            # 工作区根目录

FILES = {
    'dsh_bridge.rb':      'dsh_bridge.rb',
    'dsh_handlers.rb':    'dsh_handlers.rb',
    'dsh_loader.rb':      'dsh_loader.rb',
    'dsh_parts.rb':       'dsh_parts.rb',
    'DSH-接手指南.md':       'DSH-接手指南.md',
    'dsh_workspace.json': 'dsh_workspace.json',
}

PY = sys.executable or 'python'


def find_plugin_dirs():
    """扫出所有 SketchUp 版本的 Plugins 目录。"""
    out = []
    appdata = os.environ.get('APPDATA') or os.path.expanduser('~')
    base = os.path.join(appdata, 'SketchUp')
    if not os.path.isdir(base):
        return out
    for name in sorted(os.listdir(base)):
        d = os.path.join(base, name, 'SketchUp', 'Plugins')
        if os.path.isdir(d):
            out.append(d)
    return out


def _existing(path):
    """读一份已有的定位文件（保留它的 token 等字段）。"""
    try:
        with open(path, encoding='utf-8') as fp:
            d = json.load(fp)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def workspace_json(target=None, dry=False):
    """按**实际位置**写 dsh_workspace.json。

    ⚠️ **必须保留已有的 token**。
    第一版这里是"整份覆盖"，于是每次重装都把 token 冲掉 ——
    而桥进程里的 token 是启动时读的，客户端读的是文件：
    **两边立刻不一致，所有命令开始报 `[auth] token 不正确`**。
    症状看着像"桥坏了"，其实是安装脚本把自己的钥匙弄丢了。
    """
    # 目标目录那份是"真源"（桥从这里读），先把它现有的内容读出来
    dst = os.path.join(target, 'dsh_workspace.json') if target else \
        os.path.join(HERE, 'dsh_workspace.json')
    old = _existing(dst) or _existing(os.path.join(HERE, 'dsh_workspace.json')) \
        or _existing(os.path.join(PROJECT, 'dsh_workspace.json'))

    data = {
        '_说明': [
            'DSH <-> SketchUp 工作区定位文件（install.py 生成，可手工改）。',
            '',
            '桥按四步定位：本文件的 home -> 环境变量 DSH_WORKSPACE ->',
            '从桥自身位置向上找 sk_client.py -> 兜底。',
            '',
            'home 的语义是"含 sk_client.py 的那一层"，也就是工作区根目录。',
            '换机器/换目录时重新跑 install.py 即可。',
            '',
            'token 是桥与客户端共用的鉴权串，**首次运行由桥随机生成**。',
            '本文件已在 .gitignore 里，不会被提交。',
        ],
        'home': PROJECT.replace('\\', '/'),
        'project': os.path.basename(PROJECT),
        'shots': '',
        # 保住已有的 token；没有就留空，交给桥首次运行生成
        'token': old.get('token') or '',
        'plugin_dir': target or old.get('plugin_dir') or '',
    }
    text = json.dumps(data, ensure_ascii=False, indent=1)
    paths = [os.path.join(HERE, 'dsh_workspace.json'),
             os.path.join(PROJECT, 'dsh_workspace.json')]
    if target:
        paths.insert(0, os.path.join(target, 'dsh_workspace.json'))
    for path in paths:
        if dry:
            print('      [dry-run] 会写 %s（home=%s，token=%s）'
                  % (path, data['home'], '保留' if data['token'] else '待生成'))
            continue
        with open(path, 'w', encoding='utf-8') as fp:
            fp.write(text)
    return data


def ruby_shape_ok(path):
    """没有独立 ruby.exe，只能粗检：非空 + 合法 UTF-8 + 以 end 收尾。"""
    if not os.path.exists(path):
        return False, '文件不存在'
    raw = open(path, 'rb').read()
    if len(raw) < 500:
        return False, '只有 %d 字节，疑似截断' % len(raw)
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError as e:
        return False, '不是合法 UTF-8：%s' % e
    code = [l for l in text.splitlines()
            if l.strip() and not l.strip().startswith('#')]
    if not code or code[-1].strip() != 'end':
        last = code[-1].strip()[:40] if code else '(空)'
        return False, '最后一行不是 end，而是 %s' % last
    return True, '%d 字节 / %d 行' % (len(raw), len(text.splitlines()))


def main():
    ap = argparse.ArgumentParser(description='DSH <-> SketchUp 桥 一键安装')
    ap.add_argument('--plugin-dir', default=None, help='Plugins 目录（默认自动找）')
    ap.add_argument('--list', action='store_true', help='只列出找到的 Plugins 目录')
    ap.add_argument('--dry-run', action='store_true', help='只说要做什么')
    ap.add_argument('--uninstall', action='store_true', help='卸载')
    args = ap.parse_args()

    found = find_plugin_dirs()
    if args.list:
        print('找到的 Plugins 目录：')
        for d in found:
            print('   ' + d)
        if not found:
            print('   （没找到。SketchUp 装过吗？或换 --plugin-dir 指定）')
        return 0

    print('=' * 68)
    print('  DSH <-> SketchUp 桥   安装程序')
    print('=' * 68)
    print('  工作区根目录: %s' % PROJECT)
    print('  安装源目录  : %s' % HERE)

    target = args.plugin_dir
    if not target:
        if not found:
            print()
            print('  [X] 没找到 SketchUp 的 Plugins 目录。')
            print('      请用 --plugin-dir 指定，例如：')
            print('        python install.py --plugin-dir '
                  '"C:/Users/你/AppData/Roaming/SketchUp/SketchUp 2026/SketchUp/Plugins"')
            return 2
        if len(found) > 1:
            print()
            print('  发现多个 Plugins 目录，默认装到最新的一个：')
            for d in found:
                print('     ' + d)
        target = found[-1]
    print('  安装目标    : %s' % target)
    print()

    if args.uninstall:
        n = 0
        for name in FILES.values():
            p = os.path.join(target, name)
            if os.path.exists(p):
                if not args.dry_run:
                    os.remove(p)
                print('  已删除 %s' % name)
                n += 1
        print()
        print('  卸载完成（%d 个文件）%s' % (n, '  [dry-run]' if args.dry_run else ''))
        return 0

    # 1. 源文件检查
    #
    # ⚠️ `dsh_workspace.json` **不在仓库里**（它含 token 与本机路径，已 gitignore），
    # 所以**不能要求它作为源文件存在** —— 那是"克隆下来装不上"的经典写法。
    # 实测：第一版把它列进 FILES 做存在性检查，全新克隆一跑就
    #     [X] dsh_workspace.json 不存在 → 安装中止
    # 而我自己机器上一直有它，所以完全看不出问题。
    #
    # 正确做法：.rb / 指南这些**必须**在；配置文件**缺失就现场生成**。
    print('== 1. 检查源文件')
    bad = []
    for src in FILES:
        sp = os.path.join(HERE, src)
        if not os.path.exists(sp):
            if src == 'dsh_workspace.json':
                print('   [i] %s 不存在 —— 会现场生成（仓库里刻意不带它）' % src)
                continue
            bad.append('%s 不存在' % src)
            print('   [X] %s' % src)
            continue
        if src.endswith('.rb'):
            ok, msg = ruby_shape_ok(sp)
            print('   %s %s   %s' % ('[OK]' if ok else '[X]', src, msg))
            if not ok:
                bad.append('%s: %s' % (src, msg))
        else:
            print('   [OK] %s   %d 字节' % (src, os.path.getsize(sp)))
    if bad:
        print()
        print('  [X] 源文件有问题，已中止：')
        for b in bad:
            print('     ' + b)
        return 1

    # 2. 复制
    print()
    print('== 2. 复制文件')
    if not args.dry_run:
        os.makedirs(target, exist_ok=True)
    for src, dst in FILES.items():
        sp, dp = os.path.join(HERE, src), os.path.join(target, dst)
        if not os.path.exists(sp):
            # 只有 dsh_workspace.json 会走到这里（第 3 步会现场生成它）
            print('   [i] %s 不在仓库里，跳过（第 3 步现场生成）' % src)
            continue
        if args.dry_run:
            print('      [dry-run] %s -> %s' % (src, dp))
            continue
        if os.path.exists(dp):
            shutil.copy2(dp, dp + '.bak')
        shutil.copy2(sp, dp)
        print('   [OK] %s   %d 字节' % (dst, os.path.getsize(dp)))

    # 3. 写定位文件（关键一步）
    print()
    print('== 3. 写工作区定位文件')
    data = workspace_json(target, args.dry_run)
    if not args.dry_run:
        print('   [OK] home = %s' % data['home'])

    # 4. 自检
    print()
    print('== 4. 自检')
    if args.dry_run:
        print('   [dry-run] 跳过')
        return 0

    miss = [d for d in FILES.values() if not os.path.exists(os.path.join(target, d))]
    print('   %s 目标目录文件齐全   %s'
          % ('[OK]' if not miss else '[X]',
             ('缺：%s' % miss) if miss else '%d 个' % len(FILES)))

    ok_sc = os.path.exists(os.path.join(PROJECT, 'sk_client.py'))
    print('   %s 工作区有 sk_client.py' % ('[OK]' if ok_sc else '[X]'))

    connected = False
    if ok_sc:
        sys.path.insert(0, PROJECT)
        try:
            from sk_client import SC
            p = SC(timeout=15).ping()
            connected = True
            print('   [OK] 桥在线   v%s  SketchUp %s  %d 条命令'
                  % (p['version'], p['sketchup'], len(p['actions'])))
            br = p.get('briefing') or {}
            if 'must_read' in br:
                print('   [OK] 必读机制已就绪   must_read=%s' % br['must_read'])
            else:
                print('   [!] ping 里没有 briefing 字段 —— 装的是旧版 handlers')
        except Exception as e:
            print('   [!] 暂未连上桥：%s' % str(e)[:70])
            print('       这通常意味着 **SketchUp 还没启动**，或需要**重启 SketchUp**')
            print('       让插件生效。启动/重启后跑：')
            print('         %s %s' % (PY, os.path.join(PROJECT, 'tests',
                                                     'verify_restart.py')))

    print()
    print('=' * 68)
    if connected:
        print('  安装完成，且桥已在运行。')
    else:
        print('  安装完成（桥未在运行，属正常 —— 启动 SketchUp 即可）。')
    print('  下一步：')
    print('   1. 启动（或重启）SketchUp —— 插件在启动时加载')
    print('   2. 跑自检：python tests/verify_restart.py')
    print('   3. 新会话接手时，桥会要求先读 DSH-接手指南.md（硬门）')
    print('=' * 68)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
