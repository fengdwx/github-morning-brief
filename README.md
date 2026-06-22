# GitHub Morning Brief

每天工作日早上生成一份中文 GitHub 开源项目晨间简报，并推送到飞书群机器人。

## 关注方向

- AI/LLM、Agent、开发者工具、自动化、生产力工具
- 开源基础设施、工程实践、产品设计
- 固定冷门观察：历史预测、计算历史、社会复杂系统、事件预测、预测市场、时间推理、历史数据库和历史事件模拟

## 运行方式

GitHub Actions 会在北京时间工作日 08:30 自动运行：

```yaml
30 0 * * 1-5
```

这个 cron 是 UTC 时间，对应 Asia/Shanghai 的 08:30。

也可以在 GitHub Actions 页面手动点击 `Run workflow` 测试。

## GitHub Secrets

在仓库的 `Settings -> Secrets and variables -> Actions` 里配置：

| 名称 | 必填 | 用途 |
| --- | --- | --- |
| `FEISHU_WEBHOOK_URL` | 是 | 飞书群机器人 webhook |
| `OPENAI_API_KEY` | 否 | 用 OpenAI 生成更高质量中文简报 |

可选变量：

| 名称 | 默认值 | 用途 |
| --- | --- | --- |
| `OPENAI_MODEL` | `gpt-5.4-mini` | 生成简报使用的模型 |

如果没有 `OPENAI_API_KEY`，脚本仍会发送一个基础版简报。

## 本地测试

```bash
python3 src/github_morning_brief.py --dry-run
```

发送到飞书：

```bash
FEISHU_WEBHOOK_URL="https://open.feishu.cn/open-apis/bot/v2/hook/..." \
OPENAI_API_KEY="sk-..." \
python3 src/github_morning_brief.py
```

## 设计说明

- 不把任何密钥写进仓库。
- 只使用 Python 标准库，GitHub Actions 不需要安装依赖。
- GitHub 数据来自 GitHub Trending 页面和 GitHub Search API。
- 飞书消息过长时会自动分段发送。
