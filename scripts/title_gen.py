#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
商品标题生成器 —— 按平台字数限制与结构公式批量产出候选标题，并做合规预检。

与"拍脑袋写标题"不同，本脚本把标题当成一个可计算的拼装问题：
核心词定搜索入口，属性词定长尾覆盖，场景/人群词定点击人群，
再用平台字数上限做硬约束，用广告法词库做发布前预检。

结构公式（与 references/listing-and-content.md 一致）:
  标题 = [人群/场景词] + 核心词 + 属性词组合
  - 核心词决定能被什么搜索词命中，必须出现且尽量靠前
  - 属性词（材质/规格/型号/功能）覆盖长尾搜索
  - 场景/人群词提升点击率，但不得虚构

字数口径: 各平台按「字符数」计（1 个汉字 = 2 字符）。下表为公开常见参考值，
平台规则持续调整，**发布前务必以商家后台实际提示为准**；
也可用 --limit 手动覆盖。

用法:
  python title_gen.py --core "汽车LED大灯" --attrs "激光,双铜管,IP68,H7" \
      --scenes "货车,夜行" --platform pdd
  python title_gen.py --core "保温杯" --attrs "316不锈钢,500ml" --n 8 --json
  python title_gen.py --self-test
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

try:
    from platform_fees import disp_width, pad
except ImportError:  # 允许从其他目录调用
    import os

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from platform_fees import disp_width, pad

# 合规预检直接复用 compliance.py 的词库，保证"生成即过检"口径一致
try:
    from compliance import RULES as COMPLIANCE_RULES
except ImportError:
    COMPLIANCE_RULES = {}

# 各平台标题字符数上限（公开常见参考值，以商家后台实际限制为准）
PLATFORM_TITLE_LIMIT: dict[str, tuple[str, int]] = {
    "taobao": ("淘宝", 60),
    "tmall": ("天猫", 60),
    "pdd": ("拼多多", 60),
    "jd": ("京东", 50),
    "douyin": ("抖音电商", 60),
    "xiaohongshu": ("小红书", 40),
    "kuaishou": ("快手小店", 60),
    "wxstore": ("微信小店", 60),
}

_LEVEL_ORDER = {"P0": 0, "P1": 1, "P2": 2}


def scan_compliance(text: str) -> list[dict]:
    """对单条标题做广告法预检，返回命中明细（复用 compliance 词库）。"""
    hits = []
    lower = text.lower()
    for word, (level, category, suggest) in COMPLIANCE_RULES.items():
        if word.lower() in lower:
            hits.append({"违禁词": word, "风险级别": level,
                         "类别": category, "整改建议": suggest})
    hits.sort(key=lambda h: _LEVEL_ORDER[h["风险级别"]])
    return hits


def _fit(tokens: list[str], limit: int) -> str:
    """把 token 列表拼进字数上限：超长时从尾部逐个丢弃（核心词永远保留）。"""
    kept = list(tokens)
    while len(kept) > 1 and disp_width("".join(kept)) > limit:
        kept.pop()
    return "".join(kept)


def _score(title: str, core: str, attrs: list[str], scenes: list[str],
           limit: int) -> float:
    """候选标题打分（满分 100）：核心词位置 30 + 长度利用率 30 + 词覆盖 40。"""
    w = disp_width(title)
    # 核心词越靠前，搜索匹配权重越高（前 6 字符内出现记满分）
    pos = title.find(core)
    pos_score = 30.0 if 0 <= pos <= 6 else (15.0 if pos > 6 else 0.0)
    len_score = min(w / limit, 1.0) * 30.0
    pool = attrs + scenes
    covered = sum(1 for t in pool if t in title)
    cov_score = (covered / len(pool) * 40.0) if pool else 40.0
    return round(pos_score + len_score + cov_score, 1)


def generate(core: str, attrs: list[str], scenes: list[str],
             limit: int, n: int = 5) -> list[dict]:
    """
    生成候选标题并排序。

    返回列表，每项含 标题/字符数/得分/合规命中。
    命中 P0 的候选会被直接剔除（绝不可建议发布），P1/P2 仅标注提醒。
    """
    if not core or not core.strip():
        raise ValueError("核心词不能为空")
    core = core.strip()
    attrs = [a.strip() for a in attrs if a and a.strip()]
    scenes = [s.strip() for s in scenes if s and s.strip()]

    candidates: set[str] = set()

    # 模板1: 核心词 + 属性两两组合 + 场景
    for combo in itertools.permutations(attrs, min(2, len(attrs))):
        for sc in scenes or [""]:
            tokens = [core, *combo] + ([sc] if sc else [])
            candidates.add(_fit(tokens, limit))

    # 模板2: 场景词 + 核心词 + 属性组合
    for sc in scenes:
        for combo in itertools.permutations(attrs, min(2, len(attrs))):
            candidates.add(_fit([sc, core, *combo], limit))

    # 模板3: 单属性 + 核心词 + 剩余属性
    for first in attrs:
        rest = [a for a in attrs if a != first]
        candidates.add(_fit([first, core, *rest], limit))

    # 模板4: 核心词 + 全部属性 + 全部场景（靠 _fit 截断，吃满长度利用率）
    candidates.add(_fit([core, *attrs, *scenes], limit))

    # 模板5: 场景 + 属性 + 核心词（人群前置，偏内容平台）
    for sc in scenes:
        candidates.add(_fit([sc, *attrs[:2], core], limit))

    results = []
    for t in sorted(candidates):  # 排序遍历保证跨进程输出确定性
        if core not in t:  # 截断后丢了核心词的候选不可用
            continue
        hits = scan_compliance(t)
        if any(h["风险级别"] == "P0" for h in hits):
            continue  # P0 命中直接剔除，绝不建议
        results.append({
            "标题": t,
            "字符数": disp_width(t),
            "得分": _score(t, core, attrs, scenes, limit),
            "合规提醒": hits,
        })

    results.sort(key=lambda r: r["得分"], reverse=True)
    return results[:max(1, n)]


def render(core: str, platform: str, limit: int, results: list[dict]) -> str:
    L = ["=" * 64, "               商品标题候选报告", "=" * 64]
    pname = PLATFORM_TITLE_LIMIT.get(platform, (platform or "自定义", limit))[0]
    L.append(f"核心词: {core} | 平台: {pname} | 字数上限: {limit} 字符")
    L.append("")
    if not results:
        L.append("  未产出可用候选。请检查核心词/属性词是否本身含 P0 违禁词。")
        L.append("=" * 64)
        return "\n".join(L)
    for i, r in enumerate(results, 1):
        L.append(f"--- 候选 {i} | 得分 {r['得分']} | {r['字符数']}/{limit} 字符 ---")
        L.append(f"  {r['标题']}")
        if r["合规提醒"]:
            for h in r["合规提醒"]:
                L.append(f"  [{h['风险级别']}] 含「{h['违禁词']}」: {h['整改建议']}")
        else:
            L.append("  [OK] 合规预检通过")
        L.append("")
    L.append("提示: 得分仅为结构参考，最终应结合搜索词数据（生意参谋/多多情报通等）")
    L.append("      验证核心词真实搜索量后定稿；字数上限以商家后台实际提示为准。")
    L.append("=" * 64)
    return "\n".join(L)


def _self_test() -> int:
    print("运行 title_gen.py 自检...")
    ok = True

    core = "汽车LED大灯"
    attrs = ["激光", "双铜管", "IP68", "H7"]
    scenes = ["货车", "夜行"]

    # 用例1: 所有候选不超长且包含核心词
    rs = generate(core, attrs, scenes, limit=60, n=10)
    if rs and all(r["字符数"] <= 60 and core in r["标题"] for r in rs):
        print(f"  [PASS] 用例1 {len(rs)} 条候选均不超长且含核心词")
    else:
        print(f"  [FAIL] 用例1 候选违规: {rs}")
        ok = False

    # 用例2: 含 P0 词的输入不得产出含 P0 的候选
    rs2 = generate(core, ["最好", "激光"], [], limit=60, n=10)
    bad = [r for r in rs2 if any(h["风险级别"] == "P0" for h in scan_compliance(r["标题"]))]
    if not bad:
        print("  [PASS] 用例2 P0 词候选被剔除")
    else:
        print(f"  [FAIL] 用例2 仍产出P0候选: {[r['标题'] for r in bad]}")
        ok = False

    # 用例3: 极小上限截断后仍保留核心词（核心词自身不超限时）
    rs3 = generate("保温杯", ["316不锈钢", "500ml", "便携"], [], limit=24, n=5)
    if rs3 and all("保温杯" in r["标题"] and r["字符数"] <= 24 for r in rs3):
        print("  [PASS] 用例3 小上限截断保留核心词")
    else:
        print(f"  [FAIL] 用例3 截断异常: {rs3}")
        ok = False

    # 用例4: 结果确定性（同输入两次生成一致）
    if generate(core, attrs, scenes, 60, 5) == generate(core, attrs, scenes, 60, 5):
        print("  [PASS] 用例4 生成结果确定性")
    else:
        print("  [FAIL] 用例4 同输入输出不一致")
        ok = False

    # 用例5: 空核心词必须抛错
    try:
        generate("", attrs, scenes, 60)
        print("  [FAIL] 用例5 空核心词未报错")
        ok = False
    except ValueError:
        print("  [PASS] 用例5 空核心词拦截")

    # 用例6: 合规词库必须成功加载
    if len(COMPLIANCE_RULES) >= 100:
        print(f"  [PASS] 用例6 合规词库已加载 {len(COMPLIANCE_RULES)} 条")
    else:
        print(f"  [FAIL] 用例6 合规词库加载异常: {len(COMPLIANCE_RULES)} 条")
        ok = False

    print("自检结果:", "全部通过" if ok else "存在失败")
    return 0 if ok else 1


def main() -> int:
    p = argparse.ArgumentParser(
        description="商品标题生成器：结构公式拼装 + 字数约束 + 广告法预检",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='示例: python title_gen.py --core "汽车LED大灯" '
               '--attrs "激光,双铜管,IP68,H7" --scenes "货车" --platform pdd',
    )
    p.add_argument("--core", help="核心词（搜索主入口，必填）")
    p.add_argument("--attrs", default="", help="属性词，逗号分隔（材质/规格/型号/功能）")
    p.add_argument("--scenes", default="", help="场景/人群词，逗号分隔（可选）")
    p.add_argument("--platform", default=None,
                   help="平台代号: " + ", ".join(sorted(PLATFORM_TITLE_LIMIT)))
    p.add_argument("--limit", type=int, default=None,
                   help="手动指定字符数上限（覆盖平台默认）")
    p.add_argument("--n", type=int, default=5, help="输出候选条数，默认 5")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.add_argument("--self-test", action="store_true", help="运行内置自检")
    a = p.parse_args()

    if a.self_test:
        return _self_test()
    if not a.core:
        p.print_help()
        print("\n[错误] 必须提供 --core 核心词")
        return 2

    if a.limit is not None:
        limit = a.limit
    elif a.platform:
        if a.platform not in PLATFORM_TITLE_LIMIT:
            print(f"[错误] 未知平台 '{a.platform}'，"
                  f"可选: {', '.join(sorted(PLATFORM_TITLE_LIMIT))}")
            return 2
        limit = PLATFORM_TITLE_LIMIT[a.platform][1]
    else:
        limit = 60  # 默认取最通用的 60 字符（淘宝/拼多多/抖音一致）

    if limit <= 0:
        print("[错误] --limit 必须为正整数")
        return 2

    attrs = [x for x in a.attrs.replace("，", ",").split(",") if x.strip()]
    scenes = [x for x in a.scenes.replace("，", ",").split(",") if x.strip()]

    try:
        results = generate(a.core, attrs, scenes, limit, a.n)
    except ValueError as e:
        print(f"[错误] {e}")
        return 2

    if a.json:
        out = {
            "核心词": a.core, "平台": a.platform or "custom",
            "字数上限": limit, "候选数": len(results), "候选": results,
            "提示": "字数上限为公开参考值，以商家后台实际提示为准",
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(render(a.core, a.platform, limit, results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
