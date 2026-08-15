#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cn-ecommerce-ops 全量验收测试。

三层验证：
  L1 单元层 —— 逐个运行各脚本内置 --self-test
  L2 集成层 —— 验证工具链之间的数据自洽（如 pricing 与 ad_calc 的保本 ROI 一致）
  L3 结构层 —— 校验 SKILL.md 元数据、文件完整性与文档引用有效性

用法:
  python tests/run_all.py
退出码 0 表示全部通过，非 0 表示存在失败。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
REFS = os.path.join(ROOT, "references")
PY = sys.executable

SCRIPT_FILES = [
    "pricing.py", "ad_calc.py", "diagnose.py",
    "compliance.py", "product_score.py", "live.py",
]
REF_FILES = [
    "platform-playbook.md", "product-selection.md",
    "listing-and-content.md", "operations-playbook.md",
]

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, msg: str = "") -> None:
    results.append((name, ok, msg))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {msg}" if msg else ""))


def run(args: list[str], cwd: str = SCRIPTS):
    """执行子进程，返回 (returncode, stdout+stderr)。"""
    p = subprocess.run(
        [PY] + args, cwd=cwd, capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


# ---------------- L1 单元层 ----------------
def layer1() -> None:
    print("\n[L1] 各脚本内置自检")
    for f in SCRIPT_FILES:
        path = os.path.join(SCRIPTS, f)
        if not os.path.exists(path):
            record(f"{f} 存在性", False, "文件缺失")
            continue
        code, out = run([f, "--self-test"])
        passed = code == 0 and "全部通过" in out
        detail = ""
        if not passed:
            fails = [l.strip() for l in out.splitlines() if "[FAIL]" in l]
            detail = fails[0] if fails else f"退出码 {code}"
        record(f"{f} 自检", passed, detail)


# ---------------- L2 集成层 ----------------
def layer2() -> None:
    print("\n[L2] 工具链集成自洽性")

    # 2.1 pricing 算出的毛利率喂给 ad_calc，两边保本 ROI 必须一致
    code, out = run(["pricing.py", "--cost", "35", "--price", "129",
                     "--platform", "tmall", "--shipping", "4.5",
                     "--packaging", "1.5", "--return-rate", "20",
                     "--ad-ratio", "15", "--json"])
    if code != 0:
        record("pricing JSON 输出", False, f"退出码 {code}")
        return
    try:
        pr = json.loads(out)
    except json.JSONDecodeError as e:
        record("pricing JSON 解析", False, str(e))
        return
    record("pricing JSON 输出", True)

    gm = pr["毛利率%"]
    be_roi_pricing = pr["保本ROI"]

    code, out = run(["ad_calc.py", "--price", "129", "--gross-margin", str(gm),
                     "--cvr", "2.5", "--cpc", "1.2", "--json"])
    try:
        ad = json.loads(out)
    except json.JSONDecodeError as e:
        record("ad_calc JSON 解析", False, str(e))
        return
    be_roi_ad = ad["保本ROI"]
    ok = abs(be_roi_pricing - be_roi_ad) < 0.02
    record("pricing<->ad_calc 保本ROI 一致",
           ok, f"{be_roi_pricing} vs {be_roi_ad}")

    # 2.2 保本售价代回 pricing，净利必须归零
    be_price = pr["保本售价"]
    code, out = run(["pricing.py", "--cost", "35", "--price", str(be_price),
                     "--platform", "tmall", "--shipping", "4.5",
                     "--packaging", "1.5", "--return-rate", "20",
                     "--ad-ratio", "15", "--json"])
    pr2 = json.loads(out)
    ok = abs(pr2["单均净利"]) < 0.05
    record("保本售价代回净利归零", ok, f"净利 {pr2['单均净利']}")

    # 2.3 compliance 命中 P0 时退出码必须为 1（供 CI 拦截）
    code, _ = run(["compliance.py", "--text", "全网最低价，销量第一"])
    record("compliance P0 退出码为1", code == 1, f"实际 {code}")

    # 2.4 compliance 合规文案退出码必须为 0
    code, _ = run(["compliance.py", "--text", "纯棉衬衫，支持七天无理由退换"])
    record("compliance 合规文案退出码为0", code == 0, f"实际 {code}")

    # 2.5 diagnose 与 product_score 的 JSON 结构可解析
    code, out = run(["diagnose.py", "--impression", "100000", "--click", "2000",
                     "--order", "100", "--paid", "60", "--json"])
    try:
        dg = json.loads(out)
        record("diagnose JSON 输出", "各环节指标" in dg)
    except json.JSONDecodeError as e:
        record("diagnose JSON 输出", False, str(e))

    code, out = run(["product_score.py", "--gross-margin", "62",
                     "--search-index", "8000", "--trend", "up",
                     "--supply-ratio", "3.2", "--return-rate", "18",
                     "--weight", "0.4", "--moq", "100",
                     "--restock-days", "10", "--json"])
    try:
        ps = json.loads(out)
        ok = 0 <= ps["总分"] <= 100
        record("product_score JSON 输出", ok, f"总分 {ps['总分']}")
    except json.JSONDecodeError as e:
        record("product_score JSON 输出", False, str(e))

    # 2.6 缺参时必须返回错误码 2 而非崩溃
    code, out = run(["pricing.py"])
    record("缺参优雅退出", code == 2 and "错误" in out, f"退出码 {code}")

    # 2.7 跨目录调用（验证 sys.path 兜底逻辑）
    code, out = run([os.path.join(SCRIPTS, "pricing.py"), "--cost", "10",
                     "--price", "50", "--platform", "taobao"], cwd=ROOT)
    record("跨目录调用不报 ImportError", code == 0 and "ModuleNotFound" not in out)

    # 2.8 live.py plan 能把实时数据 JSON 转成可执行命令
    import tempfile
    sample = {
        "meta": {"keyword": "测试品", "platform": "douyin", "as_of": "2026-08-15"},
        "cost": 18.5, "price": 59.9, "commission": 3.0, "shipping": 3.0,
        "return_rate": 12.0, "ad_ratio": 15.0, "search_index": 120000,
        "trend": "up", "supply_ratio": 4.5, "weight_kg": 0.45, "moq": 50,
        "restock_days": 7, "cvr": 2.5, "cpc": 1.2,
        "impression": 200000, "click": 3000, "order": 150, "paid": 90,
    }
    tf = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8")
    json.dump(sample, tf, ensure_ascii=False)
    tf.close()
    code, out = run(["live.py", "plan", "--in", tf.name, "--json"])
    try:
        lp = json.loads(out)
        steps = lp.get("执行顺序", [])
        by_tool = {s["tool"]: s for s in steps}
        # pricing 应齐备且含 --cost；product_score/ad_calc 应链式要求先算毛利率
        pricing_ok = ("pricing.py" in by_tool
                      and not by_tool["pricing.py"]["必填缺失"]
                      and "--cost" in by_tool["pricing.py"]["cmd"])
        chain_ok = ("product_score.py" in by_tool and "ad_calc.py" in by_tool
                    and any("gross_margin" in m
                            for m in by_tool["product_score.py"]["必填缺失"])
                    and any("gross_margin" in m
                            for m in by_tool["ad_calc.py"]["必填缺失"]))
        ok = code == 0 and len(steps) == 4 and pricing_ok and chain_ok
        detail = f"{len(steps)}步,pricing齐备={pricing_ok},链式要求毛利率={chain_ok}"
        record("live.py plan 生成可执命令", ok, detail)
    except json.JSONDecodeError as e:
        record("live.py plan JSON 解析", False, str(e))
    finally:
        os.unlink(tf.name)

    # 2.9 live.py sources 列出平台数据源
    code, out = run(["live.py", "sources", "--platform", "douyin"])
    record("live.py sources 正常", code == 0 and "抖店" in out)


# ---------------- L3 结构层 ----------------
def layer3() -> None:
    print("\n[L3] 技能结构与文档完整性")

    skill_path = os.path.join(ROOT, "SKILL.md")
    if not os.path.exists(skill_path):
        record("SKILL.md 存在", False)
        return
    with open(skill_path, "r", encoding="utf-8") as f:
        content = f.read()
    record("SKILL.md 存在", True)

    # frontmatter 校验
    m = re.match(r"^---\n(.*?)\n---\n", content, re.S)
    if not m:
        record("YAML frontmatter 格式", False, "未找到 frontmatter")
        return
    fm = m.group(1)
    record("YAML frontmatter 格式", True)
    for field in ("name:", "description:", "agent_created: true"):
        record(f"frontmatter 含 {field.rstrip(':')}", field in fm)

    # name 命名规范：小写字母、数字、连字符
    nm = re.search(r"^name:\s*(\S+)", fm, re.M)
    if nm:
        valid = bool(re.fullmatch(r"[a-z0-9][a-z0-9-]*", nm.group(1)))
        record("name 命名规范", valid, nm.group(1))

    # description 长度（过短会导致触发不准）
    dm = re.search(r"^description:\s*(.+)$", fm, re.M)
    if dm:
        ln = len(dm.group(1))
        record("description 长度充分", ln >= 60, f"{ln} 字符")

    # 文件完整性
    for f in SCRIPT_FILES:
        record(f"scripts/{f} 存在", os.path.exists(os.path.join(SCRIPTS, f)))
    for f in REF_FILES:
        record(f"references/{f} 存在", os.path.exists(os.path.join(REFS, f)))

    # SKILL.md 中引用的所有本地路径必须真实存在（防止文档说谎）
    refs = set(re.findall(r"`((?:scripts|references)/[\w\-./]+)`", content))
    missing = [r for r in refs if not os.path.exists(os.path.join(ROOT, r))]
    record("SKILL.md 引用路径均有效",
           not missing, f"缺失 {missing}" if missing else f"共 {len(refs)} 处")

    # references 文档中引用的脚本路径同样校验
    for rf in REF_FILES:
        p = os.path.join(REFS, rf)
        if not os.path.exists(p):
            continue
        with open(p, "r", encoding="utf-8") as f:
            c = f.read()
        rr = set(re.findall(r"`?(scripts/[\w\-.]+\.py)`?", c))
        miss = [x for x in rr if not os.path.exists(os.path.join(ROOT, x))]
        if rr:
            record(f"{rf} 引用脚本有效",
                   not miss, f"缺失 {miss}" if miss else f"共 {len(rr)} 处")


def main() -> int:
    print("=" * 62)
    print("        cn-ecommerce-ops 全量验收测试")
    print("=" * 62)
    print(f"Python: {sys.version.split()[0]}")
    print(f"根目录: {ROOT}")

    layer1()
    layer2()
    layer3()

    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    failed = total - passed

    print("\n" + "=" * 62)
    print(f"  合计 {total} 项 | 通过 {passed} | 失败 {failed}")
    if failed:
        print("\n失败项：")
        for name, ok, msg in results:
            if not ok:
                print(f"  - {name} {msg}")
    else:
        print("  全部通过，技能可正常使用。")
    print("=" * 62)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
