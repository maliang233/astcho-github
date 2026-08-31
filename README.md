# Astcho

Astcho 是一个运行在 QQ 上的 AI 伴侣机器人。它基于 NoneBot2 和 OneBot v11，在群聊与私聊中提供自然对话，并通过日程、情绪、记忆、图片理解、表情策展和表达学习形成连续、具有个性的互动体验。

## 功能

- 群聊注意力：结合 @、回复关系、聊天节奏、日程状态和冷却时间判断是否参与对话。
- 私聊对话：按用户隔离会话，并保留最近 50 条独立上下文。
- 模型分工：Planner 负责行为决策，Reasoning Replyer 结合人设、关系、情绪、记忆和表达习惯生成回复，视觉模型负责理解图片；Reasoning 不可用时自动回落到普通 Replyer。
- 自然群聊节奏：短时间消息聚合后统一判断，支持 @/回复识别、引用回复、多段气泡和拟人化发送间隔。
- 生物记忆：使用 ChromaDB 提取、检索和去重长期与短期记忆。
- 情绪与关系：按群维护兴奋度、害羞度，并按 `(group_id, user_id)` 记录亲密度。
- 媒体理解：识别图片、短视频/GIF，并展开或总结合并转发；失败时安全降级。
- MemeCurator：通过品味筛选、向量召回、模型终审和会话去重完成学习与配图。
- 表达学习：提炼“适用情境—表达方式”，经过自动审核与管理员人工审核后注入回复风格。
- 日程系统：根据时间段调整参与意愿和说话状态。
- 管理命令：查看状态、检查记忆和执行受权限保护的重置操作。

## 技术栈

- Python 3.11+
- NoneBot2 / OneBot v11
- OpenAI-compatible API
- SQLite / ChromaDB / Pydantic

## 快速开始

### 1. 准备 OneBot 服务

部署支持 OneBot v11 的 QQ 客户端，例如 NapCat，并配置反向 WebSocket。Astcho 默认监听 `0.0.0.0:8080`。当 NapCat 运行在 Docker Desktop 中时，反向 WebSocket 地址使用：

```text
ws://host.docker.internal:8080/onebot/v11/ws
```

### 2. 安装项目

```bash
git clone <your-repository-url>
cd astcho
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

Windows PowerShell 使用 `.venv\Scripts\Activate.ps1` 激活虚拟环境。

### 3. 创建配置

```bash
cp .env.example .env
cp config/profile.example.json config/profile.json
cp config/schedule.example.json config/schedule.json
```

编辑 `.env`，填写模型 API、管理员 QQ 号和需要启用的群号：

```dotenv
ASTCHO_LLM_API_KEY=replace-me
ASTCHO_LLM_BASE_URL=https://api.example.com/v1
ASTCHO_CHAT_MODEL=your-chat-model
ASTCHO_PLANNER_MODEL=your-planner-model
ASTCHO_VISION_MODEL=your-vision-model
ASTCHO_ADMINS=123456789
ASTCHO_ALLOWED_GROUPS=123456789
```

文本、Planner、Reasoning Replyer 和视觉模型均支持 OpenAI-compatible 接口。独立 API 未设置时，会使用文本 API 的 Key 和地址。

### 4. 启动

```bash
python -m astcho
```

必要配置缺失时，程序会在初始化存储或加载模型前给出错误信息。

## 配置

| 变量 | 用途 | 默认值 |
| --- | --- | --- |
| `ASTCHO_ADMINS` | 管理员 QQ 号，逗号分隔 | 必填 |
| `ASTCHO_ALLOWED_GROUPS` | 启用的群号，留空表示不限制 | 空 |
| `ASTCHO_DATA_DIR` | SQLite、Chroma 和图片目录 | `var` |
| `ASTCHO_REASONING_ENABLED` | 启用 Reasoning Replyer，并在失败时回落到普通 Replyer | `true` |
| `ASTCHO_REASONING_MODEL` | Reasoning Replyer 模型 | `ASTCHO_CHAT_MODEL` |
| `ASTCHO_MAX_MEMORIES` | 单次回复检索的记忆数量 | `8` |
| `ASTCHO_MEME_LIMIT` | 表情库容量上限 | `300` |
| `ASTCHO_EXPRESSION_LEARNING` | 是否启用群聊表达学习 | `true` |
| `ASTCHO_EXPRESSION_LEARN_INTERVAL` | 两次表达学习的最短间隔（秒） | `900` |
| `ASTCHO_EXPRESSION_LEARN_MIN_MESSAGES` | 触发表达学习的最少消息数 | `10` |
| `ASTCHO_FORWARD_MAX_TEXT_SEGMENTS` | 转发消息最大文本段数 | `200` |
| `ASTCHO_FORWARD_MAX_MEDIA_SEGMENTS` | 转发消息执行视觉理解的最大媒体数 | `20` |
| `ASTCHO_INPUT_PRICE_PER_MILLION` | 每百万输入 Token 价格，用于账单估算 | `0` |
| `ASTCHO_OUTPUT_PRICE_PER_MILLION` | 每百万输出 Token 价格，用于账单估算 | `0` |
| `ASTCHO_DEBUG` | 输出详细的注意力、Planner、Replyer、记忆、媒体与学习链路 | `false` |

完整配置示例见 [.env.example](.env.example)。人格和日程分别通过 `config/profile.json` 与 `config/schedule.json` 配置。

人格配置支持 `identity`、`preferences.likes/dislikes`、`style`、`relationships` 和
`group_profiles`。身份、性格、行为习惯、偏好与表达风格会进入群聊、私聊和 MemeCurator；
具体用户关系只进入对应用户的回复 Prompt，不会进入全局表情策展与终审。

## 数据与隐私

所有运行数据位于 `ASTCHO_DATA_DIR`，默认是被 Git 忽略的 `var/`：

```text
var/
├── astcho.sqlite3
├── chroma/
├── memes/
└── logs/          # 每日运行日志
```

调试时将 `ASTCHO_DEBUG=true`。终端会按旧式阶段语义显示 `[System]`、用户输入、AI
输出以及 `[概率]`、`[决策]`、`[推理模式]` 等节点；文件日志始终保留 DEBUG 级别，位于
`var/logs/YYYY-MM-DD.log`。为避免泄露凭据，框架自身保持 INFO，完整 Prompt、API Key
和模型思维链不会写入日志。

- 群聊记忆按 `group_id` 隔离，私聊记忆按当前 `user_id` 隔离。
- 用户关系按 `(group_id, user_id)` 隔离。
- 表达学习按群隔离，只持久化抽象后的表达规则，不保存完整聊天记录。
- 模型输出经过 Pydantic 校验，非法 Planner 决策会降级为不回复。
- `.env`、数据库、缓存、图片和本地人格文件不会被 Git 跟踪。

## 管理命令

危险操作和诊断命令仅允许 `ASTCHO_ADMINS` 中的用户使用：

- `/astcho_status`：查看运行状态。
- `/stats`：查看记忆、策展表情和表达规则数量。
- `/recent` 或 `/astcho_memories`：查看当前会话最近的记忆。
- `/astcho_reset_memory`：重置当前会话记忆。
- `/clean`：整理并合并重复记忆，不会清空记忆库。
- `/what`、`/del_meme`：查看或删除最近发送的表情。
- `/learn`、`/learn_meme`、`/teach_meme`、`/reset_meme`：管理表情学习。
- `/bill`：查看 Token 使用量和按配置价格计算的费用估算。
- `/schedule`：支持 `status`、`override <routine> [minutes] [mood]`、`clear` 和 `reload`。
- `/打游戏输了`、`/生病了`、`/恢复正常`：日程状态快捷命令。
- `/shutdown`：安全停止进程。

私聊中的记忆命令始终限制在当前用户，不会读取其他用户的数据。

## 项目结构

```text
src/astcho/
├── handlers/    # 群聊、私聊、命令和定时任务
├── services/    # 对话、注意力、记忆、视觉、表情和表达学习
├── storage/     # SQLite 与 ChromaDB
├── domain/      # LLM 输出及领域数据模型
├── prompts.py   # Planner、Reasoning Replyer、Replyer、记忆、视觉和表达学习 Prompt
├── runtime.py   # 运行时状态、锁和后台任务
└── bot.py       # NoneBot 初始化与程序入口
```

模块导入不会连接模型或创建数据库；这些操作统一在运行入口完成。

## 开发

```bash
pip install -e '.[dev]'
ruff check src tests
pytest
python -m compileall -q src
```

贡献代码前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

## License

[MIT](LICENSE)
