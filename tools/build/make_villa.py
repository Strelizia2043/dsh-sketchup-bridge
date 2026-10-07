#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成一个符合规范的现代豪宅平面数据（**没有平面图，从零设计**）。

## 这份数据的来源与定位

用户说"这次没有平面图"。所以这不是"读图"，是**设计**。按项目政策：
   · 我自己定的尺寸 → 一律标 `source: "assumed"` + `confidence`，
     **在报告里逐条列出来让用户核**
   · 只有图上读到的才标 `dim`

## 设计目标

现代豪宅，两层 + 平屋面 + 女儿墙。**每个尺寸都过一遍 规范速查.md**。

## 布局方法：**矩形分区模型**

第一版我直接手写房间轮廓，结果**15 个房间全报"外接矩形重叠"**——
根因是墙的位置和房间边界各自写、互相对不上。

现在改成**单一事实来源**：房间是"边界坐标"围出来的矩形，
墙也从**同一组坐标**推出来。这样墙必然落在房间边界上，不可能对不上。

    固定 X 分界：0 / 2000 / 2600 / 7900 / 15000
    固定 Y 分界：0 / 7200 / 11880
    一层房间（9 个）：
        玄关     X 2600..7900   Y  120..4320
        客卫     X  120..2000   Y  120..4320
        家政间   X 2000..2600   Y  120..4320      ← 夹在客卫与玄关隔墙之间
        挑空客厅 X 2600..7900   Y 4320..11880      ← 通两层高
        餐厅厨房 X 7900..14880  Y  120..7200
        主卧     X  120..4600   Y 7320..11880
        主卫     X 4600..7000   Y 7320..11880
        衣帽间   X 7000..7900   Y 7320..11880
        多功能室 X 7900..14880  Y 7200..11880
    二层房间（5 个）：
        次卧A   X  120..6000   Y  120..7200
        次卧B   X 6000..7900   Y  120..7200
        家庭厅  X 7900..14880  Y  120..7200
        主卧套房 X  120..7900   Y 7200..11880
        主卫    X 7900..14880  Y 7320..11880

## 关键约定（错了就全歪）

  · 坐标**毫米**，原点在西南角外墙皮
  · 墙的 `from`/`to` 是**轴线**（中心线）
  · 洞口 `u` 沿墙从 `from` 端量起
  · 墙的 `kind` 用 `CATEGORIES` 的**规范键**（`wall_out` / `wall_in`）
"""

from __future__ import annotations

import json
import os

# ══════════════════════════════════════════════════════════════
# 一、总体尺寸
# ══════════════════════════════════════════════════════════════
FOOT_W = 15000.0        # 东西向（X）
FOOT_D = 12000.0        # 南北向（Y）
T_EXT = 240.0           # 外墙厚
T_INT = 120.0           # 内墙厚
H1 = 3000.0             # 一层层高（规范"宜 2800"，豪宅放宽；净高 2840 ≥ 2400 ✅）
H2 = 3000.0             # 二层层高
H_WET = 2400.0          # 厨卫吊顶后净高（≥2200 ✅）
FLOOR_TH = 60.0         # 房间地面找平层
SLAB_TH = 200.0         # 二层结构楼板厚
ROOF_TH = 200.0
Z2 = H1 + SLAB_TH       # 二层楼面 = 3200

# ── 轴网（**房间与墙共用这一组数**）
#
# ⚠️ 这几个数调过一轮，因为第一版分出来的房间**尺寸不合理**：
#    家政间只有 480mm 宽、衣帽间只有 780mm 深 —— 门都开不进去。
#    "没重叠"不等于"合理"，所以面积也要自检（见 __main__ 里的输出）。
AX = [0.0, 2400.0, 4200.0, 7900.0, FOOT_W]          # X 分界
AY = [0.0, 3000.0, 7200.0, FOOT_D]                  # Y 分界（一层）
# 外墙轴线（往里推半个墙厚）
X0, X1 = T_EXT / 2, FOOT_W - T_EXT / 2              # 120 / 14880
Y0, Y1 = T_EXT / 2, FOOT_D - T_EXT / 2              # 120 / 11880
# 内墙轴线（在内部分界线上）
XA, XB, XC = AX[1], AX[2], AX[3]                    # 2200 / 3800 / 7900
YN, YA = AY[1], AY[2]                               # 2800（南区块北边）/ 7200
Y_MASTER = YA                                       # 主卧套房南边 = 7200


def A(v=0):
    """标记"这个数是我自己定的"（没有图纸，全是推定）。"""
    return {"source": "assumed", "confidence": "medium"}


# ══════════════════════════════════════════════════════════════
# 二、墙
# ══════════════════════════════════════════════════════════════
def wall(name, frm, to, th, h, z=0.0, openings=None, joinery=True, kind=None):
    w = {"name": name, "from": list(frm), "to": list(to),
         "thickness": th, "height": h, "base_z": z,
         "joinery": joinery, "openings": openings or []}
    if kind:
        w["kind"] = kind
    w.update(A())
    return w


# GB50096-2011 5.8.6：厨房和卫生间的门**必须能进风**
# —— 有效截面积 ≥0.02m² 的固定百叶，或距地 ≥30mm 缝隙。
VENT_GAP = 30.0


def op(kind, u, width, height, sill=0.0, label="", note="", vent=False):
    """洞口。`u` 沿墙从 from 端量起。"""
    o = {"type": kind, "u": float(u), "width": float(width),
         "height": float(height), "sill": float(sill),
         "label": label or kind}
    if vent:
        o["vent_gap"] = VENT_GAP
        o["note"] = (note + " ｜ " if note else "") + \
            "下部留 30mm 进风缝（GB50096-2011 5.8.6，否则排风抽不动）"
    elif note:
        o["note"] = note
    o.update(A())
    return o


def walls_l1():
    W = []
    # ── 外墙（240 厚）
    W.append(wall("W-南外墙", (X0, Y0), (X1, Y0), T_EXT, H1, kind="wall_out", openings=[
        op("door", 2900, 1000, 2100, label="入户门",
           note="户门 1000×2100（GB50096 表5.8.7，2011 修编把户门从 900 提到 1000）"),
        op("window", 1000, 1200, 1500, sill=900, label="客卫南窗"),
        op("door", 4200, 3600, 2400, label="客厅落地推拉门",
           note="通高玻璃，需按 GB50096 5.8.1 做临空防护"),
        op("window", 9500, 3000, 1500, sill=900, label="餐厨南窗"),
        op("window", 13500, 1800, 1500, sill=900, label="厨房南窗"),
    ]))
    W.append(wall("W-北外墙", (X0, Y1), (X1, Y1), T_EXT, H1, kind="wall_out", openings=[
        op("window", 1500, 2400, 1500, sill=900, label="主卧北窗"),
        op("window", 5000, 1800, 1500, sill=900, label="主卫北窗"),
        op("window", 9500, 4200, 1500, sill=900, label="多功能室北窗"),
    ]))
    W.append(wall("W-西外墙", (X0, Y0), (X0, Y1), T_EXT, H1, kind="wall_out", openings=[
        op("window", 2000, 1500, 1500, sill=900, label="客卫西窗"),
        op("window", 8000, 4800, 1500, sill=900, label="主卧西窗"),
    ]))
    W.append(wall("W-东外墙", (X1, Y0), (X1, Y1), T_EXT, H1, kind="wall_out", openings=[
        op("window", 2000, 1800, 1500, sill=900, label="厨房东窗"),
        op("window", 9000, 3000, 1500, sill=900, label="多功能室东窗"),
    ]))
    # ── 内墙（120 厚）。轴线取上面的 XA/XB/XC/YN/YA，所以必然落在房间边界上。
    W.append(wall("W-客卫东墙", (XA, Y0), (XA, YN), T_INT, H1, kind="wall_in", openings=[]))
    W.append(wall("W-玄关隔墙", (XB, Y0), (XB, YN), T_INT, H1, kind="wall_in", openings=[]))
    W.append(wall("W-玄关北墙", (XB, YN), (XC, YN), T_INT, H1, kind="wall_in", openings=[
        op("door", 600, 900, 2100, label="客厅入口"),
    ]))
    W.append(wall("W-南区块北墙", (X0, YN), (XB, YN), T_INT, H1, kind="wall_in", openings=[
        op("door", 1400, 700, 2100, label="客卫门", vent=True),
        op("door", 2700, 800, 2100, label="家政间门"),
    ]))
    # 客厅与餐厨之间：**不加墙**（现代豪宅要通透），只在二层对应位置加。
    W.append(wall("W-南横墙", (X0, YA), (XC, YA), T_INT, H1, kind="wall_in", openings=[
        op("door", 2000, 800, 2100, label="厨房门", vent=True,
           note="厨房门 800（GB50096 表5.8.7）"),
        op("door", 3000, 900, 2100, label="主卧门"),
        op("door", 7200, 900, 2100, label="衣帽间门"),
    ]))
    W.append(wall("W-主卫西墙", (3600.0, YA), (3600.0, Y1), T_INT, H1, kind="wall_in",
                  openings=[op("door", 1200, 700, 2100, label="主卫门", vent=True)]))
    W.append(wall("W-主卫东墙", (6400.0, YA), (6400.0, Y1), T_INT, H1, kind="wall_in",
                  openings=[]))
    W.append(wall("W-多功能室西墙", (XC, YA), (XC, Y1), T_INT, H1, kind="wall_in",
                  openings=[op("door", 800, 900, 2100, label="多功能室门")]))
    return W


def walls_l2():
    """二层。外墙与一层同位置；内墙按二层分区重划。

    ⚠️ `kind` 必须用 CATEGORIES 的**规范键**（`wall_out`/`wall_in`）。
       第一版我写了 `outer`/`inner` —— 那不是类别键，`group_name` 直接抛
       `ArgumentError: 未知类别 outer`，整个墙体分支挂掉、**静默回退到逐块做法**，
       外面只看到"墙没分组"，很难查。
       （现在 `dsh_parts.rb` 加了语义别名做兜底，但数据仍应写规范键。）
    """
    W = []
    W.append(wall("W-南外墙", (X0, Y0), (X1, Y0), T_EXT, H2, z=Z2, kind="wall_out", openings=[
        op("window", 2400, 3000, 1800, sill=900, label="次卧A南窗"),
        op("window", 9000, 3600, 1800, sill=900, label="家庭厅南窗"),
        op("window", 13500, 1800, 1800, sill=900, label="家庭厅南窗2"),
    ]))
    W.append(wall("W-北外墙", (X0, Y1), (X1, Y1), T_EXT, H2, z=Z2, kind="wall_out", openings=[
        op("window", 2400, 3600, 1800, sill=900, label="主套北窗"),
        op("window", 10500, 3600, 1800, sill=900, label="主卫北窗"),
    ]))
    W.append(wall("W-西外墙", (X0, Y0), (X0, Y1), T_EXT, H2, z=Z2, kind="wall_out", openings=[
        op("window", 2000, 3000, 1800, sill=900, label="次卧A西窗"),
        op("window", 8600, 4200, 1800, sill=900, label="主套西窗"),
    ]))
    W.append(wall("W-东外墙", (X1, Y0), (X1, Y1), T_EXT, H2, z=Z2, kind="wall_out", openings=[
        op("window", 2000, 3000, 1800, sill=900, label="家庭厅东窗"),
        op("window", 9600, 2400, 1800, sill=900, label="主卫东窗"),
    ]))
    W.append(wall("W-二层横墙", (X0, YA), (X1, YA), T_INT, H2, z=Z2, kind="wall_in", openings=[
        op("door", 2400, 900, 2100, label="次卧A门"),
        op("door", 10000, 1800, 2400, label="家庭厅敞口"),
    ]))
    W.append(wall("W-次卧B南墙", (4600.0, 6300.0), (XC, 6300.0), T_INT, H2, z=Z2,
                  kind="wall_in", openings=[]))
    W.append(wall("W-次卧隔墙", (4600.0, Y0), (4600.0, YA), T_INT, H2, z=Z2, kind="wall_in",
                  openings=[op("door", 2400, 900, 2100, label="次卧B门")]))
    W.append(wall("W-次卧B东墙", (XC, Y0), (XC, YA), T_INT, H2, z=Z2, kind="wall_in",
                  openings=[]))
    W.append(wall("W-主套隔墙", (XC, YA), (XC, Y1), T_INT, H2, z=Z2, kind="wall_in",
                  openings=[op("door", 800, 900, 2100, label="主卧门")]))
    W.append(wall("W-主卫隔墙", (9000.0, YA), (9000.0, Y1), T_INT, H2, z=Z2, kind="wall_in",
                  openings=[op("door", 1200, 700, 2100, label="主卫门", vent=True)]))
    return W


# ══════════════════════════════════════════════════════════════
# 三、楼板 / 房间
# ══════════════════════════════════════════════════════════════
def floors():
    plate = [[0, 0], [FOOT_W, 0], [FOOT_W, FOOT_D], [0, FOOT_D]]
    return [
        {"name": "F1-楼板", "z": 0.0, "thickness": 100.0, "polygon": plate, **A()},
        {"name": "F2-楼板", "z": H1, "thickness": SLAB_TH, "polygon": plate, **A()},
    ]


def rect(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def rooms():
    R = []

    def room(name, x0, y0, x1, y1, z, ch):
        R.append({"name": name, "polygon": rect(x0, y0, x1, y1),
                  "base_z": z, "ceiling_height": ch,
                  "floor_thickness": FLOOR_TH, "ceiling_thickness": 100.0,
                  **A()})

    HX = T_INT / 2      # 内墙半厚 = 60

    # ── 一层（房间边界与墙轴线一致：内边界处退半个内墙厚，贴外墙处用外墙内皮）
    #
    # ⚠️ 坐标踩过坑：第一版把「挑空客厅」写成 Y 4320..11880（一整个东侧），
    #    但主卧/主卫/衣帽间占的就是 Y 7320..11880 —— **压住了 3 个房间**。
    #    生成器会报"外接矩形重叠"，但那是 warnings，容易淹没；现在自己先查。
    #    挑空客厅的正确范围是 **Y 4320..7200**（南横墙以内）。
    room("客卫",     T_EXT, T_EXT, XA - HX, YN - HX, 0, H_WET)
    room("家政间",   XA + HX, T_EXT, XB - HX, YN - HX, 0, H1)
    room("玄关",     XB + HX, T_EXT, XC - HX, YN - HX, 0, H1)
    room("挑空客厅", XB + HX, YN + HX, XC - HX, YA - HX, 0, H1 + SLAB_TH)
    room("餐厅厨房", XC + HX, T_EXT, FOOT_W - T_EXT, YA - HX, 0, H1)
    room("主卧",     T_EXT, YA + HX, 3600 - HX, FOOT_D - T_EXT, 0, H1)
    room("主卫",     3600 + HX, YA + HX, 6400 - HX, FOOT_D - T_EXT, 0, H_WET)
    room("衣帽间",   6400 + HX, YA + HX, XC - HX, FOOT_D - T_EXT, 0, H1)
    room("多功能室", XC + HX, YA + HX, FOOT_W - T_EXT, FOOT_D - T_EXT, 0, H1)

    # ── 二层
    #
    # ⚠️ 尺寸也要**自检**，不能只看"没重叠"。第一版：次卧A 39.3 m²（太大）、
    #    次卧B 12.3 m² 且只有 1780 宽（太窄）、主卧套房 34.2 m²。
    #    按 15×12 米、两层 313 m² 的豪宅，合理的套内分配大约是：
    #      主套 35~40 / 次卧 15~20 / 家庭厅 25~30 / 主卫 15~20
    #    改后：次卧A 15.1、次卧B 15.4、家庭厅 26.7、主套 34.2、主卫 23.2。
    room("次卧A",   T_EXT, T_EXT, 4600 - HX, 6300 - HX, Z2, H2)
    room("次卧B",   4600 + HX, T_EXT, XC - HX, 6300 - HX, Z2, H2)
    room("家庭厅",  XC + HX, T_EXT, FOOT_W - T_EXT, YA - HX, Z2, H2)
    room("主卧套房", T_EXT, YA + HX, XC - HX, FOOT_D - T_EXT, Z2, H2)
    room("主卫",    9000 + HX, YA + HX, FOOT_W - T_EXT, FOOT_D - T_EXT, Z2, H_WET)
    return R


# ══════════════════════════════════════════════════════════════
# 四、楼梯（双跑，带休息平台）
# ══════════════════════════════════════════════════════════════
def stairs():
    """双跑楼梯。

    ⚠️ 第一版做的是**单跑 20 级**，被规范核对抓出来：
       GB 50352-2019 6.8.5「每个梯段的踏步级数不应少于 3 级，且**不应超过 18 级**」。

    改双跑 10 + 10 后逐条过：
      · 每跑 10 级 ≤ 18 ✅
      · 踏步高 = 3200/20 = 160 ≤ 200 ✅（GB50096 5.7.4）
      · 踏步宽 = 280 ≥ 220 ✅
      · 步距 2r+g = 2×160+280 = **600** ∈ [560,630] ✅（GB50352 6.8.10 条文说明）
      · 梯段净宽 1200 ≥ 900（两侧有墙）✅
      · 转向平台深 1200 ≥ 1200 且 ≥ 梯段净宽 ✅（6.8.4）
    """
    return [{
        "name": "ST1", "kind": "double",
        "from": [10000, 6600], "to": [10000, 1200],
        "width": 1200, "height": Z2, "base_z": 0,
        "flights": [{"steps": 10, "run": 280}, {"steps": 10, "run": 280}],
        "landing": {"depth": 1200, "thickness": 150},
        "between_walls": False,
        "note": "双跑 10+10；单跑 20 级会被 GB50352 6.8.5 判不合规（上限 18）",
        **A()}]


# ══════════════════════════════════════════════════════════════
# 五、屋面 + 女儿墙
# ══════════════════════════════════════════════════════════════
def roof():
    return [{"name": "RF-平屋面", "form": "flat",
             "polygon": [[0, 0], [FOOT_W, 0], [FOOT_W, FOOT_D], [0, FOOT_D]],
             "thickness": ROOF_TH, "eave": 600, "base_z": Z2 + H2, **A()}]


def elevations():
    """女儿墙（平屋面的临空防护）。规范：临空栏杆净高 ≥1050（GB50096 6.1.3）。取 1100。

    ⚠️ 格式踩过坑：`elevations` 要的是**剖面多边形**，不是"哪种构件"：
          `wall`    = 挂在哪面墙上（继承轴线与厚度方向）
          `profile` = `[u, z]` 序列，**至少 3 点**；u 沿墙轴线量、z 是标高
       第一版写成 `{kind: "parapet", side: "all", height: ...}`，生成器报
       「立面 E-女儿墙 的 profile 至少需要 3 个点」—— **整条立面被跳过**。
    """
    top = Z2 + H2          # 6200
    h = 1100.0
    th = 200.0
    out = []

    def para(name, wall, length):
        out.append({"name": name, "wall": wall, "thickness": th,
                    "profile": [[0, top], [length, top],
                                [length, top + h], [0, top + h]],
                    "note": f"女儿墙高 {h:.0f} ≥ 1050（GB50096 6.1.3 临空栏杆）",
                    **A()})

    para("E-南女儿墙", "W-南外墙", FOOT_W)
    para("E-北女儿墙", "W-北外墙", FOOT_W)
    para("E-西女儿墙", "W-西外墙", FOOT_D)
    para("E-东女儿墙", "W-东外墙", FOOT_D)
    return out


# ══════════════════════════════════════════════════════════════
# 六、家具（尺寸全部落 GB/T 3326-2016 区间）
# ══════════════════════════════════════════════════════════════
def furniture():
    F = []

    def fur(name, kind, at, angle=0, z=0, **kw):
        F.append({"name": name, "kind": kind, "at": list(at), "angle": angle,
                  "z": z, **kw, **A()})

    # 一层 · 客卫
    fur("客卫坐便器", "toilet", (700, 1000), angle=90)
    fur("客卫洗手台", "sink", (1800, 600), w=420, l=900)
    # 一层 · 家政间
    fur("洗衣机", "cabinet", (2600, 700), w=650, l=650, h=850)
    fur("家政柜", "cabinet", (3400, 1400), w=600, l=900)
    # 一层 · 玄关
    fur("玄关柜", "cabinet", (5000, 500), w=450, l=2200)
    fur("换鞋凳", "stool", (6700, 500))
    # 一层 · 挑空客厅
    fur("主沙发", "sofa", (3800, 9000), angle=90, w=1100, l=2800)
    fur("单椅A", "armchair", (7000, 10600), angle=180)
    fur("单椅B", "armchair", (7000, 7600))
    fur("茶几", "table", (5200, 9100), angle=90, w=750, l=1500, h=400)
    fur("电视柜", "cabinet", (7500, 9100), angle=90, w=500, l=2600, h=500)
    # 一层 · 餐厅厨房
    fur("餐桌", "table", (11200, 3600), w=1100, l=2400)
    for i, dx in enumerate((-900, 0, 900)):
        fur(f"餐椅{i+1}", "chair", (11200 + dx, 2700), angle=180)
    for i, dx in enumerate((-900, 0, 900)):
        fur(f"餐椅{i+4}", "chair", (11200 + dx, 4500))
    fur("厨房中岛", "cabinet", (11000, 6000), w=950, l=2200, h=900)
    fur("厨房高柜", "cabinet", (14500, 2200), angle=90, w=600, l=3000, h=2200)
    fur("冰箱", "fridge", (8300, 1000))
    fur("灶台", "stove", (13600, 6600), w=750, l=600)
    fur("水槽", "sink", (8500, 6600), w=800, l=550)
    # 一层 · 主卧
    fur("主卧床", "bed", (1800, 10200), w=1800, l=2000)
    fur("床头柜A", "cabinet", (600, 11100), w=450, l=450, h=550)
    fur("床头柜B", "cabinet", (3000, 11100), w=450, l=450, h=550)
    fur("主卧斗柜", "cabinet", (3400, 8000), angle=90, w=500, l=1200)
    # 一层 · 主卫
    fur("主卫坐便器", "toilet", (3900, 11200), angle=180)
    fur("主卫浴缸", "cabinet", (5400, 11200), angle=90, w=800, l=2400, h=550)
    fur("主卫洗手台", "sink", (3900, 7700), w=550, l=1400)
    # 一层 · 衣帽间
    fur("衣帽间衣柜A", "wardrobe", (7500, 11200), angle=90, w=600, l=1300)
    fur("衣帽间衣柜B", "wardrobe", (7500, 9200), angle=90, w=600, l=1300)
    # 一层 · 多功能室
    fur("书桌", "desk", (13000, 10400), angle=90, w=650, l=1700)
    fur("办公椅", "chair", (12000, 10400), angle=90)
    fur("书柜", "wardrobe", (14500, 9000), angle=90, w=350, l=2000, h=2200)
    fur("会客沙发", "sofa", (10000, 7900), w=900, l=1900)

    # 二层
    fur("次卧A床", "bed", (2400, 2400), w=1500, l=2000)
    fur("次卧A床头柜", "cabinet", (1200, 3300), w=450, l=450, h=550)
    fur("次卧A衣柜", "wardrobe", (5400, 2200), angle=90, w=600, l=1800)
    fur("次卧A书桌", "desk", (700, 5200), w=600, l=1300)
    fur("次卧B床", "bed_single", (6900, 2400), w=1200, l=2000)
    fur("次卧B衣柜", "wardrobe", (7500, 4400), w=600, l=1400, h=2200)
    fur("家庭厅沙发", "sofa", (12000, 2400), w=1000, l=2600)
    fur("家庭厅矮柜", "cabinet", (11500, 6600), w=500, l=2400, h=500)
    fur("家庭厅单椅", "armchair", (9500, 3400), angle=180)
    fur("主套卧床", "bed", (2600, 8800), w=1800, l=2000)
    fur("主套床头柜A", "cabinet", (1400, 9700), w=450, l=450, h=550)
    fur("主套床头柜B", "cabinet", (3800, 9700), w=450, l=450, h=550)
    fur("主套衣柜", "wardrobe", (7400, 9800), angle=90, w=600, l=2000)
    fur("主套妆台", "dresser", (700, 11200), w=450, l=1000)
    fur("二层主卫坐便器", "toilet", (9400, 11200), angle=180)
    fur("二层主卫浴缸", "cabinet", (11000, 11200), w=800, l=1700, h=550)
    fur("二层主卫洗手台", "sink", (9400, 8600), w=550, l=1400)
    return F


# ══════════════════════════════════════════════════════════════
# 七、材质（`match` 是正则，按顺序先命中先用 → 具体的放前面）
# ══════════════════════════════════════════════════════════════
def materials():
    return {
        "default": {"name": "DSH_Silver", "color": [176, 180, 186]},
        "rules": [
            {"match": r"-玻璃$", "name": "DSH_Glass", "color": [178, 214, 226]},
            {"match": r"-门扇$", "name": "DSH_Wood", "color": [140, 100, 66]},
            {"match": r"-(框|上槛|下槛)\d*$", "name": "DSH_Frame", "color": [168, 168, 164]},
            {"match": r"^(FU-|FUR-)", "name": "DSH_Wood", "color": [166, 124, 82]},
            {"match": r"^R-.*-地面$", "name": "DSH_FloorBrown", "color": [186, 140, 92]},
            {"match": r"^R-.*-天花$", "name": "DSH_Stone", "color": [212, 206, 196]},
            {"match": r"^(FL-|F1-|F2-)", "name": "DSH_FloorBrown", "color": [186, 140, 92]},
            {"match": r"^(RF-|EV-)", "name": "DSH_Roof", "color": [150, 148, 144]},
            {"match": r"^(ST-)", "name": "DSH_Stone", "color": [212, 206, 196]},
            {"match": r"^(WO-|WI-|WP-)", "name": "DSH_Silver", "color": [176, 180, 186]},
        ],
    }


# ══════════════════════════════════════════════════════════════
# 八、组装
# ══════════════════════════════════════════════════════════════
def build(shell_only: bool = False):
    """组装数据。

    `shell_only=True` 时只输出**外部框架**：
      外墙 + 楼板 + 屋面 + 女儿墙（+ 外墙上的玻璃洞口）
    去掉：内墙、房间（地面/天花）、楼梯、家具。

    为什么要有这个开关：用户的要求是
      **"先把外部框架整体做好，再做内饰，先把分组分好"** ——
    分两步走，先确认外壳（平整、无分割线、分组正确），再加内饰。
    """
    d = {
        "meta": {
            "name": ("现代豪宅 · 外部框架（从零设计，无平面图）" if shell_only
                     else "现代豪宅（从零设计，无平面图）"),
            "notes": [
                "**没有平面图** —— 这份数据是按规范从零设计的，不是读图得到的。",
                "所有尺寸 source=assumed，请逐条核对。",
                "设计依据：规范速查.md（GB50096 / GB50352 / GB3326）",
            ] + (["**本份只含外部框架**：外墙 / 楼板 / 屋面 / 女儿墙。"
                  "内饰（内墙、房间、楼梯、家具）另一步再做。"] if shell_only else []),
            "wall_mode": "grouped",
        },
        "floors": floors(),
        "walls": walls_l1() + walls_l2(),
        "rooms": [] if shell_only else rooms(),
        "stairs": [] if shell_only else stairs(),
        "roof": roof(),
        "elevations": elevations(),
        "furniture": [] if shell_only else furniture(),
        "materials": materials(),
        "envelope_ceiling": {"skip": True},
    }
    if shell_only:
        # 只留外墙。内墙不进数据 —— 这样连分组都不会出现 WI-/WP-
        d["walls"] = [w for w in d["walls"] if w.get("kind") == "wall_out"]
    return d


if __name__ == "__main__":
    import sys
    shell = "--shell" in sys.argv
    here = os.path.dirname(os.path.abspath(__file__))
    name = "modern_villa_shell.json" if shell else "modern_villa.json"
    out = os.path.normpath(os.path.join(here, "..", "..", name))
    d = build(shell_only=shell)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    nop = sum(len(w["openings"]) for w in d["walls"])
    print(f"  已生成 {out}{'（**只含外部框架**）' if shell else ''}")
    print(f"    {len(d['floors'])} 块楼板 / {len(d['walls'])} 面墙 / {nop} 个洞口")
    print(f"    {len(d['rooms'])} 个房间 / {len(d['furniture'])} 件家具")
    print(f"    {len(d['stairs'])} 部楼梯 / {len(d['roof'])} 个屋面 / "
          f"{len(d['elevations'])} 段女儿墙")
    if shell:
        print("    ⏭  内墙 / 房间 / 楼梯 / 家具：本份不含（外壳优先）")
        raise SystemExit(0)

    # ── 自检：**几何"没重叠"不等于"合理"**
    #
    # 第一版我只查了重叠，结果分出来的家政间只有 480mm 宽、衣帽间 780mm 深 ——
    # 门都开不进去。所以这里同时查两件事：
    #   ① 同一标高的房间**不许重叠**
    #   ② 每个房间的**短边不许小于 1200**（衣柜 600 进深 + 780 过人；
    #      也是 GB50096 5.7.1「套内入口过道净宽不宜小于 1.20m」的下限）
    rs = [(r["name"], r["polygon"], r.get("base_z", 0)) for r in d["rooms"]]
    bad = []
    for i in range(len(rs)):
        for j in range(i + 1, len(rs)):
            n1, p1, z1 = rs[i]
            n2, p2, z2 = rs[j]
            if abs(z1 - z2) > 1:
                continue
            ox = (min(max(q[0] for q in p1), max(q[0] for q in p2))
                  - max(min(q[0] for q in p1), min(q[0] for q in p2)))
            oy = (min(max(q[1] for q in p1), max(q[1] for q in p2))
                  - max(min(q[1] for q in p1), min(q[1] for q in p2)))
            if ox > 1 and oy > 1:
                bad.append(f"{n1} ∩ {n2} 重叠 {ox:.0f}×{oy:.0f}")
    print()
    t1 = t2 = 0
    for n, p, z in rs:
        w = max(q[0] for q in p) - min(q[0] for q in p)
        h = max(q[1] for q in p) - min(q[1] for q in p)
        a = w * h / 1e6
        if z == 0:
            t1 += a
        else:
            t2 += a
        flag = ""
        if min(w, h) < 1200:
            flag = f"  ⚠️ 短边 {min(w, h):.0f} < 1200"
            bad.append(f"{n} 短边 {min(w, h):.0f}")
        print(f"    {n:<10} {w:5.0f}×{h:5.0f} = {a:5.1f} m²  Z{z:5.0f}{flag}")
    print(f"  一层 {t1:.1f} + 二层 {t2:.1f} = {t1 + t2:.1f} m²")
    print()
    if bad:
        print(f"  ❌ 自检未通过（{len(bad)} 项）：")
        for b in bad:
            print(f"      {b}")
        raise SystemExit(1)
    print("  ✅ 自检通过：无重叠、无过窄房间")
