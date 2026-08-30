# Astcho

Astcho 是一个面向 QQ 的、隐私友好的 NoneBot2 AI 伴侣。公开版保留群聊与私聊、日程与情绪、向量记忆、图片理解和表情策展功能；所有本地数据默认写入被 Git 忽略的 `var/`。

## 要求

- Python 3.11+
- 独立部署的 OneBot v11 实现（例如 NapCat）
- OpenAI-compatible 文本模型；图片功能需要支持视觉输入的模型

## 安装与启动

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
cp config/profile.example.json config/profile.json
cp config/schedule.example.json config/schedule.json
python -m astcho
```

编辑 `.env`，至少填写 API 地址、模型名、Key 和管理员 QQ 号。NoneBot 默认监听 `127.0.0.1:8080`，请让 OneBot v11 客户端使用反向 WebSocket 连接对应地址。缺少必要配置时程序会直接给出明确错误，不会创建数据库或加载模型。

## 数据与隐私

- SQLite、Chroma、图片和缓存统一位于 `ASTCHO_DATA_DIR`（默认 `var/`）。
- 私聊记忆按当前 `user_id` 隔离；群聊记忆按 `group_id` 隔离。
- 仓库不应包含 `.env`、数据库、图片、日志、真实人格或账号信息。
- 模型输出经过结构校验；模型不能执行管理操作。

管理命令为 `/astcho_status`、`/astcho_memories`、`/astcho_reset_memory` 和 `/astcho_schedule`，仅 `ASTCHO_ADMINS` 中的用户可用。

## 开发检查

```bash
ruff check src tests
pytest
python -m compileall -q src
```

本项目采用 MIT License。提交改动前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

