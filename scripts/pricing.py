#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
电商定价与利润测算器 —— 计算真实到手利润、保本售价、保本 ROI。

与"售价 - 成本 = 利润"的粗算不同，本脚本采用【100 单基准法】：
模拟发出 100 单，其中 r% 退货，分别核算收入侧与成本侧，
再折算回单均利润。退货产生的去程运费、包材、损耗均不可回收，
这是多数商家算漏利润的主因。

用法:
  python pricing.py --cost 30 --price 99 --platform tmall
  python pricing.py --cost 30 --price 99 --platform douyin --return-rate 25 --ad-ratio 15
  python pricing.py --cost 30 --price 99 --platform tmall --json
  python pricing.py --self-test
"""

from __future__ import annotations

import argparse
import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

try:
    from platform_fees import get_platform, list_platforms, pad
except ImportError:  # 允许从其他目录调用
    import os

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from platform_fees import get_platform, list_platforms, pad


def calc_profit(
    cost: float,
    price: float,
    commission: float,
    payment_fee: float = 0.0,
    shipping: float = 0.0,
    return_shipping: float | None = None,
    packaging: float = 0.0,
    return_rate: float = 0.0,
    damage_rate: float = 0.0,
    ad_ratio: float = 0.0,
    other: float = 0.0,
    batch: int = 100,
) -> dict:
    """
    以 batch 单为基准核算利润。

    参数均为「元」或「百分比」。返回 dict，含单均净利、净利率、
    保本售价、保本 ROI 及成本结构明细。

    退货口径:
      - 退货订单不产生销售收入，平台佣金随之退回
      - 去程运费、包材不可回收（已发出）
      - 退货运费按 return_shipping 计（商家承担部分）
      - damage_rate 为退回商品中无法二次销售的比例
    """
    if price <= 0:
        raise ValueError("售价必须大于 0")
    if cost < 0:
        raise ValueError("成本不能为负")
    if not 0 <= return_rate < 100:
        raise ValueError("退货率需在 [0, 100) 区间")

    if return_shipping is None:
        return_shipping = shipping

    r = return_rate / 100.0
    d = damage_rate / 100.0

    paid_orders = batch * (1 - r)      # 有效成交单数
    returned = batch * r               # 退货单数

    # ---------- 收入侧 ----------
    gmv = batch * price                # 含退款的成交额（推广费基数）
    revenue = paid_orders * price      # 实际到手销售额

    # ---------- 成本侧 ----------
    # 商品成本：有效订单全额消耗 + 退货中损坏部分
    goods_cost = paid_orders * cost + returned * cost * d
    # 运费：全部订单去程 + 退货回程
    ship_cost = batch * shipping + returned * return_shipping
    # 包材：发出即消耗
    pack_cost = batch * packaging
    # 平台佣金 + 支付手续费：仅按有效成交额计（退款一般原路退回佣金）
    commission_cost = revenue * commission / 100.0
    payment_cost = revenue * payment_fee / 100.0
    # 推广费：按含退款的成交额计（广告花费不因退货返还）
    ad_cost = gmv * ad_ratio / 100.0
    other_cost = batch * other

    total_cost = (
        goods_cost + ship_cost + pack_cost
        + commission_cost + payment_cost + ad_cost + other_cost
    )
    net_profit = revenue - total_cost

    per_order_profit = net_profit / paid_orders if paid_orders else 0.0
    net_margin = net_profit / revenue * 100 if revenue else 0.0

    # ---------- 保本售价 ----------
    # 令净利=0 反解 price。收入与部分成本均与 price 线性相关：
    # revenue*(1 - comm% - pay%) - gmv*ad% = 固定成本
    # => price * [ paid*(1-c-p) - batch*ad ] = 固定成本
    fixed = goods_cost + ship_cost + pack_cost + other_cost
    coef = (
        paid_orders * (1 - commission / 100.0 - payment_fee / 100.0)
        - batch * ad_ratio / 100.0
    )
    breakeven_price = fixed / coef if coef > 0 else float("inf")

    # ---------- 毛利率与保本 ROI ----------
    # 毛利率 = (售价 - 除推广外的全部变动成本) / 售价
    cost_ex_ad = total_cost - ad_cost
    gross_per_order = (revenue - cost_ex_ad) / paid_orders if paid_orders else 0.0
    gross_margin = gross_per_order / price * 100 if price else 0.0
    breakeven_roi = 100.0 / gross_margin if gross_margin > 0 else float("inf")

    def pct(x: float) -> float:
        return round(x / revenue * 100, 2) if revenue else 0.0

    return {
        "输入": {
            "售价": price, "商品成本": cost, "佣金率%": commission,
            "支付费率%": payment_fee, "快递费": shipping,
            "退货运费": return_shipping, "包材": packaging,
            "退货率%": return_rate, "损坏率%": damage_rate,
            "推广费占比%": ad_ratio, "其他成本": other,
        },
        "单均净利": round(per_order_profit, 2),
        "净利率%": round(net_margin, 2),
        "毛利率%": round(gross_margin, 2),
        "保本售价": round(breakeven_price, 2),
        "保本ROI": round(breakeven_roi, 2),
        "成本结构": {
            "商品成本": {"金额": round(goods_cost, 2), "占销售额%": pct(goods_cost)},
            "物流费": {"金额": round(ship_cost, 2), "占销售额%": pct(ship_cost)},
            "包材费": {"金额": round(pack_cost, 2), "占销售额%": pct(pack_cost)},
            "平台佣金": {"金额": round(commission_cost, 2), "占销售额%": pct(commission_cost)},
            "支付手续费": {"金额": round(payment_cost, 2), "占销售额%": pct(payment_cost)},
            "推广费": {"金额": round(ad_cost, 2), "占销售额%": pct(ad_cost)},
            "其他": {"金额": round(other_cost, 2), "占销售额%": pct(other_cost)},
        },
        "批次汇总": {
            "基准单数": batch,
            "有效成交单": round(paid_orders, 1),
            "退货单": round(returned, 1),
            "销售额": round(revenue, 2),
            "总成本": round(total_cost, 2),
            "净利润": round(net_profit, 2),
        },
    }


def render(res: dict) -> str:
    """把结果渲染成可读报告。"""
    L = []
    L.append("=" * 60)
    L.append("           电商定价与利润测算报告")
    L.append("=" * 60)
    b = res["批次汇总"]
    L.append(f"[基准] 每 {b['基准单数']} 单发货，有效成交 {b['有效成交单']} 单，"
             f"退货 {b['退货单']} 单")
    L.append("")
    L.append("--- 核心结论 ---")
    L.append(f"  单均净利      : {res['单均净利']:>10.2f} 元")
    L.append(f"  净利率        : {res['净利率%']:>10.2f} %")
    L.append(f"  毛利率        : {res['毛利率%']:>10.2f} %")
    L.append(f"  保本售价      : {res['保本售价']:>10.2f} 元  (低于此价必亏)")
    roi = res["保本ROI"]
    roi_s = "无法保本" if roi == float("inf") else f"{roi:.2f}"
    L.append(f"  保本 ROI      : {roi_s:>10}     (投产比低于此值即亏损)")
    L.append("")
    L.append("--- 成本结构（占销售额比重）---")
    for k, v in res["成本结构"].items():
        if v["金额"] > 0:
            bar = "#" * max(1, int(v["占销售额%"] / 2))
            L.append(f"  {pad(k, 12)}{v['金额']:>9.2f} 元  "
                     f"{v['占销售额%']:>6.2f}%  {bar}")
    L.append("")
    L.append("--- 批次汇总 ---")
    L.append(f"  销售额 {b['销售额']:.2f} - 总成本 {b['总成本']:.2f} "
             f"= 净利润 {b['净利润']:.2f} 元")
    L.append("")
    if res["净利率%"] < 0:
        L.append("[风险] 当前为亏损结构，需提价 / 压成本 / 降退货率 / 减推广。")
    elif res["净利率%"] < 5:
        L.append("[提示] 净利率低于5%，抗风险能力弱，退货或价格战会直接击穿。")
    elif res["净利率%"] > 30:
        L.append("[提示] 净利率较高，可考虑加大推广抢占份额。")
    L.append("=" * 60)
    L.append("注：费率为参考值，请以平台后台最新计费规则为准。")
    return "\n".join(L)


def _self_test() -> int:
    """内置自检，验证计算逻辑正确性。"""
    print("运行 pricing.py 自检...")
    ok = True

    # 用例1：零退货、零推广，净利应等于简单算式
    r1 = calc_profit(cost=30, price=100, commission=0, shipping=0, packaging=0)
    if abs(r1["单均净利"] - 70.0) > 0.01:
        print(f"  [FAIL] 用例1 期望 70.0, 实际 {r1['单均净利']}")
        ok = False
    else:
        print("  [PASS] 用例1 无退货无费用场景")

    # 用例2：10%佣金，单均净利 = 100 - 30 - 10 = 60
    r2 = calc_profit(cost=30, price=100, commission=10)
    if abs(r2["单均净利"] - 60.0) > 0.01:
        print(f"  [FAIL] 用例2 期望 60.0, 实际 {r2['单均净利']}")
        ok = False
    else:
        print("  [PASS] 用例2 佣金扣减")

    # 用例3：保本售价代入后净利应≈0
    r3 = calc_profit(cost=30, price=100, commission=5, shipping=4,
                     packaging=1, return_rate=20, ad_ratio=10)
    be = r3["保本售价"]
    r3b = calc_profit(cost=30, price=be, commission=5, shipping=4,
                      packaging=1, return_rate=20, ad_ratio=10)
    if abs(r3b["单均净利"]) > 0.05:
        print(f"  [FAIL] 用例3 保本价代入净利应为0, 实际 {r3b['单均净利']}")
        ok = False
    else:
        print("  [PASS] 用例3 保本售价反解自洽")

    # 用例4：保本ROI × 毛利率 应 ≈ 100
    gm = r3["毛利率%"]
    br = r3["保本ROI"]
    if gm > 0 and abs(gm * br - 100) > 0.5:
        print(f"  [FAIL] 用例4 毛利率×保本ROI 应≈100, 实际 {gm * br:.2f}")
        ok = False
    else:
        print("  [PASS] 用例4 保本ROI 与毛利率互洽")

    # 用例5：退货率上升，利润必须下降
    a = calc_profit(cost=30, price=100, commission=5, shipping=4, return_rate=0)
    b = calc_profit(cost=30, price=100, commission=5, shipping=4, return_rate=30)
    if not b["单均净利"] < a["单均净利"]:
        print("  [FAIL] 用例5 退货率上升利润未下降")
        ok = False
    else:
        print("  [PASS] 用例5 退货率敏感性")

    # 用例6：异常输入应抛错
    try:
        calc_profit(cost=10, price=0, commission=5)
        print("  [FAIL] 用例6 售价为0未报错")
        ok = False
    except ValueError:
        print("  [PASS] 用例6 非法输入拦截")

    print("自检结果:", "全部通过" if ok else "存在失败")
    return 0 if ok else 1


def main() -> int:
    p = argparse.ArgumentParser(
        description="电商定价与利润测算器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例: python pricing.py --cost 30 --price 99 --platform tmall",
    )
    p.add_argument("--cost", type=float, help="单件商品成本（含税进货价）")
    p.add_argument("--price", type=float, help="对客售价（实付价，扣掉优惠后）")
    p.add_argument("--platform", default=None, help="平台代号，见 --list-platforms")
    p.add_argument("--commission", type=float, default=None, help="佣金率%%，覆盖平台默认")
    p.add_argument("--payment-fee", type=float, default=None, help="支付费率%%")
    p.add_argument("--shipping", type=float, default=0.0, help="单件快递成本")
    p.add_argument("--return-shipping", type=float, default=None, help="退货回程运费，默认同快递费")
    p.add_argument("--packaging", type=float, default=0.0, help="包材成本")
    p.add_argument("--return-rate", type=float, default=0.0, help="退货率%%")
    p.add_argument("--damage-rate", type=float, default=0.0, help="退回件不可二次销售比例%%")
    p.add_argument("--ad-ratio", type=float, default=0.0, help="推广费占成交额%%")
    p.add_argument("--other", type=float, default=0.0, help="其他单均成本（客服/仓储分摊）")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.add_argument("--list-platforms", action="store_true", help="列出平台费率表")
    p.add_argument("--self-test", action="store_true", help="运行内置自检")
    a = p.parse_args()

    if a.self_test:
        return _self_test()
    if a.list_platforms:
        print(list_platforms())
        return 0
    if a.cost is None or a.price is None:
        p.print_help()
        print("\n[错误] 必须提供 --cost 与 --price")
        return 2

    commission = a.commission
    payment_fee = a.payment_fee
    if a.platform:
        try:
            info = get_platform(a.platform)
        except KeyError as e:
            print(f"[错误] {e}")
            return 2
        if commission is None:
            commission = info["commission"]
        if payment_fee is None:
            payment_fee = info["payment_fee"]
    commission = commission or 0.0
    payment_fee = payment_fee or 0.0

    try:
        res = calc_profit(
            cost=a.cost, price=a.price, commission=commission,
            payment_fee=payment_fee, shipping=a.shipping,
            return_shipping=a.return_shipping, packaging=a.packaging,
            return_rate=a.return_rate, damage_rate=a.damage_rate,
            ad_ratio=a.ad_ratio, other=a.other,
        )
    except ValueError as e:
        print(f"[错误] {e}")
        return 2

    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(render(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
