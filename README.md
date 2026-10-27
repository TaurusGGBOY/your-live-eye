<div align="center">

<img src="src/your_live_eye/web/favicon.svg" width="96" height="96" alt="YourLiveEye 标志">

# 你的眼 · YourLiveEye

**给 Agent 一个直播间，让每一种声音都有迹可循。**

[![Tests](https://github.com/TaurusGGBOY/your-live-eye/actions/workflows/tests.yml/badge.svg)](https://github.com/TaurusGGBOY/your-live-eye/actions/workflows/tests.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

[明前奶绿 Demo](https://your-live-eye-demo.pages.dev/) · [火之眼原站](https://best-hinome.pages.dev/) · [部署文档](docs/deployment.md) · [内置 Skill](.agents/skills/your-live-eye-setup/SKILL.md) · [反馈问题](https://github.com/TaurusGGBOY/your-live-eye/issues)

</div>

给 Agent 一个 B 站 UP 主的 **UID、昵称或链接**，从公开直播档案生成分类页面，并完成局域网或 Cloudflare 部署和每日更新。

“你的眼”替你观察直播间里的每一种声音；开源仓库与命令名为 `your-live-eye`，英文标识 YourLiveEye。本项目从 Hinome 抽取，运行不依赖原项目目录、私有数据库、服务器或主播素材。

## 在线体验

**明前奶绿 Demo**：2026-10-25 最近收录的完整场次，58,919 条 Message/SC，展示分类、五分钟下钻及争吵措辞强度。Demo 只保留一天；正式初始化默认全部已结束历史。

**[打开明前奶绿 Demo ↗](https://your-live-eye-demo.pages.dev/)** · **[打开火之眼原站 ↗](https://best-hinome.pages.dev/)**

Demo 已部署到 Cloudflare Pages，无需安装即可查看。它是固定单日展示；源码中的每日更新能力需部署者在自己的账号配置后启用。

![明前奶绿 Demo：全天分类与争吵措辞强度](docs/images/mingqian-demo.jpg)

## 内置初始化 Skill

项目自带 [your-live-eye-setup](.agents/skills/your-live-eye-setup/SKILL.md)，随源码一起提供。Agent 先确认主播、正式全历史或轻量 Demo、模型、Cloudflare 配置、日更时间与时区，并在开始前给出有依据的耗时范围。已有选择直接复用，不要求用户另写 Skill。耗时较长时每 5 分钟报告完成量和更新预计剩余时间。

## 一句话交给 Agent

> 阅读 AGENTS.md 和内置初始化 Skill，确认我要分析的主播与部署配置，按正式全历史模式生成舆论分析页面，并设置每天北京时间 04:00 补齐更新。若缺少模型权限，说明需要我完成哪一步登录或模型选择。完成后给我可访问网址、实际覆盖场次和分类数量。

## 一键运行

需要 Python 3.11+、网络，以及一个可用模型。默认调用**已登录的 Codex CLI**，使用 `gpt-6-luna` / high / Fast。模型权限因账户不同；可用 `--model`、`--reasoning`、`--tier` 调整，不会偷偷换模型。首次需要用户自己完成 `codex login`。

先拉取项目：

```bash
git clone https://github.com/TaurusGGBOY/your-live-eye.git
cd your-live-eye
```

在项目目录执行：

```bash
./run.sh run "明前奶绿" --deploy --schedule
```

Windows PowerShell：

```powershell
.\run.ps1 run "明前奶绿" --deploy --schedule
```

入口自动建立独立 Python 环境并安装依赖，随后执行：身份解析 → 全部已结束历史直播 → 原始归档 → 直播边界过滤 → 括号规则 → 去重文本批量分类 → 独立强度评分 → 玩梗语义初审与独立复核 → 数据对账 → 静态页面 → 常驻服务 → 每日定时任务。首次下载依赖和模型运行需要时间；进度输出为 JSON，Agent 可直接读取。

首次正式运行默认 `--date all`，覆盖来源目录中**全部已结束的历史直播**。轻量示例需要明确选择：

```bash
./run.sh run "明前奶绿" --demo --deploy
```

`--demo` 只初始化最近已结束场次；上面的在线 Demo 固定保留一天。

同样支持：

```bash
./run.sh resolve "https://live.bilibili.com/25034104/"
./run.sh run 2132180406 --deploy --schedule
./run.sh run "https://space.bilibili.com/2132180406" --deploy --schedule
./run.sh run "明前奶绿" --date 2026-10-26 --fallback-latest --deploy --schedule
```

昵称必须唯一精确匹配来源。指定日期没有档案时，默认报出缺口；只有 `--fallback-latest` 才改用最近场次，并保存原因。不同主播使用不同 `STATE/<UID>/`；第二个同时部署的页面请用另一个 `--port`。

## 大概要等多久？

**约 6 万条的单日 Demo 先预留 30–60 分钟。** 火之眼最近一次约 267 万条存量重跑，主分类实测 **3 小时 22 分**；53,079 种争吵原文的纯强度评分实测 **15 分 57 秒**。两段处理用时合计约 **3 小时 38 分**，不是连续的首次初始化墙钟，也不含下载、玩梗审核与部署。

### 每个阶段大致多久

| 阶段 | 单日 Demo，约 6 万条 | 267 万条历史参考 |
| --- | --- | --- |
| 安装环境、解析主播 | 2–10 分钟 | 2–10 分钟，一次性工作 |
| 下载、解码与整理 | 1–3 分钟 | 暂预留 15–60 分钟；首次全历史下载未实测 |
| 主分类 | 旧 Demo 分类加语境复核实测约 13 分钟，作为参考 | 6 并发实测 **3 小时 22 分 14 秒**；默认 2 并发按吞吐换算约 **10 小时**，未实跑 |
| 独立强度评分 | 少量候选约 1–3 分钟预算 | 53,079 种实测 **15 分 57 秒**；后续 2,048 条/批、2 并发对 16,184 种实测 **7 分 14 秒**，同规模约 24 分钟仅为线性估算 |
| 玩梗语义初审与独立复核 | 本次 Demo 实测 **12 分 40 秒**（61窗口、22分片、3并发，含格式修复与接续） | 火之眼 21,115 条原文、20 分片及45批二审实测 **12 分 17 秒**；全历史尚无完整实测，必须首批测量后单列 ETA |
| 生成页面、部署与回读 | 1–5 分钟 | 5–20 分钟预算，不含账号授权等待 |

**已备好档案时，分类加评分可按 6 并发约 4 小时、默认 2 并发约 10–11 小时安排；不能把它称为包含全历史玩梗审核的总初始化时间。** 之前“评分还需 1–12 小时”的估算对应已弃用的二次分类流程，现已删除。首次完整初始化还要加下载、玩梗审核和部署；新主播先测若干真实窗口，再给总预算，避免把一个日样本乘直播天数冒充实测。

明前奶绿旧单日 Demo 为 58,919 条事件、23,693 种原文，Luna high / Fast、3 并发；分类和旧语境复核约 13 分钟，首版补分约 1 分钟。火之眼主分类是已有档案、Luna high / Fast、6 并发；17 种/18 次执行缺失与49,640次模型未决分别保留，不能称为100%有效完成。玩梗参考使用不同模型与分片，不代表当前默认模型的速度。详见[耗时依据与估算口径](docs/runtime-estimates.md)。

无新增或变化内容时复用结果，通常先按 **1–3 分钟**检查预算；新增相近规模的一场先按 **20–50 分钟**安排，取决于实际新原文与玩梗审核量。同一配置中断后用 `resume`；缓存恢复曾约10秒，这不能宣传为首次运行速度。

内置 Skill 会先核对消息量、去重原文数和模型参数，按真实已完成量每5分钟修订 ETA。GitHub 托管任务每次约4.5小时保存进度；每日只运行一次时，日历等待长于实际处理时间，可手动继续 `update`。

本次同步的范围与验收见[火之眼更新同步记录](docs/upstream-sync-20261027.md)。

## 页面与分类

- 直播内 Message/SC 全部计数，五分钟分类柱、日历、日期导航、近月/年/十年分布与下钻。
- 同文只做一次模型判断，出现多少次就统计多少次；不会把重复弹幕的事件次数丢掉。
- `【` 或 `】` 字面格式直接归翻译；其余批量调用模型。八类包括翻译、招呼、支持、玩梗、闲聊、争吵、待判断、关心。
- 类别5统一命名为“争吵”，沿用指责、贬损等范围，不要求双方来回争执，也不代表认定作者有恶意。新数据一次分类后独立评分；升级保留旧数据，不重新判断。
- 争吵原文补充1–100分措辞强度，低于50分淡化但仍保留原类别。分数不是恶意概率或分类置信度；缺分重试，不拿0伪装成功。
- 每个五分钟按强度展示最多十条争吵摘录。玩梗从全部可读窗口发现，以SC或同传为证据，独立复核后按实际接话次数排序：全天全部展示并按发生时间排序、时段Top1。新增、补录或正文变化会更新；重复输入复用，失败保留上次页面。旧日未审核时明确显示“高频互动”，不冒充语义精选。
- 图片和缺失 SC 正文不伪装成已读懂，保留待判断。语义准确率没有用这次 Demo 建立人工真值评测，不能把工程通过理解成分类百分之百正确。

玩梗卡片可展开原文依据；SC、同传和观众接话保留各自的来源，不能据此确认主播音视频内容：

![明前奶绿 Demo：展开玩梗语境与原文依据](docs/images/mingqian-evidence.jpg)

“任意 UP 主”指身份输入不写死；**有可访问公开档案**才有历史弹幕可分析。本项目不会补造未收录直播，也不是实时采集器。默认来源是 [Danmakus](https://danmakus.com/)。遇到同名、无档案、权限/限流或模型不可用时给出明确失败原因。

点击五分钟柱，右侧同步切到相应时段，原文与分数一起显示：

![明前奶绿 Demo：选中五分钟时段](docs/images/mingqian-period.jpg)

手机也可以查看：

<img src="docs/images/mingqian-mobile.jpg" alt="明前奶绿 Demo 手机视图" width="320">

## 数据目录

默认状态目录与源码分离：macOS 为 `~/Library/Application Support/YourLiveEye/`，Linux 为 `~/.local/share/your_live_eye/`，Windows 为 `%LOCALAPPDATA%/YourLiveEye/`。可用 `--state` 或 `YOUR_LIVE_EYE_STATE` 改动。每个 UID 独立；首次输出会给出准确配置路径。macOS 后台服务另装独立 runtime，避免依赖外置盘源码路径。

## 恢复与日常管理

```bash
# 将 CONFIG 设为首次运行输出的路径；下面为 macOS Demo 示例。
CONFIG="$HOME/Library/Application Support/YourLiveEye/2132180406/config.json"
./run.sh status --config "$CONFIG"
./run.sh resume --config "$CONFIG"
# 仅在看过失败原因并修复后，给失败批次增加一次明确重试机会：
./run.sh resume --config "$CONFIG" --retry-failed
./run.sh rebuild --config "$CONFIG"
./run.sh verify --config "$CONFIG"
./run.sh schedule --config "$CONFIG" --print-only
./run.sh unschedule --config "$CONFIG"
./run.sh stop --config "$CONFIG"
```

模型成功项立即入库，漏 ID 只补缺项。中断后继续已有队列；失败不会推进成功检查点。本次版本升级保留旧分类、分数和原始回执；未完成旧初判按冻结提示恢复，新原文用新提示，旧二次分类停止。主动全量重判才需要另行规划，不能为升级另建目录重复付费。

定时器以北京时间 04:00 为每日界线，每 15 分钟唤醒检查：当天已成功则不再调用来源/模型；正式全历史配置每天重新核对整个目录，补齐遗漏、失败、此前未结束及迟到的旧场次；已完成消息复用分类，并复查最近三天档案。每个日更周期最多自动尝试一次，失败保留成功进度，下一天补跑；需要马上重试可手动 resume。macOS 使用 launchd，Linux 使用用户级 systemd，Windows 使用任务计划；需要主机和网络可用。可用 `--update-at HH:MM --timezone Asia/Shanghai` 设置其他时间；本机每 15 分钟检查，实际启动可能晚于设定时间至多一个检查周期。详情见 [部署](docs/deployment.md)。

## Cloudflare 发布 Action

自带 [.github/workflows/cloudflare.yml](.github/workflows/cloudflare.yml)，**默认使用 GitHub 托管的 `ubuntu-latest`，不需要自备服务器或安装 runner**。公开仓库的标准 runner 可免费使用，私有仓库按账户额度计算；模型 API 和状态存储按各自服务计费，见 [GitHub 官方说明](https://docs.github.com/en/actions/concepts/billing-and-usage)。

手动 `update` 首次初始化或补齐，`publish` 发布已完成的数据；开启日更后每天北京时间 04:00 补齐并发布。GitHub 每次分配新机器，项目用**私有 Cloudflare R2** 保存数据库、队列和已完成结果，下一次恢复后只处理缺项。约每 15 分钟在批次边界保存，运行到约 4.5 小时主动保留进度退出，下次继续；完整数据准备好后更新页面。

Agent 按 [Cloudflare 配置步骤](docs/deployment.md#cloudflare-pages-action) 填好主播 UID、可用 API 模型、Pages 项目、私有状态桶和 Secrets。已有常驻主机的用户可选择 `YOUR_LIVE_EYE_RUNNER=self-hosted`，继续使用本机 Codex 登录及持久目录；这是可选方式。源码包含完整 Action，但下载代码不会自动开启云账号、收费服务或日更。

## 导出与公开托管

```bash
./run.sh export --config "$CONFIG" --output dist/mingqian
```

导出目录只有页面和匿名展示数据，可交给 Nginx、Caddy 或 Cloudflare Pages。原始归档、观众身份、模型请求回执、配置和数据库留在独立 STATE 目录，不进入静态站。查看 [部署方式与命令](docs/deployment.md)。公网账户登录与发布单独执行；本项目不会使用原 Hinome 的域名、IP、SSH 密钥或云账号。

## 来自「火之眼」

本项目抽取自 **[火之眼（火の眼 · Hinome）](https://best-hinome.pages.dev/)**，原站面向火羽ひのめ直播间，保留其专属背景、梗解释及人工口径；「你的眼」提供独立的主播解析、分类流程、日更和部署，不依赖原站数据库，也不会直接沿用火羽专属判断。

![火之眼公网页面：火羽ひのめ直播间分析](docs/images/hinome-public.jpg)

截图为 2026-10-27 实际浏览器页面；明前奶绿与火之眼截图均来自各自的公网实际页面。画面中的历史数据和模型结论不表示已完成独立人工准确率评测。截图来源及版本见 [截图说明](docs/images/README.md)。

## 开发与证据

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m unittest discover -s tests -v
```

[隐私检查](docs/privacy-review-20261027.md) · [GitHub runner 与 Demo 发布记录](docs/cloudflare-demo-20261027.md) · [v0.2 初始化与 Skill](docs/initialization-cloudflare-20261027.md) · [架构及抽取范围](docs/architecture.md) · [真实 Demo 验收](docs/demo-20261027.md) · [来源与授权](NOTICE.md) · [MIT License](LICENSE)

本仓库只包含可独立安装的源码、合成测试和文档。不要将 `.state`、真实弹幕全档或账号凭据提交到开源仓库。
