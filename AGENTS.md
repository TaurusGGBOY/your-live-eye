# Agent 快速入口

先读 README.md。首次初始化、换主播、调整部署或日更时，读取项目自带 [.agents/skills/your-live-eye-setup/SKILL.md](.agents/skills/your-live-eye-setup/SKILL.md)，按已有选择补齐缺项，并在大批运行前给耗时范围；耗时较长时每 5 分钟更新进度与剩余时间。目标是给指定 UP 主搭建可核对的直播间分析页面。

1. 用户只给 UID、昵称或链接时，先按内置 Skill 补齐模式与部署选择；确认正式初始化后默认全部已结束历史直播（`--date all`），只有明确选择轻量 Demo 才用 `--demo`。正式入口为 `./run.sh run "输入" --deploy --schedule`。先通过 `resolve` 排除同名歧义；没有公开档案时说明缺口，不能编造数据或换成别的主播。
2. 本机优先已登录的 Codex CLI，默认 Luna high / Fast；Cloudflare Action 默认 GitHub 托管 runner，使用用户选定的兼容 API 和私有 R2 状态桶，不要求自托管。自托管是已有主机用户的可选方式。不要读取登录文件、cookie、密钥内容；不要把凭据写入配置或日志。没有可用模型时不能把全部“待判断”页面叫完成。
3. 一个 UID 一个独立 `STATE/<uid>/`。中断后 `resume --config ...`，不要重新开目录逃避失败或重复付费。进度看 `status` 与 `STATE/<uid>/progress.json`，模型未决和执行失败分别报告。
4. 数据只计来源直播区间内的 Message/SC，按 Asia/Shanghai 分日；相同原文只判断一次，事件次数不能去重。图片/缺失正文不假装读懂。模型类别 5 先是宽候选，只有对象/语境复核后的攻击进入图表与摘录。不得把观众转述当主播音视频证据。
5. 初次部署与每日补齐用同一流水线。来源成功、分类完成、静态数据对账和页面回读成功后才推进成功检查点。沿用已有锁、队列与文件原子替换；无法说明具体事故和现有机制为何不够，不新增哈希或门禁。
6. 改页面时更新 `src/your_live_eye/releases.json`，重建并使用实际局域网 URL 打开。核对主播、日期、总数、五分钟点击和普通刷新；可访问 Windows 时也检查。HTTP 200 不能代替界面验收。
7. 不提交 `.state`、原始档案、模型回执、私有配置、日志、头像或第三方素材。`export` 仅导出生成静态站。公开发布/推送仓库按用户授权，不把本地部署当已公开上线。
8. 临时文件在 `/tmp/codextmp`，保留用户其他项目和服务；Windows 优先 Windows MCP。测试 `python -m unittest discover -s tests -v`。

架构及已知边界见 docs/architecture.md；部署与定时任务见 docs/deployment.md；真实 Demo 的验收记录见 docs/demo-20261027.md。
