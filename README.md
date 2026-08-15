# 国内电商全链路运营 Skill（cn-ecommerce-ops）

![使用演示](assets/demo.gif)

一个面向 AI Agent 的**国内电商运营专家技能包**，覆盖淘宝、天猫、京东、
拼多多、抖音电商、小红书、视频号六大平台。

核心主张只有一句：**先算账，再做事。**

多数电商决策失误来自三件事——不算真实利润（漏算退货与推广成本）、
不算保本 ROI（盲目投放）、不查合规（广告法罚则起点二十万元）。
本技能为这三件事各提供了一个可执行、可验证的确定性工具。

![tests](https://img.shields.io/badge/tests-38%20passed-brightgreen)
![python](https://img.shields.io/badge/python-3.9%2B-blue)
![deps](https://img.shields.io/badge/dependencies-none-lightgrey)
![license](https://img.shields.io/badge/license-MIT-green)
![stars](https://img.shields.io/github/stars/g305595965/cn-ecommerce-ops?style=social)
![forks](https://img.shields.io/github/forks/g305595965/cn-ecommerce-ops?style=social)
![issues](https://img.shields.io/github/issues/g305595965/cn-ecommerce-ops)

---

## 为什么需要它

大模型对电商的了解通常停留在"多做内容、优化主图、提升转化率"这类
正确但无用的建议。真正的运营决策需要的是**数字**：

- 这个价格到底赚不赚钱？退货率 30% 之后还剩多少？
- 投放 ROI 做到多少才不亏？最高能出多少钱一个点击？
- 有流量不出单，问题到底出在哪一环？
- 这句文案会不会让我被罚二十万？

本技能把这些问题变成可以直接算出答案的命令。

---

## 五个可执行工具 + 实时数据桥接

全部使用 Python 3 标准库实现，**零第三方依赖**，每个脚本都内置自检。

| 脚本 | 作用 | 关键输出 |
|------|------|---------|
| `scripts/pricing.py` | 定价与利润测算 | 单均净利、**保本售价**、**保本 ROI**、成本结构 |
| `scripts/ad_calc.py` | 付费投放测算 | UV 价值、**可承受最高 CPC**、目标 ROI 反推 |
| `scripts/diagnose.py` | 转化漏斗诊断 | 瓶颈环节定位、优先级处方、提升模拟 |
| `scripts/product_score.py` | 选品六维评分 | 综合得分、短板识别与改进方向 |
| `scripts/compliance.py` | 广告法合规检查 | 175 条违禁词库，三级风险分级与整改建议 |
| `scripts/live.py` | **实时数据桥接** | 拉取当前真实费率/进货价/搜索量，一键灌入上述计算器 |

> `scripts/platform_fees.py` 是共享数据模块（六大平台佣金率、支付费率、
> 行业转化基准），被 pricing / diagnose / product_score 共同引用，
> 可用 `python scripts/platform_fees.py` 直接查看，数值均可用各脚本参数覆盖。

### 让工具"实时可用"：live.py

前五个工具再准，也依赖**真实入参**。与其凭记忆填佣金率、退货率、进货价、
搜索量，`live.py` 把"先拉实时数据、再灌入计算器"标准化：

```bash
# 看某平台该去哪拉实时数据（官方公示页 / 公开指数工具，无需 API key）
python scripts/live.py sources --platform douyin

# 看 live_data.json 该收集哪些字段、单位是什么
python scripts/live.py schema

# 把 WebSearch/WebFetch 拉到的实时值写入 live_data.json，生成执行命令
python scripts/live.py plan --in live_data.json
```

`plan` 会按"先 `pricing` 算毛利率 → 再 `product_score` / `ad_calc` 串联"的顺序
生成命令，并标注缺失字段；报告自动带上"数据截至 YYYY-MM-DD"水印。
`live.py fetch fx` 还能本机直连实时汇率接口（跨境成本换算用），网络受限时
优雅降级并提示改用 Agent 侧 WebFetch。

详见 SKILL.md 的「实时数据路由」与工作流 E。

### 亮点设计

**1. 定价用 100 单基准法，而不是简单减法**

退货产生的去程运费、包材、损耗都不可回收，这是"卖爆了却在亏钱"的
根本原因。脚本模拟发出 100 单、其中 r% 退货，分别核算收入与成本，
再折算回单均利润。

```bash
python scripts/pricing.py --cost 35 --price 129 --platform douyin \
    --shipping 4.5 --packaging 1.5 --return-rate 30 --ad-ratio 18
```

**2. 诊断看的是相对基准的偏离度，不是绝对值高低**

哪个环节相对行业基准差得最多，哪个才是真瓶颈，修复它的投入产出比最高。

```bash
python scripts/diagnose.py --impression 200000 --click 2000 \
    --order 110 --paid 55 --gmv 6600
```

```
  [!]  点击率         1.00%  基准 2.0~5.0%    偏低 偏离 50.0%
  [OK] 下单率         5.50%  基准 3.0~8.0%    正常
  [!]  支付率        50.00%  基准 60.0~85.0%  偏低 偏离 16.7%

--- 瓶颈定位 ---
  最大瓶颈: 曝光 -> 点击（点击率）
  可能归因: 主图/短视频首帧、标题、价格带、人群精准度
```

**3. 合规检查可接入自动化流程**

命中 P0（广告法明令禁止的绝对化用语）时进程返回码为 `1`，
可直接用于批处理或 CI 拦截。

```bash
python scripts/compliance.py --file detail.txt --min-level P0
```

---

## 四册知识库

| 文档 | 内容 |
|------|------|
| `references/platform-playbook.md` | 六大平台流量机制对比、淘宝坑产逻辑、拼多多价格力、抖音赛马与 GPM、小红书 CES、冷启动路径 |
| `references/product-selection.md` | 选品四道门槛、分品类退货率参考、四种产品角色矩阵、供应链评估与备货公式 |
| `references/listing-and-content.md` | 标题结构公式、主图五图法则、详情页九屏结构、短视频脚本框架、直播节奏与货盘 |
| `references/operations-playbook.md` | GMV 公式拆解、指标健康区间、日周月节奏、大促五阶段、风控红线速查 |

---

## 安装

### WorkBuddy

```bash
git clone https://github.com/g305595965/cn-ecommerce-ops.git ~/.workbuddy/skills/cn-ecommerce-ops
```

### Claude Code

```bash
git clone https://github.com/g305595965/cn-ecommerce-ops.git ~/.claude/skills/cn-ecommerce-ops
```

### 手动安装

下载仓库 ZIP，解压后将整个目录放入对应的 `skills/` 目录，
确保目录内直接包含 `SKILL.md`。

安装后重启客户端，向 AI 提问"帮我算一下这个品能不能做"即可自动触发。

---

## 直接当命令行工具用

不依赖任何 AI 客户端，脚本本身就是完整的命令行工具：

```bash
cd scripts

# 查看内置平台费率参考表
python pricing.py --list-platforms

# 算保本 ROI 和最高出价
python ad_calc.py --price 129 --gross-margin 60 --cvr 2.5 --cpc 1.2 --target-roi 4

# 选品评分
python product_score.py --gross-margin 62 --search-index 8000 --trend up \
    --supply-ratio 3.2 --return-rate 18 --weight 0.4 --moq 100 --restock-days 10

# 导出完整违禁词库
python compliance.py --list-rules
```

所有脚本均支持 `--json` 输出结构化结果，方便二次开发与集成。

---

## 测试

```bash
python tests/run_all.py
```

三层验证，共 34 项：

- **L1 单元层** —— 逐个运行各脚本内置自检（含公式自洽、单调性、异常拦截）
- **L2 集成层** —— 验证工具链数据自洽，例如 `pricing.py` 与 `ad_calc.py`
  两个独立脚本算出的保本 ROI 必须一致、保本售价代回后净利必须归零
- **L3 结构层** —— 校验 SKILL.md 元数据、文件完整性，
  以及文档中引用的每一个脚本路径是否真实存在（防止文档说谎）

---

## 数据来源与免责声明

- 内置的平台费率、行业转化基准、分品类退货率均为**公开信息与行业经验值**，
  文中已逐项标注。平台规则持续变化，实际决策**必须以各平台商家后台
  最新公示为准**。
- 合规检查基于《广告法》（2021 修正）第九条等条款及常见执法口径整理，
  结果为**风险自查提示，不构成法律意见**，具体认定以市场监管部门为准。
- 部分词汇在特定语境下可合规（如已取得对应批准文号），需结合实际判断。

---

## 贡献

欢迎提 Issue 或 PR，尤其欢迎以下方向：

- 补充或修正平台费率与规则（请附官方来源链接）
- 扩充违禁词库与整改建议
- 补充分品类的转化率与退货率基准数据
- 修正计算模型中的口径问题

提交 PR 前请运行 `python tests/run_all.py` 确保全部通过。

---

## License

[MIT](LICENSE)
