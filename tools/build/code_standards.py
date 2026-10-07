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
