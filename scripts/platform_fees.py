#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
国内主流电商平台费率参考表（共享模块）。

【重要】以下费率为公开可查的常见参考区间，平台政策会调整，
使用前必须以商家后台「费率公示 / 计费规则」页面的最新数据为准。
脚本默认取区间中位数，所有数值均可通过 --commission 等参数手动覆盖。

字段说明:
  commission      平台类目佣金 / 技术服务费率（百分比）
  payment_fee     支付通道手续费（百分比），部分平台已并入佣金
  note            计费口径备注
"""

from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 平台代号 -> 费率参考
PLATFORM_FEES: dict[str, dict] = {
    "taobao": {
        "name": "淘宝（个人/企业店）",
        "commission": 0.6,
        "payment_fee": 0.0,
        "commission_range": (0.6, 0.6),
        "note": "淘宝无类目佣金，主要为基础软件服务费；支付手续费通常已含。",
    },
    "tmall": {
        "name": "天猫",
        "commission": 4.0,
        "payment_fee": 0.6,
        "commission_range": (2.0, 5.0),
        "note": "按类目扣点，服饰/美妆多在5%，3C数码多在2%；另有年费（可返还）。",
    },
    "jd": {
        "name": "京东POP",
        "commission": 5.0,
        "payment_fee": 0.6,
        "commission_range": (2.0, 8.0),
        "note": "按类目扣点，家电类偏低、服饰/家居类偏高；另有平台使用费。",
    },
    "pdd": {
        "name": "拼多多",
        "commission": 0.6,
        "payment_fee": 0.0,
        "commission_range": (0.6, 0.6),
        "note": "多数类目仅收0.6%支付手续费；百亿补贴/特殊类目另有扣点。",
    },
    "douyin": {
        "name": "抖音电商",
        "commission": 3.0,
        "payment_fee": 0.0,
        "commission_range": (1.0, 5.0),
        "note": "类目技术服务费1%~5%；若走达人分销，需另计10%~30%达人佣金。",
    },
    "kuaishou": {
        "name": "快手小店",
        "commission": 5.0,
        "payment_fee": 0.0,
        "commission_range": (1.0, 5.0),
        "note": "类目服务费；达人分销佣金另计。",
    },
    "xiaohongshu": {
        "name": "小红书商城",
        "commission": 5.0,
        "payment_fee": 0.0,
        "commission_range": (1.0, 5.0),
        "note": "多数类目5%佣金；博主带货佣金另计。",
    },
    "wxstore": {
        "name": "微信小店",
        "commission": 2.0,
        "payment_fee": 0.6,
        "commission_range": (1.0, 5.0),
        "note": "类目技术服务费；视频号带货达人佣金另计。",
    },
}

# 行业常见转化基准（用于诊断对标）。来源为公开行业报告的经验区间，
# 仅作粗略参照，实际应以商家后台「行业均值 / 同层商家对比」为准。
BENCHMARK = {
    "click_rate": (2.0, 5.0),        # 曝光->点击 %
    "cart_rate": (5.0, 12.0),        # 点击->加购 %
    "order_rate": (3.0, 8.0),        # 点击->下单 %
    "pay_rate": (60.0, 85.0),        # 下单->支付 %
    "overall_cvr": (1.5, 4.0),       # 点击->支付 %
    "refund_rate": (5.0, 20.0),      # 退款率 %
}


def disp_width(s: str) -> int:
    """计算字符串在等宽终端下的显示宽度（中文/全角算2列）。"""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def pad(s: str, n: int) -> str:
    """按显示宽度右侧补空格，保证含中文的列能对齐。"""
    return s + " " * max(0, n - disp_width(s))


def get_platform(code: str) -> dict:
    """按代号取平台费率；未知代号抛出带可选项提示的异常。"""
    key = (code or "").strip().lower()
    if key not in PLATFORM_FEES:
        raise KeyError(
            f"未知平台代号 '{code}'。可选: {', '.join(sorted(PLATFORM_FEES))}"
        )
    return PLATFORM_FEES[key]


def list_platforms() -> str:
    """返回平台费率表的可读文本。"""
    lines = ["平台费率参考表（务必以平台最新公示为准）", "-" * 68]
    header = f"{'代号':<12}{'名称':<16}{'佣金%':<10}{'支付%':<8}"
    lines.append(header)
    for code, info in PLATFORM_FEES.items():
        lo, hi = info["commission_range"]
        rng = f"{lo}~{hi}" if lo != hi else f"{lo}"
        lines.append(
            f"{code:<12}{info['name']:<16}{rng:<10}{info['payment_fee']:<8}"
        )
        lines.append(f"{'':<12}└ {info['note']}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(list_platforms())
