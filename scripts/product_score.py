#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
选品六维评分模型 —— 把"我觉得这个能卖"变成可量化的决策。

六个维度按权重加总为 100 分：
  利润空间 25% | 市场需求 20% | 竞争强度 20%
  退货风险 15% | 物流成本 10% | 供应链 10%

输入的是原始业务数据（毛利率、搜索量、供需比等），
脚本内部通过分段插值换算为 0~100 分，避免人工主观打分。

决策阈值:
  >= 75  优质款，可重点投入
  60~74  可做款，小批量测试
  <  60  放弃，机会成本过高

用法:
  python product_score.py --gross-margin 62 --search-index 8000 --trend up \\
      --supply-ratio 3.2 --return-rate 18 --weight 0.4 --moq 100 --restock-days 10
  python product_score.py ... --json
  python product_score.py --self-test
"""

from __future__ import annotations

import argparse
import json
import math
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

try:
    from platform_fees import pad
except ImportError:
    import os

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from platform_fees import pad

WEIGHTS = {
    "利润空间": 0.25,
    "市场需求": 0.20,
    "竞争强度": 0.20,
    "退货风险": 0.15,
    "物流成本": 0.10,
    "供应链": 0.10,
}

TREND_ADJUST = {"up": 15.0, "flat": 0.0, "down": -20.0}


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _piecewise(x: float, points: list[tuple[float, float]]) -> float:
    """
    分段线性插值。points 为 [(输入值, 对应分数), ...]，按输入值升序。
    超出范围时取端点值。
    """
    if x <= points[0][0]:
        return points[0][1]
    if x >= points[-1][0]:
        return points[-1][1]
    for i in range(len(points) - 1):
        x0, y0 = points[i]
        x1, y1 = points[i + 1]
        if x0 <= x <= x1:
            ratio = (x - x0) / (x1 - x0) if x1 != x0 else 0
            return y0 + (y1 - y0) * ratio
    return points[-1][1]


def score_profit(gross_margin: float) -> float:
    """毛利率 -> 利润空间得分。40% 以下难以支撑付费投放。"""
    return _clamp(_piecewise(gross_margin, [
        (0, 0), (20, 20), (30, 35), (40, 50),
        (50, 65), (60, 78), (70, 88), (80, 95), (100, 100),
    ]))


def score_demand(search_index: float, trend: str = "flat") -> float:
    """搜索量/热度指数 + 趋势 -> 市场需求得分（对数尺度）。"""
    if search_index <= 0:
        base = 0.0
    else:
        # 100 -> 20 分, 1000 -> 47 分, 10000 -> 73 分, 100000 -> 100 分
        base = _clamp((math.log10(search_index) - 2) / 3 * 80 + 20)
    return _clamp(base + TREND_ADJUST.get(trend, 0.0))


def score_competition(supply_ratio: float) -> float:
    """供需比（搜索人气/在售商品数）-> 竞争强度得分。越高越蓝海。"""
    return _clamp(_piecewise(supply_ratio, [
        (0, 5), (0.5, 20), (1, 38), (2, 55),
        (3, 65), (5, 80), (8, 90), (15, 100),
    ]))


def score_return(return_rate: float) -> float:
    """预估退货率 -> 退货风险得分。退货率越低得分越高。"""
    return _clamp(_piecewise(return_rate, [
        (0, 100), (5, 92), (10, 84), (20, 68),
        (30, 50), (40, 32), (50, 18), (70, 0),
    ]))


def score_logistics(weight_kg: float, fragile: bool = False) -> float:
    """单件重量（kg）-> 物流成本得分。易碎品额外扣分。"""
    s = _piecewise(weight_kg, [
        (0, 100), (0.2, 95), (0.5, 87), (1, 76),
        (2, 62), (3, 52), (5, 36), (10, 15), (20, 0),
    ])
    if fragile:
        s -= 15
    return _clamp(s)


def score_supply(moq: float, restock_days: float) -> float:
    """起订量与翻单速度 -> 供应链得分，两项各占一半。"""
    s_moq = _piecewise(moq, [
        (0, 100), (30, 95), (50, 90), (100, 82),
        (300, 70), (500, 62), (1000, 48), (3000, 28), (10000, 5),
    ])
    s_days = _piecewise(restock_days, [
        (0, 100), (3, 96), (7, 90), (10, 82),
        (15, 72), (21, 60), (30, 45), (45, 25), (60, 5),
    ])
    return _clamp((s_moq + s_days) / 2)


def evaluate(
    gross_margin: float,
    search_index: float,
    supply_ratio: float,
    return_rate: float,
    weight_kg: float,
    moq: float,
    restock_days: float,
    trend: str = "flat",
    fragile: bool = False,
) -> dict:
    """执行六维评分，返回总分、各维度明细与决策建议。"""
    if trend not in TREND_ADJUST:
        raise ValueError(f"trend 必须是 up/flat/down 之一，收到 {trend}")
    for name, val in (("毛利率", gross_margin), ("退货率", return_rate)):
        if not 0 <= val <= 100:
            raise ValueError(f"{name} 需在 [0, 100] 区间，收到 {val}")
    if search_index < 0 or supply_ratio < 0 or weight_kg < 0:
        raise ValueError("搜索量、供需比、重量不能为负数")
    if moq < 0 or restock_days < 0:
        raise ValueError("起订量与翻单天数不能为负数")

    dims = {
        "利润空间": score_profit(gross_margin),
        "市场需求": score_demand(search_index, trend),
        "竞争强度": score_competition(supply_ratio),
        "退货风险": score_return(return_rate),
        "物流成本": score_logistics(weight_kg, fragile),
        "供应链": score_supply(moq, restock_days),
    }
    total = sum(dims[k] * WEIGHTS[k] for k in dims)

    if total >= 75:
        verdict = "优质款"
        advice = "可重点投入资源打造，建议排入主推计划并提前锁定供应链产能。"
    elif total >= 60:
        verdict = "可做款"
        advice = "建议小批量测款，用直通车/千川小额测点击率与转化率后再决定放大。"
    else:
        verdict = "建议放弃"
        advice = "综合竞争力不足，继续投入的机会成本过高，建议寻找替代品。"

    # 短板识别：得分低于 60 的维度，按加权损失排序
    weak = sorted(
        [(k, v) for k, v in dims.items() if v < 60],
        key=lambda kv: (60 - kv[1]) * WEIGHTS[kv[0]], reverse=True,
    )
    fix_map = {
        "利润空间": "压低采购成本、提高售价或简化包装物流；毛利率低于40%难以承担付费流量",
        "市场需求": "需求体量偏小或趋势向下，考虑换更大的细分市场或等待旺季",
        "竞争强度": "红海市场，除非有供应链或内容优势，否则不建议正面进入",
        "退货风险": "补充尺码表/实拍细节以降低预期落差，并把退货成本计入定价",
        "物流成本": "优化包装体积重量，或改用产地发货/就近仓降低运费",
        "供应链": "寻找起订量更低或翻单更快的供应商，避免爆单后断货掉权重",
    }

    return {
        "总分": round(total, 1),
        "结论": verdict,
        "建议": advice,
        "各维度得分": {k: round(v, 1) for k, v in dims.items()},
        "加权贡献": {k: round(dims[k] * WEIGHTS[k], 2) for k in dims},
        "权重": WEIGHTS,
        "短板": [{"维度": k, "得分": round(v, 1), "改进方向": fix_map[k]}
                 for k, v in weak],
        "输入": {
            "毛利率%": gross_margin, "搜索热度": search_index, "趋势": trend,
            "供需比": supply_ratio, "退货率%": return_rate,
            "单件重量kg": weight_kg, "易碎": fragile,
            "起订量": moq, "翻单天数": restock_days,
        },
    }


def render(r: dict) -> str:
    L = ["=" * 62, "                选品六维评分报告", "=" * 62]
    L.append(f"  综合得分: {r['总分']} / 100      结论: {r['结论']}")
    L.append("")
    L.append("--- 维度明细 ---")
    for k, v in r["各维度得分"].items():
        w = int(r["权重"][k] * 100)
        bar = "#" * int(v / 5)
        flag = "  " if v >= 60 else "!!"
        L.append(f"  {flag} {pad(k, 10)}{v:>5.1f}分  (权重{w:>2}%)  {bar}")
    L.append("")
    if r["短板"]:
        L.append("--- 短板与改进方向（按影响排序）---")
        for i, s in enumerate(r["短板"], 1):
            L.append(f"  {i}. {s['维度']}（{s['得分']}分）")
            L.append(f"     {s['改进方向']}")
        L.append("")
    else:
        L.append("--- 各维度均达标，无明显短板 ---")
        L.append("")
    L.append("--- 决策建议 ---")
    L.append(f"  {r['建议']}")
    L.append("=" * 62)
    L.append("注：评分模型基于行业经验阈值，建议结合自身供应链与运营能力校准。")
    return "\n".join(L)


def _self_test() -> int:
    print("运行 product_score.py 自检...")
    ok = True

    # 用例1: 权重之和必须为 1
    if abs(sum(WEIGHTS.values()) - 1.0) > 1e-9:
        print(f"  [FAIL] 用例1 权重和应为1 实际{sum(WEIGHTS.values())}"); ok = False
    else:
        print("  [PASS] 用例1 权重归一")

    # 用例2: 全优输入应得高分并判为优质款
    good = evaluate(gross_margin=75, search_index=50000, supply_ratio=8,
                    return_rate=6, weight_kg=0.3, moq=50,
                    restock_days=5, trend="up")
    if good["总分"] < 75 or good["结论"] != "优质款":
        print(f"  [FAIL] 用例2 全优应≥75 实际{good['总分']} {good['结论']}")
        ok = False
    else:
        print(f"  [PASS] 用例2 全优场景得分 {good['总分']}")

    # 用例3: 全劣输入应判为放弃
    bad = evaluate(gross_margin=15, search_index=200, supply_ratio=0.3,
                   return_rate=55, weight_kg=8, moq=5000,
                   restock_days=45, trend="down")
    if bad["总分"] >= 60 or bad["结论"] != "建议放弃":
        print(f"  [FAIL] 用例3 全劣应<60 实际{bad['总分']}"); ok = False
    else:
        print(f"  [PASS] 用例3 全劣场景得分 {bad['总分']}")

    # 用例4: 总分必须等于各维度加权和
    calc = sum(good["加权贡献"].values())
    if abs(calc - good["总分"]) > 0.15:
        print(f"  [FAIL] 用例4 加权和{calc} != 总分{good['总分']}"); ok = False
    else:
        print("  [PASS] 用例4 加权计算自洽")

    # 用例5: 所有得分必须落在 0~100
    for k, v in list(good["各维度得分"].items()) + list(bad["各维度得分"].items()):
        if not 0 <= v <= 100:
            print(f"  [FAIL] 用例5 {k} 得分越界 {v}"); ok = False
            break
    else:
        print("  [PASS] 用例5 得分范围合法")

    # 用例6: 单调性——毛利率越高，利润分越高
    if not score_profit(70) > score_profit(50) > score_profit(30):
        print("  [FAIL] 用例6 利润分非单调递增"); ok = False
    else:
        print("  [PASS] 用例6 利润维度单调性")

    # 用例7: 单调性——退货率越高，退货分越低
    if not score_return(10) > score_return(30) > score_return(50):
        print("  [FAIL] 用例7 退货分非单调递减"); ok = False
    else:
        print("  [PASS] 用例7 退货维度单调性")

    # 用例8: 趋势修正生效
    up = evaluate(60, 5000, 3, 20, 0.5, 100, 10, trend="up")
    down = evaluate(60, 5000, 3, 20, 0.5, 100, 10, trend="down")
    if not up["总分"] > down["总分"]:
        print("  [FAIL] 用例8 上升趋势未加分"); ok = False
    else:
        print("  [PASS] 用例8 趋势修正生效")

    # 用例9: 短板识别——低毛利必须被列为短板
    weak_names = [s["维度"] for s in bad["短板"]]
    if "利润空间" not in weak_names:
        print(f"  [FAIL] 用例9 低毛利未识别为短板 {weak_names}"); ok = False
    else:
        print("  [PASS] 用例9 短板识别准确")

    # 用例10: 非法输入拦截
    try:
        evaluate(60, 5000, 3, 20, 0.5, 100, 10, trend="rising")
        print("  [FAIL] 用例10 非法trend未报错"); ok = False
    except ValueError:
        print("  [PASS] 用例10 非法参数拦截")

    print("自检结果:", "全部通过" if ok else "存在失败")
    return 0 if ok else 1


def main() -> int:
    p = argparse.ArgumentParser(description="选品六维评分模型")
    p.add_argument("--gross-margin", type=float, help="预估毛利率%%")
    p.add_argument("--search-index", type=float, help="关键词月搜索量/内容热度指数")
    p.add_argument("--trend", default="flat", choices=["up", "flat", "down"],
                   help="需求趋势，默认flat")
    p.add_argument("--supply-ratio", type=float, help="供需比=搜索人气/在售商品数")
    p.add_argument("--return-rate", type=float, help="预估退货率%%")
    p.add_argument("--weight", type=float, dest="weight_kg", help="单件重量kg")
    p.add_argument("--fragile", action="store_true", help="是否易碎品")
    p.add_argument("--moq", type=float, help="供应商起订量")
    p.add_argument("--restock-days", type=float, help="翻单补货天数")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.add_argument("--self-test", action="store_true", help="运行内置自检")
    a = p.parse_args()

    if a.self_test:
        return _self_test()

    required = [a.gross_margin, a.search_index, a.supply_ratio,
                a.return_rate, a.weight_kg, a.moq, a.restock_days]
    if None in required:
        p.print_help()
        print("\n[错误] 必须提供全部六维输入参数："
              "--gross-margin --search-index --supply-ratio "
              "--return-rate --weight --moq --restock-days")
        return 2

    try:
        res = evaluate(a.gross_margin, a.search_index, a.supply_ratio,
                       a.return_rate, a.weight_kg, a.moq, a.restock_days,
                       a.trend, a.fragile)
    except ValueError as e:
        print(f"[错误] {e}")
        return 2

    print(json.dumps(res, ensure_ascii=False, indent=2) if a.json else render(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
