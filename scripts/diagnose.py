#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
店铺链路诊断器 —— 按转化漏斗定位真正的瓶颈环节，避免盲目投钱。

链路: 曝光 -> 点击(访客) -> 加购/收藏 -> 下单 -> 支付 -> (退款)

诊断逻辑不是看哪个数字低，而是看【哪个环节相对行业基准差得最多】。
低于基准最严重的环节即为瓶颈，优先修复它的投入产出比最高。

用法:
  python diagnose.py --impression 100000 --click 2000 --cart 150 --order 60 --paid 45
  python diagnose.py --impression 100000 --click 2000 --order 60 --paid 45 --gmv 5800
  python diagnose.py --self-test
"""

from __future__ import annotations

import argparse
import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

try:
    from platform_fees import BENCHMARK, pad
except ImportError:
    import os

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from platform_fees import BENCHMARK, pad

# 各环节的归因与处方
PRESCRIPTION = {
    "click_rate": {
        "环节": "曝光 -> 点击（点击率）",
        "归因": "主图/短视频首帧、标题、价格带、人群精准度",
        "处方": [
            "主图做3~5版A/B测试，卖点前置到左上角黄金视觉区",
            "首图加场景化利益点文字（不超过8字），避免纯白底堆参数",
            "检查展现人群是否精准，泛人群会稀释点击率",
            "价格带与同坑位竞品对比，价格明显偏高会直接压制点击",
        ],
    },
    "cart_rate": {
        "环节": "点击 -> 加购（加购率）",
        "归因": "详情页说服力、卖点与需求匹配度、信任状",
        "处方": [
            "详情页前3屏必须完成「解决什么问题+凭什么信你」",
            "补充对比图、实测数据、资质证书等信任状",
            "增加限时/限量/赠品等加购钩子",
        ],
    },
    "order_rate": {
        "环节": "点击 -> 下单（下单率）",
        "归因": "价格力、评价口碑、活动力度、竞品对比",
        "处方": [
            "检查问大家与差评，负面口碑是下单最大阻力",
            "优化优惠券门槛，让实付价踩住心理价位（如99、199）",
            "加强销量/评价等从众证据展示",
        ],
    },
    "pay_rate": {
        "环节": "下单 -> 支付（支付率）",
        "归因": "运费、优惠券失效、库存、客服响应、支付流程",
        "处方": [
            "核查是否存在运费门槛劝退，考虑包邮或满额包邮",
            "下单未付15~30分钟内触发客服催付+小额券",
            "检查地区不可售、库存不足等技术性拦截",
        ],
    },
    "refund_rate": {
        "环节": "退款率",
        "归因": "描述不符、质量问题、物流时效、尺码问题",
        "处方": [
            "退款率高于行业基准时，先看退款原因分布而非降价",
            "描述不符占比高 -> 详情页夸大，需回调预期",
            "服饰类优先补尺码表与买家秀实际身材数据",
        ],
    },
}


def _rate(a: float, b: float) -> float:
    """安全求百分比 a/b*100。"""
    return (a / b * 100) if b else 0.0


def diagnose(
    impression: float,
    click: float,
    order: float,
    paid: float,
    cart: float | None = None,
    refund: float | None = None,
    gmv: float | None = None,
) -> dict:
    """执行漏斗诊断，返回各环节指标、偏离度与处方。"""
    if impression <= 0:
        raise ValueError("曝光量必须大于 0")
    if click > impression:
        raise ValueError("点击数不能大于曝光量")
    if paid > order:
        raise ValueError("支付数不能大于下单数")

    metrics = {
        "click_rate": _rate(click, impression),
        "order_rate": _rate(order, click),
        "pay_rate": _rate(paid, order),
        "overall_cvr": _rate(paid, click),
    }
    if cart is not None:
        metrics["cart_rate"] = _rate(cart, click)
    if refund is not None:
        metrics["refund_rate"] = _rate(refund, paid)

    # 计算相对基准的偏离度：低于下限多少个百分点（相对）
    deviations = {}
    for key, val in metrics.items():
        if key not in BENCHMARK:
            continue
        lo, hi = BENCHMARK[key]
        if key == "refund_rate":
            # 退款率越低越好，超过上限才是问题
            status = "偏高" if val > hi else ("正常" if val >= lo else "优秀")
            gap = (val - hi) / hi * 100 if val > hi else 0.0
        else:
            if val < lo:
                status, gap = "偏低", (lo - val) / lo * 100
            elif val > hi:
                status, gap = "优秀", 0.0
            else:
                status, gap = "正常", 0.0
        deviations[key] = {
            "实际%": round(val, 2),
            "基准区间": f"{lo}~{hi}%",
            "状态": status,
            "偏离度%": round(gap, 1),
        }

    # 瓶颈 = 偏离度最大的环节
    problems = {k: v for k, v in deviations.items() if v["偏离度%"] > 0}
    bottleneck = max(problems, key=lambda k: problems[k]["偏离度%"]) if problems else None

    res = {
        "漏斗数据": {
            "曝光": impression, "点击": click,
            **({"加购": cart} if cart is not None else {}),
            "下单": order, "支付": paid,
            **({"退款": refund} if refund is not None else {}),
        },
        "各环节指标": deviations,
        "瓶颈环节": bottleneck,
        "健康环节数": sum(1 for v in deviations.values() if v["偏离度%"] == 0),
        "问题环节数": len(problems),
    }

    if gmv is not None and paid > 0:
        res["客单价"] = round(gmv / paid, 2)
        res["UV价值"] = round(gmv / click, 3) if click else 0.0

    if bottleneck:
        res["处方"] = PRESCRIPTION[bottleneck]
        # 提升模拟：把瓶颈环节拉到基准下限，GMV 能涨多少
        lo = BENCHMARK[bottleneck][0]
        cur = deviations[bottleneck]["实际%"]
        if bottleneck != "refund_rate" and cur > 0:
            uplift = (lo / cur - 1) * 100
            res["提升模拟"] = {
                "说明": f"若 {PRESCRIPTION[bottleneck]['环节']} 从 {cur}% "
                        f"提升至基准下限 {lo}%",
                "支付订单增幅%": round(uplift, 1),
                "预计支付单数": round(paid * lo / cur, 1),
            }
    return res


def render(r: dict) -> str:
    L = ["=" * 62, "              店铺转化链路诊断报告", "=" * 62]
    d = r["漏斗数据"]
    L.append("--- 漏斗数据 ---")
    L.append("  " + "  ->  ".join(f"{k} {v:g}" for k, v in d.items()))
    L.append("")
    L.append("--- 各环节体检 ---")
    name_map = {
        "click_rate": "点击率", "cart_rate": "加购率",
        "order_rate": "下单率", "pay_rate": "支付率",
        "overall_cvr": "整体转化率", "refund_rate": "退款率",
    }
    for k, v in r["各环节指标"].items():
        flag = {"偏低": "[!]", "偏高": "[!]", "正常": "[OK]", "优秀": "[++]"}[v["状态"]]
        extra = f" 偏离 {v['偏离度%']}%" if v["偏离度%"] > 0 else ""
        L.append(f"  {flag:<5}{pad(name_map.get(k, k), 12)}{v['实际%']:>7.2f}%  "
                 f"基准 {pad(v['基准区间'], 12)}{v['状态']}{extra}")
    L.append("")
    if "客单价" in r:
        L.append(f"  客单价 {r['客单价']} 元 | UV价值 {r['UV价值']} 元")
        L.append("")

    if r["瓶颈环节"]:
        p = r["处方"]
        L.append("--- 瓶颈定位 ---")
        L.append(f"  最大瓶颈: {p['环节']}")
        L.append(f"  可能归因: {p['归因']}")
        L.append("")
        L.append("--- 优先处方（按顺序执行）---")
        for idx, item in enumerate(p["处方"], 1):
            L.append(f"  {idx}. {item}")
        L.append("")
        if "提升模拟" in r:
            s = r["提升模拟"]
            L.append("--- 提升模拟 ---")
            L.append(f"  {s['说明']}")
            L.append(f"  支付订单可增长 {s['支付订单增幅%']}%，"
                     f"达到约 {s['预计支付单数']} 单")
    else:
        L.append("--- 诊断结论 ---")
        L.append("  各环节均在行业基准区间内，无明显短板。")
        L.append("  下一步应扩大流量入口规模，而非继续优化转化。")
    L.append("=" * 62)
    L.append("注：基准为行业经验区间，应以商家后台同层竞争对比数据校准。")
    return "\n".join(L)


def _self_test() -> int:
    print("运行 diagnose.py 自检...")
    ok = True

    # 用例1: 点击率极低(0.5%)，瓶颈必须是 click_rate
    r1 = diagnose(impression=100000, click=500, order=20, paid=15)
    if r1["瓶颈环节"] != "click_rate":
        print(f"  [FAIL] 用例1 瓶颈应为click_rate 实际{r1['瓶颈环节']}"); ok = False
    else:
        print("  [PASS] 用例1 低点击率瓶颈识别")

    # 用例2: 支付率极低(30%)，瓶颈应为 pay_rate
    r2 = diagnose(impression=100000, click=3500, order=200, paid=60)
    if r2["瓶颈环节"] != "pay_rate":
        print(f"  [FAIL] 用例2 瓶颈应为pay_rate 实际{r2['瓶颈环节']}"); ok = False
    else:
        print("  [PASS] 用例2 低支付率瓶颈识别")

    # 用例3: 全部健康，应无瓶颈
    r3 = diagnose(impression=100000, click=3500, order=200, paid=160)
    if r3["瓶颈环节"] is not None:
        print(f"  [FAIL] 用例3 应无瓶颈 实际{r3['瓶颈环节']}"); ok = False
    else:
        print("  [PASS] 用例3 健康店铺无误报")

    # 用例4: 退款率超标应被标记
    r4 = diagnose(impression=100000, click=3500, order=200, paid=160, refund=60)
    if r4["各环节指标"]["refund_rate"]["状态"] != "偏高":
        print("  [FAIL] 用例4 退款率超标未标记"); ok = False
    else:
        print("  [PASS] 用例4 退款率超标识别")

    # 用例5: 客单价计算
    r5 = diagnose(impression=100000, click=3500, order=200, paid=160, gmv=16000)
    if abs(r5["客单价"] - 100.0) > 0.01:
        print(f"  [FAIL] 用例5 客单价应为100 实际{r5['客单价']}"); ok = False
    else:
        print("  [PASS] 用例5 客单价计算")

    # 用例6: 数据矛盾应报错
    try:
        diagnose(impression=100, click=200, order=10, paid=5)
        print("  [FAIL] 用例6 点击>曝光未报错"); ok = False
    except ValueError:
        print("  [PASS] 用例6 矛盾数据拦截")

    print("自检结果:", "全部通过" if ok else "存在失败")
    return 0 if ok else 1


def main() -> int:
    p = argparse.ArgumentParser(description="店铺转化链路诊断器")
    p.add_argument("--impression", type=float, help="曝光量")
    p.add_argument("--click", type=float, help="点击数/访客数")
    p.add_argument("--cart", type=float, default=None, help="加购数（可选）")
    p.add_argument("--order", type=float, help="下单数")
    p.add_argument("--paid", type=float, help="支付数")
    p.add_argument("--refund", type=float, default=None, help="退款数（可选）")
    p.add_argument("--gmv", type=float, default=None, help="支付金额（可选）")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.add_argument("--self-test", action="store_true", help="运行内置自检")
    a = p.parse_args()

    if a.self_test:
        return _self_test()
    if None in (a.impression, a.click, a.order, a.paid):
        p.print_help()
        print("\n[错误] 必须提供 --impression --click --order --paid")
        return 2

    try:
        res = diagnose(a.impression, a.click, a.order, a.paid,
                       a.cart, a.refund, a.gmv)
    except ValueError as e:
        print(f"[错误] {e}")
        return 2

    print(json.dumps(res, ensure_ascii=False, indent=2) if a.json else render(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
