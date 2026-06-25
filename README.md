# 竞彩 +EV 分析器

一个用于分析中国竞彩正期望值（+EV）机会的本地工具。

项目核心思路是：在竞彩赔率进入临场冻结或低频更新阶段后，对比国际市场实时赔率，用去抽水后的公允概率判断竞彩侧是否存在被低估的选项。

## 这个项目做什么

- 获取并保存竞彩与国际赔率数据
- 将不同来源的赛事、玩法和赔率标准化
- 计算单项 EV，筛选正期望值选项
- 生成跨场 2 串 1 候选组合
- 输出可复核的 JSON 和 Markdown 分析报告

第一版重点是辅助分析，不做自动下注。

## 核心理念

### 赔率冰冻期

竞彩在临场前可能出现赔率停止变化或更新变慢的窗口，而国际市场仍会根据首发、伤病、资金流等信息继续调整赔率。

如果国际市场已经重新定价，而竞彩赔率还停留在旧估值，就可能出现数学上的正期望值机会。

### 用公允概率判断价值

项目不会只看“哪个赔率更高”，而是先对国际赔率去抽水，估算更接近真实市场判断的公允概率，再与竞彩赔率计算 EV。

简单说：

```text
EV = 公允概率 × 竞彩赔率 - 1
```

只有 EV 大于 0 的选项，才会被视为候选。

### 不为凑单牺牲 EV

很多竞彩场景需要 2 串 1。串关会放大收益，也会放大负期望。

本项目的原则是：只组合不同比赛中的正 EV 选项。若只有一个正 EV 选项，宁可空仓，也不为了凑 2 串 1 加入负 EV 比赛。

## 支持范围

第一版优先支持：

- 胜平负
- 让球胜平负
- 总进球数

数据来源优先考虑：

- 中国竞彩网官方页面
- Pinnacle

## 安装

本项目分为两层安装：Python CLI 负责标准化和计算；Codex skill 负责告诉 agent 如何按本项目规则采集、换算和生成报告。`pip install` 只会安装 Python CLI，不会自动安装 skill。

### 1. 安装 Python CLI

从 GitHub 安装：

```powershell
python -m pip install git+https://github.com/<your-github-user>/sporttery-ev-analyzer.git
```

安装后可使用模块命令运行：

```powershell
python -m sporttery_ev_analyzer.cli --help
```

也可以在克隆仓库后本地安装：

```powershell
git clone https://github.com/<your-github-user>/sporttery-ev-analyzer.git
cd sporttery-ev-analyzer
python -m pip install -e .
```

### 2. 安装 Codex skill

将仓库里的 `skills/sporttery-ev` 目录复制到本机 Codex skills 目录。Windows 示例：

```powershell
Copy-Item -Recurse .\skills\sporttery-ev "$env:USERPROFILE\.codex\skills\"
```

macOS / Linux 示例：

```bash
mkdir -p ~/.codex/skills
cp -R skills/sporttery-ev ~/.codex/skills/
```

安装后，在新的 agent 会话中要求使用 `sporttery-ev` skill。agent 应先读取 `SKILL.md`，再按其中规定使用有头浏览器访问固定 Sporttery 与 Pinnacle 入口，保存 raw JSON，然后调用 CLI 生成报告。

## 快速开始

本项目第一版采用本地 CLI：官方竞彩 raw JSON 与 Pinnacle raw JSON 进来，标准化 JSON、分析 JSON 和 Markdown 报告出去。

```powershell
python -m sporttery_ev_analyzer.cli normalize `
  --sporttery-raw data/raw/YYYY-MM-DD_HHMMSS_sporttery.json `
  --market-raw data/raw/YYYY-MM-DD_HHMMSS_pinnacle.json `
  --output data/normalized/YYYY-MM-DD_HHMMSS_matches.json

python -m sporttery_ev_analyzer.cli analyze `
  --normalized data/normalized/YYYY-MM-DD_HHMMSS_matches.json `
  --json-output data/analysis/YYYY-MM-DD_HHMMSS_ev_report.json `
  --md-output data/analysis/YYYY-MM-DD_HHMMSS_ev_report.md
```

如果没有安装为包运行，可先在仓库根目录设置：

```powershell
$env:PYTHONPATH = "src"
```

## 数据格式

原始快照至少包含：

- `source`：数据来源，例如 `sporttery`、`pinnacle`、`manual`
- `url`：官方竞彩或 Pinnacle 页面地址
- `fetched_at`：抓取或录入时间
- `raw_payload.matches`：赛事列表，每场包含球队、开赛时间、玩法和赔率
- 可选 `odds_history`：赔率历史行；标准化时自动使用发布时间最新的一行

标准化结果会保留输入来源、匹配结果和无法匹配项。分析报告会显式写入数据时间差、报告生成时间、正 EV 单项、2 串 1 候选、跳过项和风险提示。

标准化时默认会加载 `config/world_cup_2026_team_aliases.json`，只用于 2026 年世界杯国家队/地区队别名匹配。若需要自定义国家队别名，可在 `normalize` 命令中传入 `--team-aliases path/to/aliases.json`。俱乐部队名别名不在第一版范围内。

正式 EV 计算只接受官方竞彩与 Pinnacle 快照：竞彩源必须是 `sporttery` 或 `sporttery_browser`，国际赔率源必须是 `pinnacle` 或 `pinnacle_browser`。第三方转引页、预测市场或其他数据源只能人工参考，不能进入计算。

Pinnacle 亚洲让球盘不能直接对比竞彩让球胜平负；Pinnacle 大小球盘也不能直接对比竞彩总进球数。只有数学定义完全一致的三项让球盘或精确/分档总进球数市场才会进入 EV 计算。

## 设计原则

- **可复核**：保留原始数据、时间戳、来源和分析结果
- **可重复**：核心计算由确定性代码完成，不依赖临场主观判断
- **低频稳健**：优先使用低频、真实浏览器或授权 API 获取数据
- **人工决策**：工具只生成分析结果，不替用户做投注决定
- **风险优先**：数据过期、赛事匹配失败或页面异常时，不输出误导性结论

## 不做什么

- 不自动下注
- 不提交订单
- 不联系彩店
- 不绕过验证码、登录、地域或访问限制
- 不做高频抓取
- 不在数据不完整时给出确定性建议

## 风险说明

赔率数据高度依赖时间，分析结果只代表当次数据快照下的数学判断。

本项目不是投注技巧保证，也不是收益承诺。任何实际投注行为都应由用户基于最新数据、销售状态和个人风险承受能力自行决定。
