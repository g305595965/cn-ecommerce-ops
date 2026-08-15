#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时数据助手 live.py —— 把"外部实时行情"接入到各计算器的桥梁。

背景
----
本技能的计算器(pricing / ad_calc / product_score / diagnose)要做精确测算，
依赖真实参数：平台类目佣金率、类目退货率、1688 实时进货成本、关键词搜索量、
行业点击率/转化率等。这些数字若靠人工凭记忆填，极易过时或拍脑袋——
"估算"正是多数电商决策翻车的根源。

本脚本定义「实时数据契约」，让 Agent(或用户)先用 WebSearch / WebFetch 拉取
当前真实值，再一键灌入计算器：

  sources  列出每个平台可实时核验的权威数据源 URL，供 Agent 用 WebFetch 拉取
          当前真实佣金率 / 退货率 / 进货价 / 搜索量（无需任何 API key）。
  schema   打印 live_data.json 的字段规范，告诉 Agent 该收集哪些数、单位是什么。
  plan     给定一份 live_data.json，生成可直接执行的 pricing / ad_calc /
           product_score / diagnose 命令，把实时数据一键灌入计算器。
  stamp    输出当前日期，用于报告"数据截至"水印，提醒以商家后台为准。
  fetch    尝试用 urllib 直连一个稳定的实时公开接口(汇率)，演示本机直连能力；
           网络受限时优雅降级，并提示改用 Agent 侧 WebFetch。

设计原则：本脚本自身不抓取电商站点(避免反爬/JS 渲染问题)，而是把
"实时数据如何获取 + 如何落地到计算器"标准化，保证整条链路可复现、可审计。

用法:
  python live.py sources --platform douyin
  python live.py schema
  python live.py plan --in live_data.json
  python live.py stamp
  python live.py fetch fx
  python live.py --self-test
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# ---------------------------------------------------------------
# 1. 实时数据源注册表（Agent 用 WebFetch / WebSearch 拉取，无需 key）
#    均为各平台官方公示页或公开指数工具，权威性高于社群经验值。
# ---------------------------------------------------------------
SOURCES: dict[str, dict] = {
    "taobao": {
        "name": "淘宝 / 淘宝天猫",
        "佣金与费率": "https://rule.taobao.com（淘宝规则中心 → 资费/软件服务费）",
        "关键词热度": "https://sycm.taobao.com（生意参谋，需登录，看「搜索词分析」）",
        "进货价": "https://www.1688.com（搜商品名，按销量排序看档口拿货价）",
    },
    "tmall": {
        "name": "天猫",
        "佣金与费率": "https://rule.tmall.com（天猫规则 → 资费标准 / 各类目费率表）",
        "关键词热度": "https://sycm.taobao.com（生意参谋，需登录）",
        "进货价": "https://www.1688.com",
    },
    "jd": {
        "name": "京东 POP",
        "佣金与费率": "https://rule.jd.com（京东规则 → 开放平台资费标准）",
        "关键词热度": "https://zhongce.jd.com / 京东商智（需登录）",
        "进货价": "https://www.1688.com",
    },
    "pdd": {
        "name": "拼多多",
        "佣金与费率": "https://jinbao.pinduoduo.com（拼多多商家后台 → 费率公示）",
        "关键词热度": "https://pdd.heshu.com（多多情报通，需订阅）",
        "进货价": "https://www.1688.com",
    },
    "douyin": {
        "name": "抖音电商 / 抖店",
        "佣金与费率": "https://school.jinritemai.com（抖店学习中心 → 资费规则）",
        "关键词热度": "https://trendinsight.oceanengine.com（巨量算数，公开趋势）",
        "进货价": "https://www.1688.com / https://haohuo.jinritemai.com（抖批）",
    },
    "kuaishou": {
        "name": "快手小店",
        "佣金与费率": "https://s.kwaixiaodian.com（快手小店 → 资费说明）",
        "关键词热度": "https://www.kuaishou.com/agent（快手磁力指数，需登录）",
        "进货价": "https://www.1688.com",
    },
    "xiaohongshu": {
        "name": "小红书商城",
        "佣金与费率": "https://pro.xiaohongshu.com（蒲公英 / 专业号 → 佣金规则）",
        "关键词热度": "https://pro.xiaohongshu.com（专业号后台 → 品类热搜）",
        "进货价": "https://www.1688.com",
    },
    "wxstore": {
        "name": "微信小店 / 视频号",
        "佣金与费率": "https://store.weixin.qq.com（微信小店 → 类目技术服务费）",
        "关键词热度": "https://index.weixin.qq.com（微信指数，公开）",
        "进货价": "https://www.1688.com",
    },
}

# 通用实时源（跨平台）
GENERIC_SOURCES = {
    "关键词趋势(抖音)": "https://trendinsight.oceanengine.com",
    "微信指数": "https://index.weixin.qq.com",
    "百度指数": "https://index.baidu.com",
    "1688 进货价": "https://www.1688.com",
    "实时汇率(跨境成本)": "https://open.er-api.com/v1/latest/CNY",
}


# ---------------------------------------------------------------
# 2. live_data.json 字段规范（契约）
# ---------------------------------------------------------------
SCHEMA = {
    "meta": {
        "keyword": "商品关键词，如『不锈钢保温杯』（用于溯源与报告）",
        "platform": "平台代号，见 sources：taobao/tmall/jd/pdd/douyin/...",
        "as_of": "数据日期 YYYY-MM-DD，自动填当前日期；报告水印用",
        "note": "数据来源说明，如『佣金率取自抖店学习中心资费规则』",
    },
    "cost": "单件进货成本(元)，来自 1688 实时档口价",
    "price": "目标售价 / 竞品到手价(元)",
    "commission": "实时类目佣金率(%)，来自平台资费公示",
    "payment_fee": "支付通道费率(%)，可选，缺省取平台默认",
    "shipping": "单件快递成本(元)",
    "packaging": "包材成本(元)",
    "return_rate": "实时类目退货率(%)，来自平台/行业报告",
    "ad_ratio": "计划推广费占成交额(%)，如直通车/千川预算占比",
    "search_index": "关键词月搜索量 / 内容热度指数",
    "trend": "需求趋势 up/flat/down",
    "supply_ratio": "供需比 = 搜索人气 / 在售商品数",
    "weight_kg": "单件重量(kg)，物流分用",
    "fragile": "是否易碎 bool",
    "moq": "供应商起订量",
    "restock_days": "翻单补货天数",
    "cvr": "行业/竞品 点击->支付 转化率(%)",
    "cpc": "平均点击花费(元)",
    "impression": "曝光量（diagnose 用）",
    "click": "点击数（diagnose 用）",
    "cart": "加购数（diagnose 用，可选）",
    "order": "下单数（diagnose 用）",
    "paid": "支付数（diagnose 用）",
    "refund": "退款数（diagnose 用，可选）",
    "gmv": "支付金额（diagnose 用，可选）",
}


def _today() -> str:
    return _dt.date.today().isoformat()


def cmd_sources(platform: str | None) -> int:
    keys = [platform] if platform else list(SOURCES)
    if platform and platform not in SOURCES:
        print(f"[错误] 未知平台 '{platform}'，可选: {', '.join(SOURCES)}")
        return 2
    print("实时数据源注册表（Agent 用 WebFetch / WebSearch 拉取，无需 API key）")
    print("=" * 64)
    for k in keys:
        info = SOURCES[k]
        print(f"\n[{info['name']}] ({k})")
        for label, url in info.items():
            if label == "name":
                continue
            print(f"  {label}: {url}")
    print("\n--- 跨平台通用源 ---")
    for label, url in GENERIC_SOURCES.items():
        print(f"  {label}: {url}")
    print("\n提示: 拉到数字后写入 live_data.json，再用 `live.py plan` 生成命令。")
    return 0


def cmd_schema() -> int:
    print("live_data.json 字段规范（契约）")
    print("=" * 64)
    print("把 WebFetch / WebSearch 拉到的实时值填进对应字段，单位已标注。")
    print("带 meta 的为主信息；其余为各计算器入参。缺省字段会被跳过或用平台默认。")
    print("-" * 64)
    for k, v in SCHEMA.items():
        if isinstance(v, dict):
            print(f"\n[{k}]")
            for kk, vv in v.items():
                print(f"  {kk}: {vv}")
        else:
            print(f"  {k}: {v}")
    print("\n示例:")
    ex = {
        "meta": {"keyword": "不锈钢保温杯", "platform": "douyin",
                  "as_of": _today(), "note": "佣金率取自抖店资费规则"},
        "cost": 18.5, "price": 59.9, "commission": 3.0, "shipping": 3.0,
        "packaging": 1.0, "return_rate": 12.0, "ad_ratio": 15.0,
        "search_index": 120000, "trend": "up", "supply_ratio": 4.5,
        "weight_kg": 0.45, "moq": 50, "restock_days": 7,
        "cvr": 2.5, "cpc": 1.2,
        "impression": 200000, "click": 3000, "cart": 250,
        "order": 150, "paid": 90, "refund": 12, "gmv": 5300,
    }
    print(json.dumps(ex, ensure_ascii=False, indent=2))
    return 0


def _q(val) -> str:
    """把数值格式化为简洁命令行参数。"""
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, float):
        # 去掉多余小数
        return ("%g" % val)
    return str(val)


def build_plan(data: dict) -> dict:
    """根据 live_data.json 生成各计算器命令片段与执行顺序。"""
    meta = data.get("meta", {})
    plat = data.get("platform") or meta.get("platform")
    as_of = data.get("as_of") or meta.get("as_of") or _today()

    steps = []

    # Step 1: pricing（需要 cost/price/commission/return_rate 等）
    p_args = []
    if plat:
        p_args.append(f"--platform {plat}")
    for f in ("cost", "price", "commission", "payment_fee", "shipping",
              "packaging", "return_rate", "ad_ratio"):
        if f in data and data[f] is not None:
            p_args.append(f"--{f.replace('_', '-')} {_q(data[f])}")
    if p_args:
        steps.append({
            "step": 1,
            "tool": "pricing.py",
            "目的": "用实时进货价/佣金率/退货率算真实利润、保本价、毛利率",
            "cmd": "python pricing.py " + " ".join(p_args) + " --json",
            "必填缺失": [f for f in ("cost", "price") if f not in data],
        })

    # Step 2: product_score（需要 gross_margin，由 pricing 给出；其余取实时值）
    # 注：product_score 的「单件重量」参数为 --weight（dest=weight_kg），
    # 与字段名不一致，需单独映射，不能直接 replace('_','-')。
    FLAG_OVERRIDE = {"weight_kg": "weight"}
    s_args = []
    for f in ("search_index", "trend", "supply_ratio", "return_rate",
              "weight_kg", "moq", "restock_days"):
        if f in data and data[f] is not None:
            flag = FLAG_OVERRIDE.get(f, f.replace("_", "-"))
            s_args.append(f"--{flag} {_q(data[f])}")
    # fragile 是布尔 flag，仅当为 True 时输出 --fragile（False 直接省略）
    if data.get("fragile") is True:
        s_args.append("--fragile")
    gm = data.get("gross_margin")
    if gm is not None:
        s_args.append(f"--gross-margin {_q(gm)}")
    steps.append({
        "step": 2,
        "tool": "product_score.py",
        "目的": "六维选品评分（毛利率用 Step1 的输出，保证两工具串联自洽）",
        "cmd": "python product_score.py " + " ".join(s_args) + " --json",
        "必填缺失": [f for f in ("search_index", "supply_ratio",
                                  "return_rate", "weight_kg", "moq",
                                  "restock_days") if f not in data]
                     + (["gross_margin(先跑 pricing)"] if gm is None else []),
    })

    # Step 3: ad_calc（需要 gross_margin/cvr/cpc；price 取实时）
    a_args = []
    if "price" in data:
        a_args.append(f"--price {_q(data['price'])}")
    if gm is not None:
        a_args.append(f"--gross-margin {_q(gm)}")
    for f in ("cvr", "cpc"):
        if f in data and data[f] is not None:
            a_args.append(f"--{f} {_q(data[f])}")
    if a_args:
        steps.append({
            "step": 3,
            "tool": "ad_calc.py",
            "目的": "用实时毛利率/转化率/CPC 算保本 ROI 与最高出价",
            "cmd": "python ad_calc.py " + " ".join(a_args) + " --json",
            "必填缺失": [f for f in ("price", "cvr", "cpc") if f not in data]
                         + (["gross_margin(先跑 pricing)"] if gm is None else []),
        })

    # Step 4: diagnose（漏斗）
    d_args = []
    for f in ("impression", "click", "cart", "order", "paid", "refund", "gmv"):
        if f in data and data[f] is not None:
            d_args.append(f"--{f} {_q(data[f])}")
    req = ("impression", "click", "order", "paid")
    if any(f in data for f in req):
        steps.append({
            "step": 4,
            "tool": "diagnose.py",
            "目的": "用实时店铺漏斗数据定位瓶颈环节",
            "cmd": "python diagnose.py " + " ".join(d_args) + " --json",
            "必填缺失": [f for f in req if f not in data],
        })

    return {
        "meta": {
            "keyword": meta.get("keyword"),
            "platform": plat,
            "as_of": as_of,
            "note": meta.get("note"),
        },
        "数据新鲜度": f"数据截至 {as_of}，请以商家后台最新公示校准",
        "执行顺序": steps,
        "缺失提醒": [s for s in steps if s["必填缺失"]],
    }


def cmd_plan(path: str, as_json: bool) -> int:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except OSError as e:
        print(f"[错误] 无法读取 {path}: {e}")
        return 2
    except json.JSONDecodeError as e:
        print(f"[错误] {path} 不是合法 JSON: {e}")
        return 2

    plan = build_plan(data)

    if as_json:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    print("=" * 64)
    print("           实时数据 → 计算器执行计划")
    print("=" * 64)
    m = plan["meta"]
    print(f"商品: {m.get('keyword')} | 平台: {m.get('platform')} | 截至: {m.get('as_of')}")
    if m.get("note"):
        print(f"来源: {m['note']}")
    print(f"\n{plan['数据新鲜度']}\n")
    for s in plan["执行顺序"]:
        print(f"--- Step {s['step']}: {s['tool']} ---")
        print(f"  目的: {s['目的']}")
        print(f"  命令: {s['cmd']}")
        if s["必填缺失"]:
            print(f"  [!] 缺失必填: {', '.join(s['必填缺失'])}")
        print()
    miss = plan["缺失提醒"]
    if miss:
        print("[汇总] 以下命令缺必填字段，请先用 WebFetch/WebSearch 补齐实时值：")
        for s in miss:
            print(f"  - Step{s['step']} {s['tool']}: {', '.join(s['必填缺失'])}")
    else:
        print("[OK] 所有命令字段齐备，可直接复制执行。")
    print("=" * 64)
    return 0


def cmd_stamp() -> int:
    print(_today())
    return 0


def cmd_fetch(kind: str) -> int:
    """尝试本机直连实时公开接口；失败则优雅降级。"""
    if kind == "fx":
        url = "https://open.er-api.com/v1/latest/CNY"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                js = json.loads(r.read().decode("utf-8"))
            rates = js.get("rates", {})
            out = {k: rates.get(k) for k in ("USD", "EUR", "JPY", "HKD") if k in rates}
            print("实时汇率（来源 open.er-api.com，跨境成本换算用）：")
            for k, v in out.items():
                print(f"  1 CNY = {v} {k}")
            print(f"  数据时间: {js.get('time_last_update_utc', '未知')}")
            return 0
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 本机直连汇率接口失败: {e}")
            print("        网络受限环境下属正常，请改用 Agent 侧 WebFetch 拉取，")
            print("        或直接在商家后台/银行牌价查看实时汇率。")
            return 1
    print(f"[错误] 未知 fetch 类型 '{kind}'，支持: fx")
    return 2


def _self_test() -> int:
    print("运行 live.py 自检...")
    ok = True

    # 用例1: build_plan 能产出 4 步且命令非空
    sample = {
        "meta": {"keyword": "测试品", "platform": "douyin", "as_of": _today()},
        "cost": 18.5, "price": 59.9, "commission": 3.0, "shipping": 3.0,
        "return_rate": 12.0, "ad_ratio": 15.0, "search_index": 120000,
        "trend": "up", "supply_ratio": 4.5, "weight_kg": 0.45, "moq": 50,
        "restock_days": 7, "cvr": 2.5, "cpc": 1.2,
        "impression": 200000, "click": 3000, "order": 150, "paid": 90,
    }
    plan = build_plan(sample)
    if len(plan["执行顺序"]) != 4:
        print(f"  [FAIL] 用例1 期望4步, 实际 {len(plan['执行顺序'])}")
        ok = False
    else:
        print("  [PASS] 用例1 生成4步执行计划")
    for s in plan["执行顺序"]:
        if not s["cmd"].startswith("python "):
            print(f"  [FAIL] 用例1 {s['tool']} 命令非法: {s['cmd']}")
            ok = False
    else:
        print("  [PASS] 用例1 各步骤命令格式正确")

    # 用例2: 缺字段时必填缺失被标记
    partial = {"cost": 10, "platform": "taobao"}
    p2 = build_plan(partial)
    pricing_step = next(s for s in p2["执行顺序"] if s["tool"] == "pricing.py")
    if "price" not in pricing_step["必填缺失"]:
        print("  [FAIL] 用例2 缺 price 未被标记")
        ok = False
    else:
        print("  [PASS] 用例2 缺失必填字段正确标记")

    # 用例3: 缺 gross_margin 时 pricing 应在前、product_score/ad_calc 标记缺毛利率
    no_gm = {**sample}
    no_gm.pop("gross_margin", None)
    p3 = build_plan(no_gm)
    miss_tools = {s["tool"] for s in p3["缺失提醒"]}
    if "product_score.py" not in miss_tools or "ad_calc.py" not in miss_tools:
        print(f"  [FAIL] 用例3 缺毛利率未正确传导: {miss_tools}")
        ok = False
    else:
        print("  [PASS] 用例3 毛利率缺失链式传导正确")

    # 用例3b: fragile=True 应生成 --fragile 旗标而非 --fragile true
    frag = build_plan({"platform": "douyin", "cost": 10, "price": 30,
                       "fragile": True})
    fcmd = next(s["cmd"] for s in frag["执行顺序"] if s["tool"] == "product_score.py")
    if "--fragile" in fcmd and "--fragile true" not in fcmd and "--fragile false" not in fcmd:
        print("  [PASS] 用例3b fragile 旗标生成正确")
    else:
        print(f"  [FAIL] 用例3b fragile 处理错误: {fcmd}")
        ok = False
    # fragile=False 应省略
    frag0 = build_plan({"platform": "douyin", "cost": 10, "price": 30,
                        "fragile": False})
    fcmd0 = next(s["cmd"] for s in frag0["执行顺序"] if s["tool"] == "product_score.py")
    if "--fragile" not in fcmd0:
        print("  [PASS] 用例3c fragile=False 正确省略")
    else:
        print(f"  [FAIL] 用例3c fragile=False 未省略: {fcmd0}")
        ok = False

    # 用例3d: weight_kg 必须映射到 --weight 而非 --weight-kg
    w = build_plan({"platform": "douyin", "cost": 10, "price": 30,
                    "weight_kg": 0.4})
    wcmd = next(s["cmd"] for s in w["执行顺序"] if s["tool"] == "product_score.py")
    if "--weight 0.4" in wcmd and "--weight-kg" not in wcmd:
        print("  [PASS] 用例3d weight_kg 映射到 --weight 正确")
    else:
        print(f"  [FAIL] 用例3d weight 映射错误: {wcmd}")
        ok = False

    # 用例4: sources 注册表覆盖全部 8 平台
    if len(SOURCES) < 8:
        print(f"  [FAIL] 用例4 平台源不足8个, 实际 {len(SOURCES)}")
        ok = False
    else:
        print(f"  [PASS] 用例4 覆盖 {len(SOURCES)} 个平台数据源")

    # 用例5: stamp 返回合法日期
    import re
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", _today()):
        print("  [FAIL] 用例5 日期格式错误")
        ok = False
    else:
        print("  [PASS] 用例5 日期水印格式正确")

    print("自检结果:", "全部通过" if ok else "存在失败")
    return 0 if ok else 1


def main() -> int:
    p = argparse.ArgumentParser(
        description="实时数据助手：把外部实时行情接入各计算器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("sources", help="列出各平台实时数据源 URL")
    sp.add_argument("--platform", default=None, help="只列出某平台，如 douyin")

    sub.add_parser("schema", help="打印 live_data.json 字段规范")

    pp = sub.add_parser("plan", help="根据 live_data.json 生成执行命令")
    pp.add_argument("--in", dest="infile", required=True, help="live_data.json 路径")
    pp.add_argument("--json", action="store_true", help="输出 JSON")

    sub.add_parser("stamp", help="输出当前日期水印")

    fp = sub.add_parser("fetch", help="本机直连实时公开接口(演示)")
    fp.add_argument("kind", nargs="?", default="fx", help="fx=实时汇率")

    p.add_argument("--self-test", action="store_true", help="运行内置自检")

    a = p.parse_args()
    if a.self_test:
        return _self_test()
    if not a.cmd:
        p.print_help()
        return 2
    if a.cmd == "sources":
        return cmd_sources(a.platform)
    if a.cmd == "schema":
        return cmd_schema()
    if a.cmd == "plan":
        return cmd_plan(a.infile, a.json)
    if a.cmd == "stamp":
        return cmd_stamp()
    if a.cmd == "fetch":
        return cmd_fetch(a.kind)
    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
