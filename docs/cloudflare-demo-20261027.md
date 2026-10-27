# Cloudflare Demo 与开源发布

记录日期：2026-10-27，Asia/Shanghai。软件包 v0.3.1，页面 v0.1.3。

## 访问入口

- [你的眼 · YourLiveEye 源码](https://github.com/TaurusGGBOY/your-live-eye)
- [明前奶绿 Demo](https://your-live-eye-demo.pages.dev/)
- [火之眼 / 火の眼原站](https://best-hinome.pages.dev/)

Demo 保留 2026-10-25 一场直播，58,919 条 Message/SC；全历史是正式初始化的默认能力，不代表该示例已经补齐全部历史。此次开源整理复用完成的结果，不追加模型调用。

## 自动部署

Action 默认 GitHub 托管 ubuntu-latest，自托管仅为可选方式。托管运行器使用私有 R2 恢复数据库、原始档案、队列和回执；约 15 分钟在批次边界保存，约 4.5 小时保留进度退出，下次继续。成功完成后导出静态页面，再由 Wrangler 发布到 Pages。每日默认北京时间 04:00。

源码仓库没有账号密钥，也没有启用公开 Demo 的云端日更。使用者需按 [部署说明](deployment.md) 配置自己的模型、私有状态桶与 Pages Secrets。R2 的恢复与保存通过模拟对象存储测试；尚未宣称完成真实 GitHub + R2 的全历史运行。

## 已有验证

v0.3.0 源码和独立安装 wheel 各 19 项测试通过，覆盖全历史补齐、失败恢复、同文计数、日更检查点、R2 恢复、WAL 一致备份及状态保存；Actionlint 和内置 Skill 校验通过。

Mac Chrome 与 Windows Edge 均实际打开过公网 Demo。页面显示 58,919 事件、61 根五分钟柱、173 个强度徽章，42 条低分摘录淡化。首柱切换为 18:56–19:01，右侧同步 3 条原文与 90/62/62 分。Windows 另验证日历、日志、普通刷新及 390px 无横向溢出。截图见 [images](images/README.md)。这属于工程与浏览器验收，不是人工语义准确率证明。

v0.1.3 新增页脚与“关于”中的 GitHub 入口。公开发布前检查源码、Git 历史、提交身份、图片元数据和静态页面；范围与结果见 [隐私检查](privacy-review-20261027.md)。本机网络、操作系统用户名、凭据、数据库、模型回执和部署操作日志不进入开源仓库。

## 开源交付验证

仓库已设为 Public。初始 Windows CI 暴露默认编码读取中文失败，已将文本文件统一显式 UTF-8、命令行输出改为可跨编码读取的 JSON，并补回归。最新代码在 GitHub 的 Windows、macOS、Linux 上各 20 项测试通过；从干净 Git 副本使用可执行 run.sh 启动、构建 wheel 和运行 20 项测试亦通过。部署工作流和内置 Skill 校验通过。

Demo 页面 v0.1.3、火之眼页面 v2026.10.27.3 均在页脚及关于信息链接到本仓库，局域网和公网均已通过实际浏览器核对。火之眼另外完成同一套 17 项桌面检查、手机布局、发布前后检查及 HTML/CSS/JS/图标逐字节回读。真实数据范围保持原样，未借此发布仍在执行的重分类候选。

最终公网版本：[Demo c13ca5b5](https://c13ca5b5.your-live-eye-demo.pages.dev/)；[火之眼 d35d14f2](https://d35d14f2.best-hinome.pages.dev/)。火之眼的 GitHub 发布首次因旧测试未同步版本日志渲染而失败，补齐后再次运行卡在浏览器依赖安装；取消该次任务后，在既有 Windows 浏览器执行同一检查，再通过官方 Wrangler 发布并回读，不将取消的云端任务记录为成功。运行日志与账户操作记录留在私有交付目录。

README 的耗时已依据同日火之眼存量主分类实测修订，见 [运行耗时依据](runtime-estimates.md)。主分类 3 小时 22 分不等于包含评分、首次下载和部署的完整初始化时间。
