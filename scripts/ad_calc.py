#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
付费流量投放测算器 —— UV 价值、保本 ROI、可承受最高出价、目标反推。

适用于直通车 / 万相台 / 巨量千川 / 京准通 / 多多搜索等所有 CPC 竞价场景。

核心恒等式:
  UV 价值      = 客单价 × 转化率
  ROI          = UV 价值 ÷ CPC
  保本 ROI     = 1 ÷ 毛利率
  保本 CPC     = UV 价值 × 毛利率
  广告后利润   = GMV × 毛利率 - 广告花费

只要 CPC 低于保本 CPC，投放即为正向；高于则每一次点击都在亏钱。

用法:
  python ad_calc.py --price 129 --gross-margin 60 --cvr 2.5 --cpc 1.2
  python ad_calc.py --price 129 --gross-margin 60 --cvr 2.5 --cpc 1.2 --budget 2000
  python ad_calc.py --price 129 --gross-margin 60 --cvr 2.5 --cpc 1.2 --target-roi 3
  python ad_calc.py --self-test
"""

from __future__ import annotations

import argparse
import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def calc_ad(
    price: float,
    gross_margin: float,
    cvr: float,
    cpc: float,
    ctr: float | None = None,
    budget: float | None = None,
    target_roi: float | None = None,
) -> dict:
    """
    计算投放核心指标。

    price        客单价（元）
    gross_margin 毛利率（%），须为扣除商品/物流/佣金后、未扣广告的口径
    cvr          点击->支付转化率（%）
    cpc          实际平均点击花费（元）
    ctr          点击率（%），提供后可推算 CPM 与所需曝光
    budget       日预算（元），提供后测算日投放结果
    target_roi   目标 ROI，提供后反推所需 CPC 与 CVR
    """
    if price <= 0:
        raise ValueError("客单价必须大于 0")
    if not 0 < gross_margin <= 100:
        raise ValueError("毛利率需在 (0, 100] 区间")
    if not 0 < cvr <= 100:
        raise ValueError("转化率需在 (0, 100] 区间")
    if cpc <= 0:
        raise ValueError("CPC 必须大于 0")

    gm = gross_margin / 100.0
    cvr_d = cvr / 100.0

    uv_value = price * cvr_d              # 每个访客能带来多少成交额
    roi = uv_value / cpc                  # 投产比
    breakeven_roi = 1.0 / gm              # 保本投产比
    breakeven_cpc = uv_value * gm         # 可承受最高点击单价
    cpa = cpc / cvr_d                     # 单笔成交获客成本
    breakeven_cpa = price * gm            # 可承受最高获客成本

    profit_per_click = uv_value * gm - cpc          # 每次点击的净贡献
    profit_per_order = price * gm - cpa             # 每单广告后利润
    margin_after_ad = (profit_per_order / price * 100) if price else 0.0

    res = {
        "输入": {
            "客单价": price, "毛利率%": gross_margin,
            "转化率%": cvr, "CPC": cpc,
        },
        "UV价值": round(uv_value, 3),
        "当前ROI": round(roi, 2),
        "保本ROI": round(breakeven_roi, 2),
        "保本CPC": round(breakeven_cpc, 2),
        "CPC安全边际%": round((breakeven_cpc - cpc) / breakeven_cpc * 100, 2)
        if breakeven_cpc else 0.0,
        "单单获客成本CPA": round(cpa, 2),
        "保本CPA": round(breakeven_cpa, 2),
        "每点击净利": round(profit_per_click, 3),
        "每单广告后利润": round(profit_per_order, 2),
        "广告后净利率%": round(margin_after_ad, 2),
        "结论": "正向可放量" if roi > breakeven_roi else "亏损需优化",
    }

    if ctr is not None:
        if not 0 < ctr <= 100:
            raise ValueError("点击率需在 (0, 100] 区间")
        cpm = cpc * (ctr / 100.0) * 1000
        res["曝光指标"] = {
            "点击率%": ctr,
            "千次曝光成本CPM": round(cpm, 2),
            "每单所需曝光": round(1 / (ctr / 100.0 * cvr_d)),
        }

    if budget is not None:
        if budget <= 0:
            raise ValueError("预算必须大于 0")
        clicks = budget / cpc
        orders = clicks * cvr_d
        gmv = orders * price
        profit = gmv * gm - budget
        res["预算测算"] = {
            "日预算": budget,
            "预估点击": round(clicks),
            "预估订单": round(orders, 1),
            "预估GMV": round(gmv, 2),
            "广告后利润": round(profit, 2),
            "实际ROI": round(gmv / budget, 2),
        }

    if target_roi is not None:
        if target_roi <= 0:
            raise ValueError("目标ROI必须大于 0")
        need_cpc = uv_value / target_roi
        need_cvr = target_roi * cpc / price * 100
        res["目标反推"] = {
            "目标ROI": target_roi,
            "所需CPC": round(need_cpc, 2),
            "CPC需下降%": round((cpc - need_cpc) / cpc * 100, 2) if cpc else 0.0,
            "或所需转化率%": round(need_cvr, 2),
            "转化率需提升%": round((need_cvr - cvr) / cvr * 100, 2) if cvr else 0.0,
            "达标": target_roi <= roi,
        }

    return res


def render(r: dict) -> str:
    L = ["=" * 60, "           付费流量投放测算报告", "=" * 60]
    i = r["输入"]
    L.append(f"客单价 {i['客单价']} 元 | 毛利率 {i['毛利率%']}% | "
             f"转化率 {i['转化率%']}% | CPC {i['CPC']} 元")
    L.append("")
    L.append("--- 核心指标 ---")
    L.append(f"  UV 价值（每访客产值）: {r['UV价值']:>8.3f} 元")
    L.append(f"  当前 ROI            : {r['当前ROI']:>8.2f}")
    L.append(f"  保本 ROI            : {r['保本ROI']:>8.2f}")
    L.append(f"  保本 CPC（最高出价）: {r['保本CPC']:>8.2f} 元")
    L.append(f"  CPC 安全边际        : {r['CPC安全边际%']:>8.2f} %")
    L.append(f"  实际 CPA（获客成本）: {r['单单获客成本CPA']:>8.2f} 元")
    L.append(f"  保本 CPA            : {r['保本CPA']:>8.2f} 元")
    L.append(f"  每单广告后利润      : {r['每单广告后利润']:>8.2f} 元")
    L.append(f"  广告后净利率        : {r['广告后净利率%']:>8.2f} %")
    L.append("")

    if "曝光指标" in r:
        e = r["曝光指标"]
        L.append("--- 曝光侧 ---")
        L.append(f"  CPM {e['千次曝光成本CPM']:.2f} 元 | "
                 f"成交一单约需 {e['每单所需曝光']} 次曝光")
        L.append("")

    if "预算测算" in r:
        b = r["预算测算"]
        L.append("--- 日预算测算 ---")
        L.append(f"  预算 {b['日预算']:.0f} 元 -> 点击 {b['预估点击']} 次 "
                 f"-> 订单 {b['预估订单']} 单")
        L.append(f"  GMV {b['预估GMV']:.2f} 元 | ROI {b['实际ROI']:.2f} | "
                 f"广告后利润 {b['广告后利润']:.2f} 元")
        L.append("")

    if "目标反推" in r:
        t = r["目标反推"]
        L.append("--- 目标反推 ---")
        L.append(f"  要达到 ROI {t['目标ROI']}，二选一：")
        L.append(f"    A. CPC 降到 {t['所需CPC']:.2f} 元"
                 f"（需下降 {t['CPC需下降%']:.1f}%）")
        L.append(f"    B. 转化率提到 {t['或所需转化率%']:.2f}%"
                 f"（需提升 {t['转化率需提升%']:.1f}%）")
        L.append(f"  当前状态: {'已达标' if t['达标'] else '未达标'}")
        L.append("")

    L.append("--- 结论 ---")
    if r["结论"] == "正向可放量":
        L.append(f"  [正向] ROI {r['当前ROI']} > 保本 {r['保本ROI']}，"
                 f"每点击净赚 {r['每点击净利']:.3f} 元，可加预算测试放量。")
    else:
        L.append(f"  [亏损] ROI {r['当前ROI']} < 保本 {r['保本ROI']}，"
                 f"每点击净亏 {abs(r['每点击净利']):.3f} 元。")
        L.append("  优先级: 1)提转化率(主图/详情/评价/价格) "
                 "2)降CPC(优化质量分/精准词) 3)提客单价(搭配套餐)")
    L.append("=" * 60)
    return "\n".join(L)


def _self_test() -> int:
    print("运行 ad_calc.py 自检...")
    ok = True

    # 用例1: UV价值 = 100 × 2% = 2.0
    r1 = calc_ad(price=100, gross_margin=50, cvr=2, cpc=1)
    if abs(r1["UV价值"] - 2.0) > 1e-6:
        print(f"  [FAIL] 用例1 UV价值 期望2.0 实际{r1['UV价值']}"); ok = False
    else:
        print("  [PASS] 用例1 UV价值公式")

    # 用例2: 保本ROI = 1/0.5 = 2.0
    if abs(r1["保本ROI"] - 2.0) > 1e-6:
        print(f"  [FAIL] 用例2 保本ROI 期望2.0 实际{r1['保本ROI']}"); ok = False
    else:
        print("  [PASS] 用例2 保本ROI公式")

    # 用例3: 保本CPC 代入后 ROI 必须等于保本ROI
    be_cpc = r1["保本CPC"]
    r3 = calc_ad(price=100, gross_margin=50, cvr=2, cpc=be_cpc)
    if abs(r3["当前ROI"] - r3["保本ROI"]) > 0.01:
        print(f"  [FAIL] 用例3 保本CPC下ROI应等于保本ROI: "
              f"{r3['当前ROI']} vs {r3['保本ROI']}"); ok = False
    else:
        print("  [PASS] 用例3 保本CPC自洽")

    # 用例4: 保本CPC 下每单利润应为 0
    if abs(r3["每单广告后利润"]) > 0.01:
        print(f"  [FAIL] 用例4 保本点每单利润应为0 实际{r3['每单广告后利润']}")
        ok = False
    else:
        print("  [PASS] 用例4 保本点利润归零")

    # 用例5: 目标反推自洽——用反推出的CPC重算，ROI应等于目标
    r5 = calc_ad(price=129, gross_margin=60, cvr=2.5, cpc=1.2, target_roi=3)
    nc = r5["目标反推"]["所需CPC"]
    r5b = calc_ad(price=129, gross_margin=60, cvr=2.5, cpc=nc)
    if abs(r5b["当前ROI"] - 3) > 0.02:
        print(f"  [FAIL] 用例5 反推CPC重算ROI应=3 实际{r5b['当前ROI']}"); ok = False
    else:
        print("  [PASS] 用例5 目标ROI反推自洽")

    # 用例6: 预算测算 GMV/预算 应等于 ROI
    r6 = calc_ad(price=100, gross_margin=50, cvr=2, cpc=1, budget=1000)
    b = r6["预算测算"]
    if abs(b["实际ROI"] - r6["当前ROI"]) > 0.02:
        print(f"  [FAIL] 用例6 预算ROI不一致"); ok = False
    else:
        print("  [PASS] 用例6 预算测算一致性")

    # 用例7: 非法输入
    try:
        calc_ad(price=100, gross_margin=0, cvr=2, cpc=1)
        print("  [FAIL] 用例7 毛利率0未报错"); ok = False
    except ValueError:
        print("  [PASS] 用例7 非法输入拦截")

    print("自检结果:", "全部通过" if ok else "存在失败")
    return 0 if ok else 1


def main() -> int:
    p = argparse.ArgumentParser(description="付费流量投放测算器")
    p.add_argument("--price", type=float, help="客单价")
    p.add_argument("--gross-margin", type=float, help="毛利率%%（未扣广告）")
    p.add_argument("--cvr", type=float, help="点击->支付转化率%%")
    p.add_argument("--cpc", type=float, help="平均点击花费")
    p.add_argument("--ctr", type=float, default=None, help="点击率%%（可选）")
    p.add_argument("--budget", type=float, default=None, help="日预算（可选）")
    p.add_argument("--target-roi", type=float, default=None, help="目标ROI（可选）")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.add_argument("--self-test", action="store_true", help="运行内置自检")
    a = p.parse_args()

    if a.self_test:
        return _self_test()
    if None in (a.price, a.gross_margin, a.cvr, a.cpc):
        p.print_help()
        print("\n[错误] 必须提供 --price --gross-margin --cvr --cpc")
        return 2

    try:
        res = calc_ad(a.price, a.gross_margin, a.cvr, a.cpc,
                      a.ctr, a.budget, a.target_roi)
    except ValueError as e:
        print(f"[错误] {e}")
        return 2

    print(json.dumps(res, ensure_ascii=False, indent=2) if a.json else render(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
