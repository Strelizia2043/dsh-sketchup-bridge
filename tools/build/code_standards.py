#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""建筑常识库 —— 规范的硬数字，供生成器**自动核对**用。

## 这个文件解决什么问题

用户提的要求："门正常应该多高多宽，灯要放在离地面多高的位置间隔不能少于多少"。
以前我建门靠"通行值"（1.0×2.1 之类）凭印象写，**没有出处**。
现在每个数字都连到规范条文，生成时可以自动核对，超范围就写进疑问清单问用户。

## 数字的置信度规则（重要）

本文件的每条标准都带 `src` 与 `conf`：
  · `conf="规范"` —— **直接从规范原文抄下来的**，带条文号
  · `conf="通行"` —— 行业通行做法，规范没直接规定（或我没查到原文）
  · `conf="待核"` —— 我用常识写的，**没有出处**，用之前必须再查

**只有 `规范` 级的数字可以硬性拦截**，另外两级只能提示、不能拒绝生成。

## 来源

均引自公开发布的国标条文（原文链接见各条 `src`）：
  · GB 50096-2011《住宅设计规范》
  · GB 50352-2019《民用建筑设计统一标准》
  · GB 50034-2013《建筑照明设计标准》（照度值，条文原文未取到，见下）
"""

from __future__ import annotations

# ────────────────────────────────────────────────────────────
# 常用尺寸别名（图纸/口语里都这么说）
# ────────────────────────────────────────────────────────────
MM = 1.0          # 本文件全部用毫米
M = 1000.0


# ══════════════════════════════════════════════════════════════
# 1. 门洞（GB 50096-2011 表 5.8.7）
# ══════════════════════════════════════════════════════════════
# 原文注释：
#   1 表中门洞口高度不包括门上亮子高度，宽度以平开门为准
#   2 洞口两侧地面有高低差时，以高地面为起算高度
# 条文说明 5.8.7："本次修编根据住宅实态调查数据仅将户门洞口宽度增大为 1.00m，
#                 其余未作改动。"
DOORS = {
    "户门":   {"w": 1000, "h": 2100, "src": "GB50096-2011 表5.8.7", "conf": "规范",
               "note": "2011 修编把户门宽度从 0.90 提到 1.00"},
    "起居室门": {"w": 900, "h": 2100, "src": "GB50096-2011 表5.8.7", "conf": "规范"},
    "卧室门":  {"w": 900, "h": 2100, "src": "GB50096-2011 表5.8.7", "conf": "规范"},
    "厨房门":  {"w": 800, "h": 2100, "src": "GB50096-2011 表5.8.7", "conf": "规范"},
    "卫生间门": {"w": 700, "h": 2100, "src": "GB50096-2011 表5.8.7", "conf": "规范"},
    "阳台门":  {"w": 800, "h": 2100, "src": "GB50096-2011 表5.8.7", "conf": "规范"},
    # 无障碍（GB 50763）—— 通行值，本文件不硬拦
    "无障碍门": {"w": 800, "h": 2100, "src": "GB50763 通行值", "conf": "通行"},
}

# 厨房/卫生间的门必须能进风（GB50096-2011 5.8.6）：
#   下部设有效截面积 ≥0.02 m² 的固定百叶，**或** 距地面留 ≥30mm 的缝隙
KITCHEN_BATH_DOOR_GAP = {"gap_mm": 30, "area_m2": 0.02,
                         "src": "GB50096-2011 5.8.6", "conf": "规范"}


# ══════════════════════════════════════════════════════════════
# 2. 窗台与防护（GB 50096-2011 5.8.1 / 6.1.1 / 6.1.3）
# ══════════════════════════════════════════════════════════════
WINDOW = {
    # 外窗（窗外无阳台/平台）窗台净高 < 0.90m 时必须设防护设施
    "sill_protect_below": {"v": 900, "src": "GB50096-2011 5.8.1", "conf": "规范"},
    # 凸窗：窗台 ≤0.45m 时，防护高度从窗台面起算 ≥0.90m
    "bay_sill_low": {"v": 450, "src": "GB50096-2011 5.8.2-1", "conf": "规范"},
    "bay_protect_h": {"v": 900, "src": "GB50096-2011 5.8.2-1", "conf": "规范"},
    # 0.45m 以下的可踏面不计入窗台净高（容易无意识攀登）
    "step_exclude": {"v": 450, "src": "GB50096-2011 5.8.1 条文说明", "conf": "规范"},
}

# 临空栏杆净高（GB 50096-2011 6.1.3）
RAILING = {
    "外廊内天井上人屋面_6层及以下": {"h": 1050, "src": "GB50096-2011 6.1.3", "conf": "规范"},
    "外廊内天井上人屋面_7层及以上": {"h": 1100, "src": "GB50096-2011 6.1.3", "conf": "规范"},
    "公共出入口台阶_高>700且临空": {"h": 1050, "src": "GB50096-2011 6.1.2", "conf": "规范"},
    # 垂直杆件间净距 ≤0.11m —— 防儿童穿过/攀登
    "杆件净距_max": {"v": 110, "src": "GB50096-2011 6.1.3", "conf": "规范"},
    "室内楼梯扶手_自踏步前缘量": {"h": 900, "src": "GB50352-2019 6.8.8", "conf": "规范",
                          "note": "不宜小于 0.90m"},
    "水平栏杆_长度>0.5m": {"h": 1050, "src": "GB50352-2019 6.8.8", "conf": "规范"},
}


# ══════════════════════════════════════════════════════════════
# 3. 楼梯（GB 50352-2019 6.8 + GB 50096-2011 5.7）
# ══════════════════════════════════════════════════════════════
STAIR = {
    # 踏步（套内楼梯，住宅内部）
    "踏步宽_min": {"v": 220, "src": "GB50096-2011 5.7.4", "conf": "规范"},
    "踏步高_max": {"v": 200, "src": "GB50096-2011 5.7.4", "conf": "规范"},
    # 扇形踏步：距内侧扶手中心 0.25m 处宽度 ≥0.22m
    "扇形踏步_0.25m处宽_min": {"v": 220, "src": "GB50096-2011 5.7.4", "conf": "规范"},
    "扇形踏步_参照半径": {"v": 250, "src": "GB50096-2011 5.7.4", "conf": "规范"},
    # 梯段净宽
    "套内_一边临空_净宽_min": {"v": 750, "src": "GB50096-2011 5.7.3", "conf": "规范"},
    "套内_两侧有墙_净宽_min": {"v": 900, "src": "GB50096-2011 5.7.3", "conf": "规范",
                          "note": "并在其中一侧墙面设扶手"},
    # 级数（**单位是"级"，不是毫米** —— 别在打印时都套 mm）
    "每梯段级数_min": {"v": 3, "unit": "级", "src": "GB50352-2019 6.8.5", "conf": "规范"},
    "每梯段级数_max": {"v": 18, "unit": "级", "src": "GB50352-2019 6.8.5", "conf": "规范"},
    # 净高
    "梯段净高_min": {"v": 2200, "src": "GB50352-2019 6.8.6", "conf": "规范"},
    "平台上下过道净高_min": {"v": 2000, "src": "GB50352-2019 6.8.6", "conf": "规范"},
    # 平台
    "转向平台宽_min": {"v": 1200, "src": "GB50352-2019 6.8.4", "conf": "规范",
                    "note": "且不小于梯段净宽"},
    "直跑中间平台_min": {"v": 900, "src": "GB50352-2019 6.8.4", "conf": "规范"},
    # 步距公式（2r+g）—— 舒适度自检
    "步距_舒适范围": {"lo": 560, "hi": 630, "src": "GB50352-2019 6.8.10 条文说明", "conf": "规范"},
}


# ══════════════════════════════════════════════════════════════
# 4. 过道净宽（GB 50096-2011 5.7.1）
# ══════════════════════════════════════════════════════════════
CORRIDOR = {
    "套内入口过道": {"min": 1200, "src": "GB50096-2011 5.7.1", "conf": "规范"},
    "通往卧室起居室": {"min": 1000, "src": "GB50096-2011 5.7.1", "conf": "规范"},
    "通往厨房卫生间贮藏室": {"min": 900, "src": "GB50096-2011 5.7.1", "conf": "规范"},
}


# ══════════════════════════════════════════════════════════════
# 5. 层高与净高（GB 50096-2011 5.5）
# ══════════════════════════════════════════════════════════════
HEIGHT = {
    "层高_宜": {"v": 2800, "src": "GB50096-2011 5.5.1", "conf": "规范",
              "note": "把层高控制在 2.80m 以下，为了节地节能"},
    "卧室起居室净高_min": {"v": 2400, "src": "GB50096-2011 5.5.2", "conf": "规范"},
    # 梁底/吊柜底等局部：≥2.10m，且局部净高面积 ≤ 使用面积的 1/3
    "局部净高_min": {"v": 2100, "src": "GB50096-2011 5.5.2", "conf": "规范"},
    "局部净高面积占比_max": {"v": 1 / 3, "src": "GB50096-2011 5.5.2", "conf": "规范"},
    "坡屋顶作卧室_≥2.10m面积占比_min": {"v": 0.5, "src": "GB50096-2011 5.5.3", "conf": "规范"},
    "厨房卫生间净高_min": {"v": 2200, "src": "GB50096-2011 5.5.4", "conf": "规范"},
    # 厨卫排水横管下表面距地面净距
    "厨卫排水横管下净距_min": {"v": 1900, "src": "GB50096-2011 5.5.5", "conf": "规范"},
}


# ══════════════════════════════════════════════════════════════
# 6. 照度标准值（GB 50034-2013）
# ══════════════════════════════════════════════════════════════
# ⚠️ 置信度说明：GB 50034 的**表格在 PDF/图片里，我没取到条文原文**。
#    下面这些是通行引用的数值，标 conf="通行"。
#    要用作硬性判断之前，必须先去核对规范原文（这一步没做）。
ILLUMINANCE = {
    "起居室_一般活动": {"lx": 100, "plane": 0.75, "conf": "通行"},
    "起居室_书写阅读": {"lx": 300, "plane": 0.75, "conf": "通行"},
    "卧室_一般活动":  {"lx": 75,  "plane": 0.75, "conf": "通行"},
    "卧室_床头阅读":  {"lx": 150, "plane": 0.75, "conf": "通行"},
    "餐厅":        {"lx": 150, "plane": 0.75, "conf": "通行"},
    "厨房_一般":    {"lx": 100, "plane": 0.75, "conf": "通行"},
    "厨房_操作台":  {"lx": 500, "plane": 0.75, "conf": "通行"},
    "卫生间":      {"lx": 150, "plane": 0.75, "conf": "通行"},
    "楼梯间":      {"lx": 100, "plane": 0.0,  "conf": "通行"},
    "走道":        {"lx": 100, "plane": 0.0,  "conf": "通行"},
}

# 灯具安装高度
# ⚠️ conf="待核"：这些是我按常识写的，**没有规范出处**。
#    规范（GB 50352 / 各地低压用电规程）只规定**安全下限**：
#      额定电压 220V 的灯具，潮湿及危险场所/生产车间/室外 距地 ≥2.5m
SAFE_LAMP_HEIGHT = {
    "220V灯具_潮湿危险场所车间室外_min": {
        "v": 2500, "src": "上海市低压用户电气装置规程 5.2.7", "conf": "规范"},
}
LAMP_HEIGHT = {
    "客厅吊灯":   {"v": 2200, "conf": "待核", "note": "灯底距地；低于此会碰头"},
    "餐桌吊灯":   {"v": 1800, "conf": "待核", "note": "桌面以上 700~800 更常见"},
    "卧室吸顶灯": {"v": 2200, "conf": "待核"},
    "厨房吸顶灯": {"v": 2200, "conf": "待核"},
    "卫生间吸顶灯": {"v": 2200, "conf": "待核"},
    "壁灯":      {"v": 1800, "conf": "待核"},
    "镜前灯":    {"v": 1800, "conf": "待核"},
    "开关_距地":  {"v": 1300, "conf": "待核"},
    "插座_距地":  {"v": 300,  "conf": "待核"},
    "厨房台面插座": {"v": 1000, "conf": "待核"},
}

# 灯具间距 —— **这个用户明确问了**
#
# 规范里**没有**"间距不能少于多少"这种条文。间距是按**距离比**算的：
#       间距 S ≤ 距离比 × (灯具到工作面高度 H)
# 距离比因灯具配光而异（下面这些是通行取值，conf="通行"）。
# 所以正确的回答是：**间距下限不是常数，取决于灯具类型和安装高度**。
LAMP_SPACING = {
    "距离比_荧光灯_半直接": 1.5,
    "距离比_筒灯_宽配光":   0.7,
    "距离比_筒灯_中配光":   0.5,
    "距离比_泛光灯":        0.5,
    "conf": "通行",
    "formula": "S_max = 距离比 × H（H = 灯具到工作面高度，工作面一般取距地 0.75m）",
    "note": "规范没有规定间距下限；间距由照度均匀度反推。"
            "所以本文件只给公式与距离比，不给一个假的固定数字。",
}


# ══════════════════════════════════════════════════════════════
# 7. 其他常用（均为通行值，不硬拦）
# ══════════════════════════════════════════════════════════════
COMMON = {
    "台阶_踏步宽_min":  {"v": 300, "src": "GB50096-2011 6.1.4", "conf": "规范"},
    "台阶_踏步高_max":  {"v": 150, "src": "GB50096-2011 6.1.4", "conf": "规范"},
    "台阶_踏步高_min":  {"v": 100, "src": "GB50096-2011 6.1.4", "conf": "规范"},
    "台阶_级数_min":    {"v": 2,   "src": "GB50096-2011 6.1.4", "conf": "规范"},
    "台阶_宽>1.8m时扶手高": {"v": 900, "src": "GB50096-2011 6.1.4", "conf": "规范"},
    "楼梯井_防坠落_净宽阈值": {"v": 200, "src": "GB50352-2019 6.8.9", "conf": "规范"},
    "栏杆镂空净距_max":  {"v": 110, "src": "GB50352-2019 6.8.9 条文说明", "conf": "规范"},
}


# ══════════════════════════════════════════════════════════════
# 自动核对
# ══════════════════════════════════════════════════════════════
def check_door(width: float, height: float, kind: str = "卧室门") -> list[dict]:
    """核对一个门洞。返回问题列表（空 = 通过）。

    只对 `conf="规范"` 的项硬判；尺寸在规范值之上不算错（门可以更大）。
    """
    out = []
    spec = DOORS.get(kind)
    if spec is None:
        return [{"level": "info", "msg": f"未知门类型 {kind}，未核对"}]
    if width < spec["w"]:
        out.append({"level": "问", "what": f"{kind}宽度",
                    "got": width, "want": spec["w"],
                    "src": spec["src"],
                    "msg": f"{kind}洞口宽 {width:.0f} < 规范最小 {spec['w']}mm（{spec['src']}）"})
    if height < spec["h"]:
        out.append({"level": "问", "what": f"{kind}高度",
                    "got": height, "want": spec["h"],
                    "src": spec["src"],
                    "msg": f"{kind}洞口高 {height:.0f} < 规范最小 {spec['h']}mm（{spec['src']}）"})
    return out


def check_stair(riser: float, tread: float, width: float = None,
                sides: str = "one_open", n_risers: int = None) -> list[dict]:
    """核对套内楼梯。sides: 'one_open' 一边临空 / 'two_wall' 两侧有墙。"""
    out = []
    r = STAIR["踏步高_max"]["v"]
    t = STAIR["踏步宽_min"]["v"]
    if riser > r:
        out.append({"level": "问", "what": "踏步高", "got": riser, "want": f"≤{r}",
                    "src": STAIR["踏步高_max"]["src"],
                    "msg": f"踏步高 {riser:.0f} > 规范最大 {r}mm"})
    if tread < t:
        out.append({"level": "问", "what": "踏步宽", "got": tread, "want": f"≥{t}",
                    "src": STAIR["踏步宽_min"]["src"],
                    "msg": f"踏步宽 {tread:.0f} < 规范最小 {t}mm"})
    if width is not None:
        key = "套内_一边临空_净宽_min" if sides == "one_open" else "套内_两侧有墙_净宽_min"
        m = STAIR[key]["v"]
        if width < m:
            out.append({"level": "问", "what": "梯段净宽", "got": width, "want": f"≥{m}",
                        "src": STAIR[key]["src"],
                        "msg": f"梯段净宽 {width:.0f} < 规范最小 {m}mm（{'一边临空' if sides=='one_open' else '两侧有墙'}）"})
    if n_risers is not None:
        if n_risers < STAIR["每梯段级数_min"]["v"] or n_risers > STAIR["每梯段级数_max"]["v"]:
            out.append({"level": "问", "what": "梯段级数", "got": n_risers,
                        "want": f"{STAIR['每梯段级数_min']['v']}~{STAIR['每梯段级数_max']['v']}",
                        "src": STAIR["每梯段级数_max"]["src"],
                        "msg": f"梯段 {n_risers} 级，规范要求 3~18 级"})
    # 步距自检（2r+g）
    if riser and tread:
        step = 2 * riser + tread
        lo, hi = STAIR["步距_舒适范围"]["lo"], STAIR["步距_舒适范围"]["hi"]
        if not (lo <= step <= hi):
            out.append({"level": "提示", "what": "步距", "got": step, "want": f"{lo}~{hi}",
                        "src": STAIR["步距_舒适范围"]["src"],
                        "msg": f"步距 2r+g = {step:.0f}mm，舒适范围 {lo}~{hi}mm"})
    return out


def check_room_height(clear_h: float, kind: str = "卧室") -> list[dict]:
    """核对室内净高。kind: 卧室/起居室/厨房/卫生间。"""
    key = "厨房卫生间净高_min" if kind in ("厨房", "卫生间") else "卧室起居室净高_min"
    m = HEIGHT[key]["v"]
    if clear_h < m:
        return [{"level": "问", "what": f"{kind}净高", "got": clear_h, "want": f"≥{m}",
                 "src": HEIGHT[key]["src"],
                 "msg": f"{kind}净高 {clear_h:.0f} < 规范最小 {m}mm（{HEIGHT[key]['src']}）"}]
    return []


def lamp_spacing_max(lamp_type: str, mount_h: float, work_plane: float = 750) -> dict:
    """灯具最大间距。用户问的"间隔不能少于多少"——

    ⚠️ 规范**没有**间距下限。间距是**上限**问题（均匀度）：
           S ≤ 距离比 × (安装高度 − 工作面高度)
    所以这里返回的是**上限**，不是下限。要"不能少于"是问反了。
    """
    ratio = LAMP_SPACING.get(f"距离比_{lamp_type}")
    if ratio is None:
        return {"error": f"未知灯具类型 {lamp_type}",
                "known": [k[4:] for k in LAMP_SPACING if k.startswith("距离比_")]}
    h = mount_h - work_plane
    return {"s_max": ratio * h, "ratio": ratio, "H": h,
            "formula": LAMP_SPACING["formula"], "conf": LAMP_SPACING["conf"],
            "note": "这是**上限**；规范不规定间距下限"}


# ══════════════════════════════════════════════════════════════
# 8. 无障碍（GB 50763-2012《无障碍设计规范》）
# ══════════════════════════════════════════════════════════════
# 用户说"这俩大概查一下就行了" —— 所以这里是**参考数据**，
# 用的是通行引用的数值，**我没去核条文原文**，全部标 `通行`。
# 用途：润色时如果要加无障碍设施，按这些值来，别拍脑袋。
ACCESSIBILITY = {
    "门净宽_min":        {"v": 800,  "conf": "通行", "note": "轮椅通行"},
    "走道净宽_min":      {"v": 1200, "conf": "通行"},
    "轮椅回转直径_min":  {"v": 1500, "conf": "通行", "note": "Φ1500 的圆"},
    "坡道_坡度_max":     {"v": 1 / 12, "unit": "", "conf": "通行",
                       "note": "1:12；受场地限制时 1:10~1:8 需加设中间平台"},
    "坡道_每段最大升高": {"v": 750, "conf": "通行", "note": "超过要设休息平台"},
    "坡道_扶手高":       {"v": 850, "conf": "通行", "note": "设上下两层，下层 650"},
    "坡道_扶手下层高":   {"v": 650, "conf": "通行"},
    "扶手_端部水平延伸": {"v": 300, "conf": "通行"},
    "门槛高_max":        {"v": 15,  "conf": "通行", "note": "且应做斜面"},
    "src": "GB50763-2012（**数值未核原文，标通行**）",
}


# ══════════════════════════════════════════════════════════════
# 9. 防火（GB 50016-2014《建筑设计防火规范》）
# ══════════════════════════════════════════════════════════════
# 同上：**参考数据**，未核原文，标 `通行`。
# 注意：这一类比无障碍更严肃 —— 真出事是要负责的。
# 所以这里只放**最粗的判据**，细节必须让用户查规范。
FIRE = {
    "疏散门_开启方向": {"v": "朝疏散方向", "conf": "通行",
                   "note": "疏散门必须朝疏散方向开启（不能内开挡路）"},
    "疏散门_净宽_min":  {"v": 900, "conf": "通行"},
    "疏散楼梯_净宽_min": {"v": 1100, "conf": "通行"},
    "住宅_疏散距离_max": {"v": 22000, "conf": "通行",
                     "note": "户门到最近安全出口；**不同建筑类型差别很大**，"
                             "这里只是住宅的粗值，必须按实际查表"},
    "楼梯间_形式":      {"v": None, "conf": "通行",
                     "note": "多层住宅通常封闭楼梯间；高层要防烟楼梯间。"
                             "**这一条必须问用户建筑高度与层数**"},
    "src": "GB50016-2014（**数值未核原文，标通行**）",
}


# ══════════════════════════════════════════════════════════════
# 10. 采光通风（GB 50033 / GB 50096）
# ══════════════════════════════════════════════════════════════
DAYLIGHT = {
    "窗地面积比_卧室起居室_min": {"v": 1 / 7, "unit": "", "conf": "通行",
                            "note": "窗洞口面积 / 房间地面面积"},
    "窗地面积比_厨房_min":      {"v": 1 / 10, "unit": "", "conf": "通行"},
    "采光_侧窗进深比":          {"v": None, "conf": "通行",
                            "note": "单侧采光时房间进深不宜大于窗上沿高度的 2 倍"},
    "src": "GB50033 / GB50096（**数值未核原文，标通行**）",
}


# ══════════════════════════════════════════════════════════════
# 润色提案：平面里没写的，按规范补一个**说得过去的**值
# ══════════════════════════════════════════════════════════════
#
# ⚠️ 这一段和下面的 `check_*` **方向相反**，别混：
#
#   check_*        "你已经写了 X，我核对合不合规"   → 不合规要问
#   suggest_*      "你没写 X，我提议补一个值"        → 要不要加，问用户
#
# 用户的定位说得很清楚：
#   "主要还是根据平面图来做模型，查这些规范是为了**润色**，
#    平面图里没加的你问用户要不要加，**润色的时候不要超乎常理**"
#
# 所以这里的值不追求"最优"，只追求"**说得过去**"——
# 让模型看起来像个正常的房子，而不是一堆裸几何。
SUGGEST_RULES = {
    "wall_height": {
        "why": "墙高在**平面图上不会标注**（那是立面/剖面信息），"
               "所以这个数是我按常规取的，必须让你确认",
        "value": 2800,
        "ask": "层高按 2800mm 做吗？（GB50096 5.5.1「住宅层高宜为 2.80m」）",
        "from": "GB50096-2011 5.5.1",
        "conf": "规范",
    },
    "window_sill": {
        "why": "平面图画窗只画个洞，**不写窗台高**；但窗台高决定这个窗"
               "是普通窗、落地窗还是幕墙，直接影响立面",
        "value": 900,
        "ask": "这些窗的窗台高按 900mm 做吗？（≥900 就不必另加防护栏杆）",
        "from": "GB50096-2011 5.8.1（窗台 <900 必须设防护设施，"
                "所以 900 是「不用另做栏杆」的最小值）",
        "conf": "规范",
    },
    "door_kind_default": {
        "why": "不同部位的门规范尺寸不同（户门 1000、卫生间门 700），"
               "平面图上常常只画个洞不写是哪一类",
        "value": 900,
        "ask": "没标注的门，我按卧室门（900×2100）做吗？"
               "入户门要 1000、卫生间门 700，哪个位置不对请告诉我",
        "from": "GB50096-2011 表5.8.7",
        "conf": "规范",
    },
    "door_leaf": {
        "why": "平面图上常常只画一个门洞（连开启弧线都没有），"
               "**没有门扇的话模型上就是一个洞**，看着不像房子",
        "value": 40,
        "ask": "要给这些门洞加上门扇吗？（厚 40mm，贴洞口一侧，底部留 20mm 缝）",
        "from": "通行做法（门扇厚 40）；门洞尺寸见 GB50096 表5.8.7",
        "conf": "通行",
    },
    "railing": {
        "why": "栏杆在平面图上要么不画、要么只画一条线，**高度与分格完全读不出来**；"
               "但它是安全构件，漏了模型就是错的",
        "value": {"h": 1050, "gap": 110},
        "ask": "临空处要加栏杆吗？按高 1050mm、竖杆净距 ≤110mm 做"
               "（6 层及以下 1050；7 层以上要 1100。净距 110 是防小孩穿过/攀登）",
        "from": "GB50096-2011 6.1.3（外廊/内天井/上人屋面：6层及以下 ≥1050，"
                "7层及以上 ≥1100；垂直杆件净距 ≤110）",
        "conf": "规范",
    },
    "slab_thickness": {
        "why": "平面图不标板厚（那是结构图的事）",
        "value": {"floor": 100, "roof": 150},
        "ask": "楼板按 100 厚、屋顶板按 150 厚做吗？",
        "from": "通行做法（住宅现浇板 100~120）",
        "conf": "通行",
    },
    "skirting": {
        "why": "实建房子墙脚都有踢脚线，模型上加一圈会明显更像成品",
        "value": {"h": 100, "th": 15},
        "ask": "要加踢脚线吗？（高 100、出墙 15）纯装饰，不加也不影响结构",
        "from": "通行做法",
        "conf": "通行",
    },
    "entrance_step": {
        "why": "入户门外面一般有一步台阶（室内外高差）",
        "value": {"tread": 300, "riser": 150},
        "ask": "入户门外要加一步台阶吗？（踏面 300、高 150）",
        "from": "GB50096-2011 6.1.4（踏面不宜 <300，高不宜 >150）",
        "conf": "规范",
    },
    "furniture": {
        "why": "平面图上家具通常只是一堆轮廓线，读不准；但**空房间不像住宅**",
        "value": None,
        "ask": "要按房间用途补一套常规家具吗？"
               "（床 1500×2000、桌 800×1400、衣柜深 600 —— 都是通行规格，"
               "不满意可以逐个改）",
        "from": "通行规格（见 plan_schema.md 的 FURNITURE_STD）",
        "conf": "通行",
    },
    "lighting": {
        "why": "**平面图上不会有灯**，但没灯的模型点开是黑的、也不像家。"
               "照度按房间用途定，间距按距离比反推",
        "value": None,
        "ask": "要我按房间用途布一套灯吗？"
               "（照度按 GB50034：起居室 100lx、卧室 75lx、厨房操作台 500lx；"
               "间距按距离比，如宽配光筒灯 0.7 × 层高）",
        "from": "GB50034-2013（照度值未取到原文，标通行）+ 距离比通行取值",
        "conf": "通行",
    },
}


def suggest_additions(data: dict) -> list[dict]:
    """看平面里**缺什么**，逐条提议补上（带理由与出处）。

    与 `check_plan` 的区别（方向相反）：
      check_plan        → "你写了 X，但不合规"
      suggest_additions → "你没写 X，要不要我补一个说得过去的值"

    返回结构与 `check_plan` 一致，可直接并进疑问清单。
    """
    out: list[dict] = []
    seen: set = set()

    def add(key, at, ask=None):
        if key in seen:
            return
        seen.add(key)
        r = SUGGEST_RULES[key]
        out.append({"at": at, "why": r["why"], "ask": ask or r["ask"],
                    "src": r["from"], "level": "润色",
                    "conf": r["conf"], "suggest": r["value"]})

    walls = data.get("walls") or []
    rooms = data.get("rooms") or []
    stairs = data.get("stairs") or []
    furn = data.get("furniture") or []

    # ⚠️ **墙高不在这里问** —— Ruby 侧 `questions_for` 已经问了
    # （"墙高在平面图上不会标注…涉及 8 面墙"）。
    # 我第一版又加了一条，结果同一个问题问两遍（实测第 1 条和第 4 条）。
    # 规矩：**同一个问题只能有一个源头**，否则清单会重复、用户会以为有两处问题。
    # 这里只保留 Ruby 没有的东西。

    # 窗台高
    #
    # ⚠️ 判据必须是「**字段缺失**」，不能是「sill 为假」。
    # 踩过：`o.get('sill')` 对 `sill: 0` 也返回假，于是把
    # 「**明确写了落地（窗台 0）**」误判成「**没写窗台高**」——
    # 同一批玻璃一边被识别为落地通高（check_plan 那条），
    # 一边又被问「窗台按 900 做吗」，**自相矛盾**，
    # 用户会以为有两处问题，其实只有一处。
    win = [f"{w.get('name','墙')}/{o.get('label','洞')}"
           for w in walls for o in (w.get("openings") or [])
           if (o.get("type") or "").lower() in ("window", "窗")
           and "sill" not in o]
    if win:
        add("window_sill", f"{len(win)} 处窗洞（{win[0]} 等）")

    # 门：类别与门扇
    doors = [(w, o) for w in walls for o in (w.get("openings") or [])
             if (o.get("type") or "").lower() in ("door", "门")]
    if doors:
        add("door_kind_default", f"{len(doors)} 处门洞没标类别")
        if not any(w.get("joinery") for w, _ in doors):
            add("door_leaf", f"{len(doors)} 处门洞")

    # 栏杆：有落地洞口 / 楼梯
    open_below = [w.get("name", "墙") for w in walls
                  for o in (w.get("openings") or [])
                  if (o.get("type") or "").lower() in ("window", "窗")
                  and not o.get("sill") and (w.get("height") or 0)
                  and (o.get("height") or 0) >= (w.get("height") or 0) - 1]
    if open_below or stairs:
        where = (f"落地洞口（{len(open_below)} 处）" if open_below
                 else f"楼梯（{len(stairs)} 部）")
        add("railing", where)

    # 板厚
    if (data.get("floors") or []) and not any(f.get("thickness")
                                              for f in data["floors"]):
        add("slab_thickness", f"{len(data['floors'])} 块楼板")

    # 家具
    if rooms and not furn:
        add("furniture", f"{len(rooms)} 个房间都是空的")

    # 灯具（总是提议）
    add("lighting", f"{len(rooms) or len(walls)} 个空间")

    return out


# ══════════════════════════════════════════════════════════════
# 拿整份 plan 数据做核对（生成器直接调这个）
# ══════════════════════════════════════════════════════════════
def check_plan(data: dict) -> list[dict]:
    """核对整份平面数据，返回与 Ruby 侧 `questions_for` **同结构**的条目。

    键对齐：{at, why, ask, src, level}
    这样 Python 侧直接并进疑问清单，不用改渲染代码。
    """
    out: list[dict] = []

    def add(at, why, ask, src, level="规范"):
        out.append({"at": at, "why": why, "ask": ask, "src": src, "level": level})

    def add_grouped(at, why, ask, src, level="规范"):
        """同一类问题**合并成一条**，避免刷屏。

        实测踩到：4 面外墙各一个落地玻璃，于是问了 4 遍一模一样的话。
        用户的清单应该是"这一类有几处"，不是把同一句话说 N 遍。
        """
        for q in out:
            if q["ask"] == ask and q["level"] == level:
                q["at"] += f"；{at}"
                q["count"] = q.get("count", 1) + 1
                return
        out.append({"at": at, "why": why, "ask": ask, "src": src,
                    "level": level, "count": 1})

    # ── 墙上的洞口：按 type + 尺寸核对门 / 窗
    for w in (data.get("walls") or []):
        wn = w.get("name", "墙")
        wh = w.get("height") or 0
        for i, o in enumerate(w.get("openings") or [], 1):
            label = o.get("label") or f"{wn}-洞{i}"
            typ = (o.get("type") or "").lower()
            wd = o.get("width")
            ht = o.get("height")
            sill = o.get("sill") or 0

            if typ in ("door", "门"):
                if wd:
                    kind = _door_kind(wn, label)
                    for iss in check_door(wd, ht or 2100, kind):
                        if iss["level"] == "问":
                            add(f"{wn} / {label}",
                                f"不合规范：{iss['msg']}",
                                f"这个门的洞口宽能改成 ≥{iss['want']}mm 吗？"
                                f"还是图纸上确实就这么宽？",
                                iss["src"])
                # 5.8.6 厨房/卫生间门必须能进风
                if any(k in (wn + label) for k in ("厨房", "卫生间", "卫", "厕")):
                    add(f"{wn} / {label}",
                        f"规范的强制要求：{KITCHEN_BATH_DOOR_GAP['src']} 规定厨房/"
                        f"卫生间门下部要能进风（有效截面积 ≥0.02m² 的固定百叶，"
                        f"或距地 ≥30mm 缝隙），否则排油烟机 / 排风扇抽不动",
                        "这个门留 30mm 门槛缝，还是做百叶？"
                        "（不留则不达标，但这是你的房子，你说了算）",
                        KITCHEN_BATH_DOOR_GAP["src"])

            elif typ in ("window", "窗"):
                if sill and sill < WINDOW["sill_protect_below"]["v"]:
                    add(f"{wn} / {label}",
                        f"窗台高 {sill:.0f} < 900mm，{WINDOW['sill_protect_below']['src']} "
                        f"要求「窗外无阳台或平台时」必须设防护设施",
                        "这个窗台设栏杆 / 防护玻璃吗？还是外面其实有平台？",
                        WINDOW["sill_protect_below"]["src"])
                # 通高洞口（落地到顶）—— 它的属性不是普通窗
                if sill <= 1 and wh and ht and ht >= wh - 1:
                    add_grouped(f"{wn} / {label}",
                        "这是个**落地通高**洞口（窗台 0、到顶）。按 GB50096 5.8.1 "
                        "它落在临空防护的范围里，但落地玻璃幕墙的构造做法与普通窗不同",
                        "这是落地玻璃幕墙，还是普通落地窗？"
                        "（按幕墙算的话，玻璃厚度与分格都不一样）",
                        "GB50096-2011 5.8.1", "属性")

    # ── 楼梯
    import math
    for s in (data.get("stairs") or []):
        sn = s.get("name", "楼梯")
        h = s.get("height") or 0
        steps = s.get("steps") or 0
        kind = (s.get("kind") or "").lower()
        r = s.get("radius")
        if kind in ("spiral", "螺旋") or r:
            if h and steps and r:
                riser = h / steps
                deg = (s.get("total_deg") or 360.0) / steps
                tread250 = math.radians(deg) * 250
                need = STAIR["扇形踏步_0.25m处宽_min"]["v"]
                if tread250 < need:
                    need_deg = need / 250.0
                    add(f"{sn}（螺旋楼梯）",
                        f"几何上做不到规范：半径 {r:.0f}、{steps} 级 → 每级转 {deg:.1f}°，"
                        f"距中心 250mm 处踏面只有 {tread250:.0f}mm，规范要 ≥{need}mm。"
                        f"要满足 {need}mm，每级得转 {math.degrees(need_deg):.1f}°，"
                        f"一圈最多 {int(360/math.degrees(need_deg))} 级 —— "
                        f"那样踏步高 {h/max(1,int(360/math.degrees(need_deg))):.0f}mm，"
                        f"又超过 {STAIR['踏步高_max']['v']}mm 上限",
                        f"三条路选一条：① 加大半径到 "
                        f"{need/math.radians(deg):.0f}mm 以上；② 改成直跑 / 折跑楼梯；"
                        f"③ 接受不合规，我照建但在报告里标出来",
                        STAIR["扇形踏步_0.25m处宽_min"]["src"])
                if riser > STAIR["踏步高_max"]["v"]:
                    add(f"{sn}（螺旋楼梯）",
                        f"踏步高 {riser:.0f} > 规范上限 {STAIR['踏步高_max']['v']}mm",
                        "要增加级数，还是这就是你想要的？",
                        STAIR["踏步高_max"]["src"])
        elif h and steps:
            riser = h / steps
            tread = s.get("run") or s.get("tread")
            width = s.get("width")
            sides = "two_wall" if s.get("between_walls") else "one_open"
            for iss in check_stair(riser, tread or 9999, width, sides, steps):
                if iss["level"] == "问":
                    add(f"{sn}（楼梯）", f"不合规范：{iss['msg']}",
                        f"这个尺寸能调整到 {iss['want']} 吗？", iss["src"])

    # ── 房间净高
    for room in (data.get("rooms") or []):
        ch = room.get("ceiling_height")
        if not ch:
            continue
        th = room.get("floor_thickness") or 100
        ct = room.get("ceiling_thickness") or 100
        clear = ch - th - ct
        nm = room.get("name", "房间")
        kind = "厨房" if "厨" in nm else ("卫生间" if ("卫" in nm or "厕" in nm) else "卧室")
        for iss in check_room_height(clear, kind):
            add(f"房间 {nm}",
                f"{iss['msg']}（层高 {ch:.0f} − 地面厚 {th:.0f} − 天花厚 {ct:.0f} "
                f"= 净高 {clear:.0f}）",
                f"层高要提到 {iss['want'].lstrip('≥')}mm 以上吗？", iss["src"])
    return out


def _door_kind(wall_name: str, label: str) -> str:
    """按墙名 / 洞口名猜门的类别（用来选对应规范值）。"""
    s = f"{wall_name}{label}"
    if any(k in s for k in ("户门", "入户", "大门", "entry")):
        return "户门"
    if "厨" in s:
        return "厨房门"
    if any(k in s for k in ("卫", "厕", "浴")):
        return "卫生间门"
    if any(k in s for k in ("阳台", "露台")):
        return "阳台门"
    if any(k in s for k in ("起居", "客厅", "厅")):
        return "起居室门"
    return "卧室门"


if __name__ == "__main__":
    import json
    print("== 住宅规范硬数字（每条带出处）")
    for k, v in DOORS.items():
        if v.get("conf") == "规范":
            print(f"  门 {k:<8} {v['w']}×{v['h']}mm   {v['src']}")
    print()
    print("== 楼梯")
    for k in ("踏步宽_min", "踏步高_max", "套内_一边临空_净宽_min",
              "套内_两侧有墙_净宽_min", "梯段净高_min", "每梯段级数_max"):
        v = STAIR[k]
        print(f"  {k:<24} {v['v']}{v.get('unit','mm')}   {v['src']}")
    print()
    print("== 净高")
    for k in ("层高_宜", "卧室起居室净高_min", "局部净高_min", "厨房卫生间净高_min"):
        v = HEIGHT[k]
        print(f"  {k:<22} {v['v']}mm   {v['src']}")
    print()
    print("== 自检示例")
    print("  1.0×2.1 户门 :", check_door(1000, 2100, "户门") or "✅")
    print("  0.7×2.1 卧室门:", check_door(700, 2100, "卧室门"))
    print("  踏步 200/220  :", check_stair(200, 220, 900, "two_wall", 16) or "✅")
    print("  踏步 250/180  :", check_stair(250, 180, 700, "one_open", 20))
    print()
    print("== 灯具间距（用户问的那条）")
    print(" ", json.dumps(lamp_spacing_max("筒灯_宽配光", 2600), ensure_ascii=False))
