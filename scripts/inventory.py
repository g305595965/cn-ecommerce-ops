#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
备货与资金占用测算器 —— 补货点、建议备货量、资金占用与断货/滞销风险。

电商库存决策的核心矛盾只有两个：备少了断货（链接权重清零、活动资源位被撤），
备多了压资金（滞销、清仓亏损）。本脚本把这两个风险量化：

  补货点 ROP = 日均销量 × (供货周期 + 安全库存天数)
  建议补货量 = ceil(max(0, ROP - 在库 - 在途) / MOQ) × MOQ
  资金占用   = 建议补货量 × 单件成本

风险分级:
  断货风险 —— 可售天数 < 供货周期: 高危（等不到补货就断货）
              可售天数 < 供货周期+安全天数: 警戒（已进入补货窗口）
              其余: 安全
  滞销风险 —— 在库可售天数 > 90 天: 提示资金沉淀与清仓预案

用法:
  python inventory.py --daily-sales 50 --lead-days 7 --stock 200 --cost 18 --moq 100
  python inventory.py --daily-sales 30 --lead-days 10 --budget 5000 --json
  python inventory.py --self-test
"""

from __future__ import annotations

import argparse
import json
import math
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SLOW_DAYS = 90  # 在库可售天数超过该值判定为滞销风险（行业常见口径）


def calc_inventory(daily_sales: float, lead_days: float,
                   safety_days: float = 7.0, stock: float = 0.0,
                   in_transit: float = 0.0, cost: float = 0.0,
                   moq: int = 1, budget: float | None = None) -> dict:
    """计算补货点、建议补货量与资金占用。单位: 件 / 天 / 元。"""
    if daily_sales <= 0:
        raise ValueError("日均销量必须大于 0")
    if lead_days < 0 or safety_days < 0:
        raise ValueError("供货周期与安全天数不能为负")
    if stock < 0 or in_transit < 0 or cost < 0:
        raise ValueError("库存/在途/成本不能为负")
    if moq < 1:
        raise ValueError("MOQ 至少为 1")

    rop = daily_sales * (lead_days + safety_days)
    available = stock + in_transit
    sellable_days = available / daily_sales

    gap = max(0.0, rop - available)
    reorder_qty = int(math.ceil(gap / moq) * moq) if gap > 0 else 0
    capital = reorder_qty * cost

    # 断货风险分级
    if sellable_days < lead_days:
        stockout_risk = "高危"
        stockout_note = "现有库存在补货到达前就会售罄，需加急补货或控量投放"
    elif sellable_days < lead_days + safety_days:
        stockout_risk = "警戒"
        stockout_note = "已进入补货窗口，应立即下单补货"
    else:
        stockout_risk = "安全"
        stockout_note = "库存覆盖补货周期与安全天数"

    # 滞销风险
    overstock = sellable_days > SLOW_DAYS
    overstock_note = (f"在库可售 {sellable_days:.0f} 天，超过 {SLOW_DAYS} 天滞销线，"
                      "建议暂停补货并评估清仓/捆绑方案") if overstock else ""

    # 预算约束
    budget_note = ""
    affordable = None
    if budget is not None:
        if budget < 0:
            raise ValueError("预算不能为负")
        if cost > 0 and capital > budget:
            affordable = int(budget // cost // moq * moq)
            budget_note = (f"按建议量需资金 {capital:.0f} 元，超出预算 {budget:.0f} 元；"
                           f"预算内最多可备 {affordable} 件"
                           f"（覆盖约 {affordable / daily_sales:.0f} 天销量）")

    return {
        "输入": {
            "日均销量": daily_sales, "供货周期天": lead_days,
            "安全库存天": safety_days, "在库": stock, "在途": in_transit,
            "单件成本": cost, "MOQ": moq,
            "预算": budget if budget is not None else "未设",
        },
        "补货点ROP": round(rop, 1),
        "可用库存": available,
        "可售天数": round(sellable_days, 1),
        "建议补货量": reorder_qty,
        "资金占用": round(capital, 2),
        "断货风险": stockout_risk,
        "断货说明": stockout_note,
        "滞销风险": overstock,
        "滞销说明": overstock_note,
        "预算说明": budget_note,
        "预算内可备量": affordable,
    }


def render(r: dict) -> str:
    L = ["=" * 60, "             备货与资金占用测算报告", "=" * 60]
    i = r["输入"]
    L.append(f"[输入] 日销 {i['日均销量']} 件 | 供货周期 {i['供货周期天']} 天 "
             f"+ 安全 {i['安全库存天']} 天 | 在库 {i['在库']} + 在途 {i['在途']}")
    L.append("")
    L.append("--- 核心结论 ---")
    L.append(f"  补货点 ROP   : {r['补货点ROP']:>10.1f} 件 (库存低于此值即应下单)")
    L.append(f"  可售天数     : {r['可售天数']:>10.1f} 天")
    L.append(f"  建议补货量   : {r['建议补货量']:>10} 件")
    L.append(f"  资金占用     : {r['资金占用']:>10.2f} 元")
    L.append("")
    mark = {"高危": "[!]", "警戒": "[!]", "安全": "[OK]"}[r["断货风险"]]
    L.append(f"{mark} 断货风险: {r['断货风险']} —— {r['断货说明']}")
    if r["滞销风险"]:
        L.append(f"[!] 滞销风险: {r['滞销说明']}")
    if r["预算说明"]:
        L.append(f"[!] 预算约束: {r['预算说明']}")
    L.append("")
    L.append("提示: 大促前请把『日均销量』替换为大促预估日销重新测算；")
    L.append("      一件代发模式无备货需求，本工具适用于自采囤货/半托管海外仓场景。")
    L.append("=" * 60)
    return "\n".join(L)


def _self_test() -> int:
    print("运行 inventory.py 自检...")
    ok = True

    # 用例1: ROP 公式正确 (50 × (7+7) = 700)
    r1 = calc_inventory(daily_sales=50, lead_days=7, safety_days=7,
                        stock=200, cost=18, moq=100)
    if abs(r1["补货点ROP"] - 700) < 0.01:
        print("  [PASS] 用例1 ROP 公式正确")
    else:
        print(f"  [FAIL] 用例1 ROP 期望700 实际{r1['补货点ROP']}")
        ok = False

    # 用例2: MOQ 向上取整 (gap=500 → 500; gap=501 → 600)
    r2 = calc_inventory(daily_sales=50, lead_days=7, safety_days=7,
                        stock=200, moq=100)
    r2b = calc_inventory(daily_sales=50.1, lead_days=7, safety_days=7,
                         stock=200, moq=100)
    if r2["建议补货量"] == 500 and r2b["建议补货量"] == 600:
        print("  [PASS] 用例2 MOQ 向上取整正确")
    else:
        print(f"  [FAIL] 用例2 补货量 {r2['建议补货量']}/{r2b['建议补货量']}")
        ok = False

    # 用例3: 库存充足时补货量为 0 且风险安全
    r3 = calc_inventory(daily_sales=10, lead_days=5, safety_days=5,
                        stock=500)
    if r3["建议补货量"] == 0 and r3["断货风险"] == "安全":
        print("  [PASS] 用例3 库存充足不补货")
    else:
        print(f"  [FAIL] 用例3 补货量{r3['建议补货量']} 风险{r3['断货风险']}")
        ok = False

    # 用例4: 零库存零在途必为高危
    r4 = calc_inventory(daily_sales=30, lead_days=10, stock=0)
    if r4["断货风险"] == "高危" and r4["可售天数"] == 0:
        print("  [PASS] 用例4 零库存判高危")
    else:
        print(f"  [FAIL] 用例4 风险{r4['断货风险']} 天数{r4['可售天数']}")
        ok = False

    # 用例5: 在途计入可用库存
    r5 = calc_inventory(daily_sales=10, lead_days=5, safety_days=5,
                        stock=50, in_transit=50)
    if r5["可用库存"] == 100 and abs(r5["可售天数"] - 10) < 0.01:
        print("  [PASS] 用例5 在途计入可用库存")
    else:
        print(f"  [FAIL] 用例5 可用{r5['可用库存']} 天数{r5['可售天数']}")
        ok = False

    # 用例6: 预算不足时给出预算内可备量
    r6 = calc_inventory(daily_sales=50, lead_days=7, safety_days=7,
                        stock=0, cost=18, moq=100, budget=5000)
    if (r6["预算内可备量"] is not None
            and r6["预算内可备量"] * 18 <= 5000
            and (r6["预算内可备量"] + 100) * 18 > 5000):
        print("  [PASS] 用例6 预算约束计算正确")
    else:
        print(f"  [FAIL] 用例6 预算内可备量 {r6['预算内可备量']}")
        ok = False

    # 用例7: 滞销判定 (可售 100 天 > 90 天)
    r7 = calc_inventory(daily_sales=10, lead_days=5, stock=1000)
    if r7["滞销风险"]:
        print("  [PASS] 用例7 滞销风险判定")
    else:
        print("  [FAIL] 用例7 未识别滞销")
        ok = False

    # 用例8: 非法输入拦截
    for kw in ({"daily_sales": 0, "lead_days": 5},
               {"daily_sales": 10, "lead_days": 5, "moq": 0}):
        try:
            calc_inventory(**kw)
            print(f"  [FAIL] 用例8 非法输入未拦截: {kw}")
            ok = False
        except ValueError:
            pass
    else:
        print("  [PASS] 用例8 非法输入拦截")

    print("自检结果:", "全部通过" if ok else "存在失败")
    return 0 if ok else 1


def main() -> int:
    p = argparse.ArgumentParser(
        description="备货与资金占用测算器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例: python inventory.py --daily-sales 50 --lead-days 7 "
               "--stock 200 --cost 18 --moq 100",
    )
    p.add_argument("--daily-sales", type=float, help="日均销量（件/天，必填）")
    p.add_argument("--lead-days", type=float, help="供货周期：下单到可售天数（必填）")
    p.add_argument("--safety-days", type=float, default=7.0,
                   help="安全库存天数，默认 7")
    p.add_argument("--stock", type=float, default=0.0, help="当前在库（件）")
    p.add_argument("--in-transit", type=float, default=0.0, help="在途未到货（件）")
    p.add_argument("--cost", type=float, default=0.0, help="单件成本（元）")
    p.add_argument("--moq", type=int, default=1, help="供应商起订量/补货最小批量")
    p.add_argument("--budget", type=float, default=None, help="备货资金上限（元，可选）")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.add_argument("--self-test", action="store_true", help="运行内置自检")
    a = p.parse_args()

    if a.self_test:
        return _self_test()
    if a.daily_sales is None or a.lead_days is None:
        p.print_help()
        print("\n[错误] 必须提供 --daily-sales 与 --lead-days")
        return 2

    try:
        res = calc_inventory(a.daily_sales, a.lead_days, a.safety_days,
                             a.stock, a.in_transit, a.cost, a.moq, a.budget)
    except ValueError as e:
        print(f"[错误] {e}")
        return 2

    print(json.dumps(res, ensure_ascii=False, indent=2) if a.json else render(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
