# 部署与定时任务

本文中的 `$CONFIG` 指首次运行输出的绝对配置路径。macOS Demo 可设为 `CONFIG="$HOME/Library/Application Support/YourLiveEye/2132180406/config.json"`。

## 本机与局域网

`./run.sh run "主播" --deploy --schedule` 默认监听 `0.0.0.0:18770`。实际 LAN 地址保存在 `STATE/<UID>/access.json`。多个主播同时部署需分配不同端口。所有身份、目录和进度按 UID 隔离。

macOS 常驻页面使用 `~/Library/LaunchAgents/org.yourliveeye.<UID>.web-<PORT>.plist`，日更使用 `org.yourliveeye.<UID>.daily-<PORT>.plist`；均是当前用户级任务，登录后运行。macOS 的运行环境安装在 `~/Library/Application Support/YourLiveEye/runtime/`；源码可以在外置盘，后台任务不从外置盘启动。不会碰 `com.hinome.*`。Linux 使用 `~/.config/systemd/user/` 中同名服务/定时器；需要可用用户级 systemd，未登录也运行需由管理员配置 linger。Windows 使用当前用户任务计划；主机/防火墙需允许所选端口。源码含三平台安装器，本次真实验收平台见 Demo 报告。

日更默认每天 `04:00 Asia/Shanghai`，可用 `--update-at HH:MM --timezone IANA时区` 配置。本机任务每 15 分钟检查一次，当地设定时间前属于上一日更周期，实际启动可能晚至下一个检查点；主机离线则恢复后补齐。首次成功运行后不立即重复模型调用。每个周期最多一次自动尝试；失败保留已完成项、不推进成功日期，下一周期给失败批次一次额外机会，防止每 15 分钟无限重试费用。手动 `resume --retry-failed` 可立即重试。

正式配置默认 `date=all`，每天核对全部目录，补遗漏和迟到旧档；已完成且未变化来源跳过，最近三天或消息数变化的档案重读，成功分类不重跑。进行中的直播留到后续已结束时处理。显式 Demo/单日配置保持首次选择范围起的增量；不会因升级自动变成全历史。旧来源响应保留。需要更频繁跟进正在播的场次时，当前版本不提供实时采集。

服务端仅允许静态页面、汇总和按日 JSON 路由，不提供原始数据、配置、数据库或目录列表。普通刷新能读到新版本；导出的页面没有本地绝对路径。LAN 页面未设密码，仅在可信局域网使用。

## 模型接口

默认 Codex CLI 需预先登录。项目调用时使用临时无仓库目录、只读权限并禁用工具；仅传主播身份和消息文字，不传观众 UID。读取其标准输出中的用量，不读取登录文件。

可切换支持 Chat Completions + JSON schema 的 API：

```bash
# 凭据由用户在当前 shell/系统密钥服务设置；不写进项目文件。
export YOUR_LIVE_EYE_API_BASE=https://api.openai.com/v1
# 设置 YOUR_LIVE_EYE_API_KEY 或 OPENAI_API_KEY
./run.sh run 2132180406 --provider openai --model YOUR_AVAILABLE_MODEL --tier default --deploy
```

模型需要支持 `reasoning_effort` 和 JSON schema；接口不同会明确失败。API 适配器不声称所有厂商都兼容。`--tier` 目前仅对 Codex 生效；API 以服务端配置为准。没有用户提供的可用模型权限不能自动完成。

API 凭据不可写到 launchd/schtasks 的明文参数中，因此自动安装 API 日更前会说明需要由主机注入凭据。管理员可在其已有密钥管理环境调用：

```bash
your-live-eye scheduled --config /ABSOLUTE/STATE/UID/config.json
```

同样可用 cron 每 15 分钟调用 `scheduled`，时间/时区判定由配置处理，不依赖机器时区。默认 Codex 路线不需要这一步人员介入。

## 静态公网部署

先导出：

```bash
./run.sh export --config "$CONFIG" --output dist/mingqian
```

Nginx/Caddy 的站点根目录指向导出目录；不指向仓库或 `.state`。

Cloudflare Pages 的自动入口见下节；手动方式是在部署者自己的账号创建 Pages 项目后执行：

```bash
npx wrangler pages deploy dist/mingqian --project-name YOUR_PROJECT
```

这条命令是真正公网发布。请先确认页面内容与数据使用范围；不会自动继承原项目账户。每天若要同步公网，可在自己的调度中接续 `export` 到新的输出目录后再执行托管命令。默认日更自动更新局域网站；公网凭据和自动发布由部署者单独配置。

仓库附 `deploy/Dockerfile`（源码安装环境）和 `deploy/Caddyfile`（导出静态站的托管示例），容器使用只读静态目录即可展示，无需模型密钥。处理流水线需另挂独立状态目录并选可用模型。

## 恢复与清理

配置改变前先保留旧目录。`resume --retry-failed` 只用于处理工程失败，不为了修饰语义分数反复问同一条。暂停新模型任务可在对应状态目录创建 `stop-claim`，当前批次结束后停止；删除后恢复。

使用 `unschedule` 停止每日任务、`stop` 停止页面服务。两者只处理当前配置注册的任务。不要按端口或进程名批量杀服务。`releases/` 可保留多个版本；回滚时将 `current.json` 指到已验证旧目录，再执行 `verify`。


## Cloudflare Pages Action

仓库自带 [发布工作流](../.github/workflows/cloudflare.yml)，默认用 **GitHub 托管 `ubuntu-latest`**。公开仓库的标准 runner 免费使用，私有仓库按套餐额度；模型 API 与 R2 按各自服务计费。无需自备服务器，self-hosted 只是可选项。

### 1. 默认：GitHub 托管 runner

1. 在自己的 GitHub 仓库保留工作流，并允许 Actions。先运行 `./run.sh resolve "主播UID或昵称或链接"` 核对主播 UID。
2. 在 Cloudflare 创建 Pages Direct Upload 项目，生产分支默认 `main`。
3. 创建**私有 R2 桶**作为任务进度存储，关闭 `r2.dev` 公开访问，不绑定公开域名。创建仅该桶读写的 R2 S3 凭据，保存在 GitHub Secrets；项目不会把原始档案传给 Pages。
4. 选择有权限的模型 API，需兼容项目的 Chat Completions、`reasoning_effort` 和 JSON schema。Codex 登录权限不等于 API 权限，不能照抄本机模型名假设可用。
5. 填写下表，运行 Action 的 `update`。首次自动创建独立配置，正式范围默认全部历史；无需先在本机下载。

| 名称 | 类型 | 内容 |
| --- | --- | --- |
| `YOUR_LIVE_EYE_UID` | Variable | resolve 返回的数字 UP UID，不是直播间号 |
| `YOUR_LIVE_EYE_MODEL` | Variable | 该 API 实际可用的模型名 |
| `YOUR_LIVE_EYE_API_BASE` | Variable，可省 | 兼容接口地址，空值默认 OpenAI v1 |
| `YOUR_LIVE_EYE_API_KEY` | Secret | 可用模型 API 密钥 |
| `YOUR_LIVE_EYE_STATE_BUCKET` | Variable | Cloudflare 私有 R2 桶名 |
| `R2_ACCESS_KEY_ID` | Secret | 仅该桶的读写访问 ID |
| `R2_SECRET_ACCESS_KEY` | Secret | 对应 R2 密钥 |
| `YOUR_LIVE_EYE_SCOPE` | Variable，可省 | 首次默认 `all`；明确 Demo 时 `latest` 或 `YYYY-MM-DD` |
| `YOUR_LIVE_EYE_UPDATE_AT` | Variable，可省 | 首次默认 `04:00` |
| `YOUR_LIVE_EYE_TIMEZONE` | Variable，可省 | 首次默认 `Asia/Shanghai` |
| `CLOUDFLARE_PROJECT_NAME` | Variable | 自己创建的 Pages 项目名 |
| `CLOUDFLARE_PRODUCTION_BRANCH` | Variable，可省 | 生产分支，默认 `main` |
| `YOUR_LIVE_EYE_DAILY_ENABLED` | Variable | `true` 开启每日补齐并自动公开发布，其余值仅手动 |
| `CLOUDFLARE_ACCOUNT_ID` | Secret | Pages 和 R2 所属 Account ID |
| `CLOUDFLARE_API_TOKEN` | Secret | 该账号的 Cloudflare Pages Edit Token |

Token/密钥由用户在 Secrets 界面保存，不粘贴到聊天、不写进配置或仓库。公开 Pages 只收到静态页面、匿名摘录和汇总；原始档案、模型回执及 SQLite 位于私有 R2 的 `your-live-eye/<UID>/state.tar.gz`。没有使用公共 Actions cache/artifact 保存私有数据。

GitHub 每个任务都是新机器，因此流程先恢复 R2，再补齐，结束时保存一致的 SQLite 备份。约每 15 分钟在已完成来源/模型批次边界保存；约 4.5 小时到达下一个边界后停止并保存，留出完成在途请求和上传的时间。下次 `update` 或日更继续，不重复已成功判断。突然断电/被强制取消可能丢失最后一次保存后的进度；大历史档案的恢复、压缩、上传耗时和 runner 磁盘容量仍需计入估时。

恢复失败（例如权限或网络错误）会报错，不能把它当空数据重新付费跑全量。已有配置优先于首次初始化 Variables；调整时间或从 Demo 扩全历史时，应先保存旧配置，再下载私有状态、修改对应 config、上传回原对象；不要仅改 Variable 就声称旧配置已改变。本次代码升级保留旧分类与分数，未来新数据使用新版提示，不需要新状态桶；主动全量重判须另行规划。

玩梗审核与分类使用同一API服务及模型，R2同时保存私有 `memes/` 输入、回执和分片状态。首次本机配置可用 `--meme-model` / `--meme-reasoning` 显式选择单独的语义模型；已有配置可设置 `meme_model: {"model":"可用模型","reasoning":"low"}`。已开始的审核使用冻结参数，新来源才采用新设置，不能静默更换或重复运行已完成审核。

### 2. 可选：已有 self-hosted 主机

已有常驻 Mac/Linux 主机时，设置 `YOUR_LIVE_EYE_RUNNER=self-hosted`，注册带 `your-live-eye` 标签的 runner；同一用户需能调用已登录 Codex CLI，或由 Secrets 提供 API 密钥。先生成配置：

```bash
./run.sh run "主播UID或昵称" --date all --configure-only
```

设置 Variable `YOUR_LIVE_EYE_CONFIG` 为 checkout 外持久目录中 `config.json` 的绝对路径。此模式不使用 R2，亦不需要 UID/MODEL/STATE_BUCKET/R2 Secrets；Pages 项目和 Cloudflare Secrets 仍需填写。项目不复制登录文件，配置不包含密钥。已有单日 Demo 保持单日，不因升级自动扩成全历史。

### 3. 执行与每天 4 点

Actions → **Cloudflare Pages** → Run workflow：

- `update`：首次处理全部可用历史，或继续未完成内容；成功后导出并发布。初次请选择这一项。
- `publish`：不下载、不调用模型，用已成功的数据及当前前端导出并发布。上传失败后用它重试，无需重新分类。
- 日更：开启 `YOUR_LIVE_EYE_DAILY_ENABLED=true`，默认 cron `0 20 * * *`（UTC），即北京时间次日 **04:00**。先补未完成 Message/SC、新场次与迟到旧档，再发布；失败保留上次线上页面及已保存进度。

更改日更时间需同时修改 config 的 `update_at/timezone` 和工作流 cron；内置 Skill 会读回核对。首次尚无云端 config 时可设置上表时间 Variables。用 Action 负责日更后，不为同一数据集再安装本机 daily，LAN web 服务可独立保留；`unschedule --config ...` 只移除对应本机日更。

GitHub 定时任务可能延迟，默认分支需含工作流；公开仓库长时间无活动可能被停用，不能承诺精确到秒。工作流没有 push/PR 自动发布。较长的首次全历史可多次手动 `update` 接续，也可等次日日更；在完整初始化通过前不发布一个假装完整的部分页面。Agent 陪同运行时按内置 Skill 每 5 分钟汇报，并区分模型有效处理时间、等待下次运行时间与总工期。

发布后打开返回网址核对主播、日期、总数、分数与五分钟下钻。源码、本地模拟测试和手动 Pages 发布不能当成 GitHub hosted + R2 已在云上全链路实跑；实际验证范围以交付记录为准。

依据（2026-10-27 核对）：[GitHub runner 费用](https://docs.github.com/en/actions/concepts/billing-and-usage)；[GitHub hosted runner](https://docs.github.com/en/actions/concepts/runners/github-hosted-runners)；[GitHub schedule](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)；[Cloudflare Direct Upload CI](https://developers.cloudflare.com/pages/how-to/use-direct-upload-with-continuous-integration/)；[R2 S3 API](https://developers.cloudflare.com/r2/api/s3/api/)。
