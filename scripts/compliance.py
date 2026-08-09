#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
电商文案合规检查器 —— 扫描广告法违禁词、极限词与需资质用语。

依据《中华人民共和国广告法》（2021 修正）第九条、第十七条、第二十八条
及市场监管总局相关执法口径。第九条明确禁止使用"国家级""最高级""最佳"
等绝对化用语，实践中单条罚则起点为二十万元，是电商文案最高频的翻车点。

风险分级:
  P0 明令禁止 —— 绝对化用语、虚假权威背书，命中即违法，必须删改
  P1 需要资质 —— 有对应批准文号/证明材料方可使用，否则构成违规
  P2 真实性约束 —— 内容必须真实可自证，无法举证即构成虚假宣传

用法:
  python compliance.py --text "全网最低价，第一品牌，100%纯天然"
  python compliance.py --file detail.txt
  python compliance.py --text "..." --json
  python compliance.py --list-rules
  python compliance.py --self-test

注意: 本工具用于风险自查提示，不构成法律意见；最终以监管部门认定为准。
"""

from __future__ import annotations

import argparse
import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ---------------------------------------------------------------
# 违禁词库: 词 -> (风险级别, 类别, 建议替代)
# ---------------------------------------------------------------
RULES: dict[str, tuple[str, str, str]] = {}


def _add(words, level, category, suggest):
    for w in words:
        RULES[w] = (level, category, suggest)


# --- P0 绝对化用语（广告法第九条明令禁止）---
_add(["国家级", "国家免检", "宇宙级", "世界级", "全球级"],
     "P0", "绝对化-权威级别", "删除该表述，或改为具体可证的资质名称")
_add(["最高级", "最高", "最佳", "最好", "最优", "最强", "最大", "最小",
      "最低", "最新", "最先进", "最先", "最流行", "最受欢迎", "最便宜",
      "最划算", "最值", "最热", "最火"],
     "P0", "绝对化-最字系", "改为「优选」「热销」「高性价比」等相对表述")
_add(["第一", "排名第一", "销量第一", "行业第一", "全国第一", "天下第一",
      "全网第一", "NO.1", "no.1", "TOP1", "top1"],
     "P0", "绝对化-排名", "改为「热销款」「多人选择」，或标注可查证的榜单来源")
_add(["唯一", "独一无二", "绝无仅有", "空前绝后", "史无前例", "前无古人",
      "举世无双", "无与伦比", "无可比拟", "不可替代"],
     "P0", "绝对化-唯一性", "改为「少见」「独特设计」「差异化」")
_add(["顶级", "极品", "极致", "终极", "巅峰", "至尊", "王牌", "王者",
      "领袖", "冠军", "之王", "之最", "霸主", "神器"],
     "P0", "绝对化-顶级系", "改为「高品质」「进阶款」「主推款」")
_add(["100%", "百分百", "百分之百", "绝对", "彻底", "完全", "永久",
      "终身", "万能", "全能"],
     "P0", "绝对化-程度", "改为「严格质检」「长效」，并给出具体可验证指标")
_add(["全网最低价", "全网最低", "史上最低", "史上最强", "全国最大",
      "全球首发", "国际品质", "世界领先", "行业领先", "领先品牌"],
     "P0", "绝对化-复合", "改为「本店活动价」「近期优惠价」等可自证表述")
_add(["驰名商标"],
     "P0", "禁止性标识", "广告法第十四条禁止用于商品宣传，必须删除")

# --- P1 需资质/证明文件 ---
_add(["专利产品", "专利技术", "国家专利"],
     "P1", "需专利号", "必须标注专利号与专利类型，且专利处于有效状态")
_add(["中国驰名", "老字号", "非物质文化遗产", "有机食品", "绿色食品",
      "国家认证", "权威认证", "官方认证", "质量免检"],
     "P1", "需认证文件", "须持有对应认证证书并在有效期内，建议标注证书编号")
_add(["专家推荐", "医生推荐", "CCTV推荐", "央视推荐", "明星同款",
      "政府推荐", "机构推荐"],
     "P1", "需授权证明", "须有被引用方书面授权；医疗人员形象不得用于食品药品广告")
_add(["特供", "专供", "军供", "内供"],
     "P1", "禁用性表述", "禁止使用国家机关名义，建议整体删除")

# --- P1 医疗功效（食品/化妆品/日用品不得宣称）---
_add(["治疗", "疗效", "治愈", "根治", "药到病除", "包治", "特效",
      "抗癌", "防癌", "抑制肿瘤", "消炎", "杀菌", "抗菌", "灭菌",
      "解毒", "排毒", "壮阳", "补肾", "生发", "防脱发"],
     "P1", "医疗功效用语", "非药品/械字号不得宣称疗效，改为「清洁」「护理」「舒缓」")
_add(["减肥", "瘦身", "燃脂", "溶脂", "丰胸", "美白", "祛斑", "祛痘",
      "抗皱", "除皱", "生肌", "修复受损"],
     "P1", "特殊化妆品功效", "美白/祛斑属特殊化妆品，须有国妆特字批准文号")
_add(["无副作用", "无毒副作用", "安全无害", "纯天然无添加", "零添加"],
     "P1", "安全性断言", "须有检测报告支撑，「零添加」需符合食品标签相关规定")

# --- P2 真实性约束 ---
_add(["限时抢购", "仅此一天", "最后一天", "限量", "秒杀", "清仓",
      "倒计时", "错过再无", "即将涨价", "亏本甩卖", "跳楼价"],
     "P2", "促销真实性", "活动时间与库存必须真实，虚构倒计时构成价格欺诈")
_add(["原价", "划线价", "市场价", "厂家指导价", "专柜价"],
     "P2", "价格标注", "须为真实成交过的价格，否则违反明码标价规定")
_add(["点击有礼", "转发有礼", "关注有礼", "免费送", "0元购"],
     "P2", "赠送真实性", "赠品规则须明示且可兑现，不得设置隐性门槛")
_add(["销量冠军", "爆款", "网红同款", "断货王", "回头客最多"],
     "P2", "数据可证性", "涉及销量排名须有平台数据支撑，建议改为「热销中」")

# --- P2 迷信/低俗 ---
_add(["辟邪", "转运", "改运", "招财", "旺夫", "旺财", "保平安",
      "增强气场", "开光"],
     "P2", "封建迷信", "宣扬迷信内容违反广告法第九条，建议改为「工艺摆件」")


LEVEL_DESC = {
    "P0": "明令禁止 - 命中即违法，必须立即删改",
    "P1": "需要资质 - 无对应文件则构成违规",
    "P2": "真实性约束 - 无法举证即属虚假宣传",
}


def check(text: str, min_level: str = "P2") -> dict:
    """
    扫描文本中的违禁词。

    text       待检查的文案
    min_level  最低报告级别，P0 只报最高危，P2 报全部
    返回命中列表与统计。
    """
    if not isinstance(text, str):
        raise ValueError("待检查内容必须是字符串")

    order = {"P0": 0, "P1": 1, "P2": 2}
    if min_level not in order:
        raise ValueError(f"min_level 必须是 P0/P1/P2 之一，收到 {min_level}")
    threshold = order[min_level]

    lower = text.lower()
    hits = []
    for word, (level, category, suggest) in RULES.items():
        if order[level] > threshold:
            continue
        target = word.lower()
        start = 0
        positions = []
        while True:
            idx = lower.find(target, start)
            if idx == -1:
                break
            positions.append(idx)
            start = idx + 1
        if positions:
            ctx_list = []
            for pos in positions[:3]:
                a = max(0, pos - 8)
                b = min(len(text), pos + len(word) + 8)
                ctx_list.append(text[a:b].replace("\n", " "))
            hits.append({
                "违禁词": word,
                "风险级别": level,
                "类别": category,
                "出现次数": len(positions),
                "位置": positions[:5],
                "上下文": ctx_list,
                "整改建议": suggest,
            })

    # 去重：若长词已命中，剔除被其完全包含的短词（如"全网最低价"含"最低"）
    hits.sort(key=lambda h: len(h["违禁词"]), reverse=True)
    kept: list[dict] = []
    for h in hits:
        if any(h["违禁词"] in k["违禁词"] and h["违禁词"] != k["违禁词"]
               and set(h["位置"]) & {p + k["违禁词"].lower().find(h["违禁词"].lower())
                                     for p in k["位置"]}
               for k in kept):
            continue
        kept.append(h)

    kept.sort(key=lambda h: (order[h["风险级别"]], -h["出现次数"]))
    counts = {lv: sum(1 for h in kept if h["风险级别"] == lv)
              for lv in ("P0", "P1", "P2")}

    if counts["P0"] > 0:
        verdict, risk = "高危不可发布", "存在广告法明令禁止用语，发布即面临处罚风险"
    elif counts["P1"] > 0:
        verdict, risk = "需提供资质", "含需资质用语，无证明文件不得使用"
    elif counts["P2"] > 0:
        verdict, risk = "需自证真实", "含真实性约束用语，须确保内容可举证"
    else:
        verdict, risk = "通过", "未检出已知违禁词"

    return {
        "文本长度": len(text),
        "检出总数": len(kept),
        "分级统计": counts,
        "结论": verdict,
        "风险说明": risk,
        "命中明细": kept,
    }


def render(r: dict) -> str:
    L = ["=" * 64, "               电商文案合规检查报告", "=" * 64]
    c = r["分级统计"]
    L.append(f"文本长度 {r['文本长度']} 字 | 检出 {r['检出总数']} 处 | "
             f"P0:{c['P0']}  P1:{c['P1']}  P2:{c['P2']}")
    L.append("")
    L.append(f"[结论] {r['结论']} —— {r['风险说明']}")
    L.append("")
    if not r["命中明细"]:
        L.append("  未检出已知违禁词。仍建议人工复核夸大表述与竞品贬低内容。")
        L.append("=" * 64)
        return "\n".join(L)

    cur = None
    for h in r["命中明细"]:
        if h["风险级别"] != cur:
            cur = h["风险级别"]
            L.append(f"--- {cur} {LEVEL_DESC[cur]} ---")
        L.append(f"  * 「{h['违禁词']}」x{h['出现次数']}  [{h['类别']}]")
        for ctx in h["上下文"]:
            L.append(f"      原文: ...{ctx}...")
        L.append(f"      建议: {h['整改建议']}")
    L.append("")
    L.append("=" * 64)
    L.append("免责声明: 本结果为风险自查提示，不构成法律意见。")
    L.append("部分词汇在特定语境下可合规（如已取得批准文号），请结合实际判断。")
    return "\n".join(L)


def _self_test() -> int:
    print("运行 compliance.py 自检...")
    ok = True

    # 用例1: P0 绝对化词必须检出
    r1 = check("本店全网最低价，销量第一，品质最好")
    if r1["分级统计"]["P0"] == 0:
        print("  [FAIL] 用例1 未检出P0违禁词"); ok = False
    else:
        print(f"  [PASS] 用例1 检出P0违禁词 {r1['分级统计']['P0']} 个")

    # 用例2: 合规文案不应误报
    r2 = check("这款棉质衬衫版型修身，适合日常通勤穿着，支持七天无理由退换。")
    if r2["检出总数"] != 0:
        print(f"  [FAIL] 用例2 合规文案误报: "
              f"{[h['违禁词'] for h in r2['命中明细']]}"); ok = False
    else:
        print("  [PASS] 用例2 合规文案零误报")

    # 用例3: 结论分级正确
    if r1["结论"] != "高危不可发布":
        print(f"  [FAIL] 用例3 结论应为高危 实际{r1['结论']}"); ok = False
    else:
        print("  [PASS] 用例3 高危结论判定")

    # 用例4: P1 医疗功效词检出
    r4 = check("本产品可消炎杀菌，根治各类皮肤问题")
    if r4["分级统计"]["P1"] == 0:
        print("  [FAIL] 用例4 未检出医疗功效词"); ok = False
    else:
        print("  [PASS] 用例4 医疗功效词检出")

    # 用例5: min_level 过滤生效
    r5 = check("限时抢购，最后一天", min_level="P0")
    if r5["检出总数"] != 0:
        print(f"  [FAIL] 用例5 P0过滤失效，误报"
              f"{[h['违禁词'] for h in r5['命中明细']]}"); ok = False
    else:
        print("  [PASS] 用例5 级别过滤生效")

    # 用例6: 次数统计准确
    r6 = check("最好最好最好")
    hit = next((h for h in r6["命中明细"] if h["违禁词"] == "最好"), None)
    if not hit or hit["出现次数"] != 3:
        print(f"  [FAIL] 用例6 次数统计错误 {hit}"); ok = False
    else:
        print("  [PASS] 用例6 重复词计数准确")

    # 用例7: 大小写不敏感
    r7 = check("我们是行业 no.1 的品牌")
    if r7["分级统计"]["P0"] == 0:
        print("  [FAIL] 用例7 小写no.1未检出"); ok = False
    else:
        print("  [PASS] 用例7 大小写不敏感匹配")

    # 用例8: 非法参数
    try:
        check("测试", min_level="P9")
        print("  [FAIL] 用例8 非法级别未报错"); ok = False
    except ValueError:
        print("  [PASS] 用例8 非法参数拦截")

    print(f"词库规模: {len(RULES)} 条")
    print("自检结果:", "全部通过" if ok else "存在失败")
    return 0 if ok else 1


def main() -> int:
    p = argparse.ArgumentParser(description="电商文案合规检查器")
    p.add_argument("--text", help="直接传入待检查文案")
    p.add_argument("--file", help="从文件读取文案（UTF-8）")
    p.add_argument("--min-level", default="P2", choices=["P0", "P1", "P2"],
                   help="最低报告级别，默认P2全量")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.add_argument("--list-rules", action="store_true", help="导出完整词库")
    p.add_argument("--self-test", action="store_true", help="运行内置自检")
    a = p.parse_args()

    if a.self_test:
        return _self_test()
    if a.list_rules:
        by_cat: dict[str, list[str]] = {}
        for w, (lv, cat, _) in RULES.items():
            by_cat.setdefault(f"{lv} {cat}", []).append(w)
        for cat in sorted(by_cat):
            print(f"\n[{cat}] 共{len(by_cat[cat])}词")
            print("  " + "、".join(by_cat[cat]))
        print(f"\n合计 {len(RULES)} 条")
        return 0

    text = a.text
    if a.file:
        try:
            with open(a.file, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            print(f"[错误] 无法读取文件: {e}")
            return 2
    if not text:
        p.print_help()
        print("\n[错误] 必须提供 --text 或 --file")
        return 2

    try:
        res = check(text, a.min_level)
    except ValueError as e:
        print(f"[错误] {e}")
        return 2

    print(json.dumps(res, ensure_ascii=False, indent=2) if a.json else render(res))
    # P0 命中时返回非零，便于 CI/批处理拦截
    return 1 if res["分级统计"]["P0"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
