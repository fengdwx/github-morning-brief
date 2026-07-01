# GitHub Morning Brief

每天早上生成一份中文 GitHub 开源项目晨间简报，并推送到飞书群机器人。

## 关注方向

- AI/LLM、Agent、开发者工具、自动化、生产力工具
- 开源基础设施、工程实践、产品设计
- 固定冷门观察：历史预测、计算历史、社会复杂系统、事件预测、预测市场、时间推理、历史数据库和历史事件模拟

## 运行方式

GitHub Actions 会在北京时间每天 08:30 自动运行：

```yaml
30 0 * * *
```

这个 cron 是 UTC 时间，对应 Asia/Shanghai 的 08:30。

也可以在 GitHub Actions 页面手动点击 `Run workflow` 测试。

## GitHub Secrets

在仓库的 `Settings -> Secrets and variables -> Actions` 里配置：

| 名称 | 必填 | 用途 |
| --- | --- | --- |
| `FEISHU_WEBHOOK_URL` | 是 | 飞书群机器人 webhook |
| `ANTHROPIC_AUTH_TOKEN` | 推荐 | 用 Anthropic/Claude-compatible 接口生成更高质量中文简报 |
| `ANTHROPIC_BASE_URL` | 推荐 | Anthropic/Claude-compatible 接口地址 |
| `OPENAI_API_KEY` | 否 | Anthropic-compatible 不可用时的 OpenAI 备用生成接口 |

可选变量：

| 名称 | 默认值 | 用途 |
| --- | --- | --- |
| `ANTHROPIC_MODEL` | `cc-deepseek-v4-pro` | Anthropic-compatible 生成模型 |
| `OPENAI_MODEL` | `gpt-5.4-mini` | OpenAI 备用生成模型 |
| `ALLOW_FALLBACK_BRIEF` | 空 | 设为 `true` 时，AI 生成失败才允许发送基础元数据版简报 |

脚本会优先使用 `ANTHROPIC_AUTH_TOKEN` + `ANTHROPIC_BASE_URL`，失败后尝试 `OPENAI_API_KEY`。默认情况下，AI 生成失败会直接中止，避免发送低质量的元数据版简报。

## 本地测试

```bash
python3 src/github_morning_brief.py --dry-run
```

如果只是想在没有模型密钥时检查数据抓取链路，可以显式启用基础版 fallback：

```bash
ALLOW_FALLBACK_BRIEF=true python3 src/github_morning_brief.py --dry-run
```

发送到飞书：

```bash
FEISHU_WEBHOOK_URL="https://open.feishu.cn/open-apis/bot/v2/hook/..." \
ANTHROPIC_AUTH_TOKEN="sk-..." \
ANTHROPIC_BASE_URL="https://example.com" \
ANTHROPIC_MODEL="cc-deepseek-v4-pro" \
python3 src/github_morning_brief.py
```

## 设计说明

- 不把任何密钥写进仓库。
- 只使用 Python 标准库，GitHub Actions 不需要安装依赖。
- GitHub 数据来自 GitHub Trending 页面和 GitHub Search API。
- 飞书消息过长时会自动分段发送。
