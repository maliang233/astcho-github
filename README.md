# Astcho

Astcho（星回）是一个运行在 QQ 上的拟人化 AI 聊天机器人。它基于 NoneBot2 与 OneBot v11，能够参与群聊、处理私聊，并通过注意力、日程、情绪、关系、记忆、图片理解、表情包策展和表达学习形成连续的互动体验。

Astcho 的目标不是成为一个随叫随到的问答助手，而是像群友一样判断什么时候接话、怎样回应，以及何时保持安静。

## 特性

- **群聊注意力**：综合 @、引用、聊天节奏、冷却时间、日程状态和情绪决定是否参与对话。
- **Planner + Reasoning Replyer**：Planner 负责是否回复、情绪变化和配图决策；Reasoning Replyer 使用结构化“做题式”提示，结合人格、关系、记忆和群聊语境生成回复。
- **人格与关系**：通过 JSON 定义身份、性格、行为习惯、喜好与厌恶；群聊中的特殊关系只注入对应用户的回复上下文。
- **情绪系统**：按群维护兴奋度与害羞度，按 `(group_id, user_id)` 维护亲密度，并随时间自然衰减。
- **生物记忆**：使用 ChromaDB 提取、检索、去重和整理记忆，并通过元数据隔离不同群与用户。
- **独立私聊会话**：按 `user_id` 维护互不混合的进程内最近消息历史。
- **视觉理解**：理解图片、GIF、短视频和合并转发，为聊天与表情学习提供语义。
- **MemeCurator**：学习群聊中的表情包，执行人格品味判断、向量检索、模型终审、使用去重和容量淘汰。
- **表达学习**：从群友消息中归纳“使用场景—表达方式”，仅作为风格参考，并支持自动与人工审核。
- **日程系统**：根据星期、时间段和临时状态调整说话欲望与语气。
- **可观测运行链路**：日志覆盖注意力、Planner、Reasoning Replyer、记忆、视觉、策展和表达学习节点。

## 工作流程

```text
QQ / NapCat
     │ OneBot v11
     ▼
消息处理 ──► 注意力与消息聚合 ──► Planner
                                      │
                         ┌────────────┴────────────┐
                         │                         │
                      保持安静                 生成回复
                                                   │
                               人格 + 情绪 + 关系 + 记忆
                                                   │
                                           Reasoning Replyer
                                                   │
                                    文本回复 + 可选策展表情
```

模型只负责受约束的文本和结构化决策。管理、删除、关闭等操作始终由程序权限控制，不由模型决定。

## 环境要求

- Python 3.11 或更高版本
- 支持 OneBot v11 的 QQ 客户端，例如 [NapCat](https://github.com/NapNeko/NapCatQQ)
- OpenAI-compatible 文本模型接口
- 支持图片输入的 OpenAI-compatible 视觉模型接口
- 首次启动时可访问 Hugging Face，以下载配置的嵌入模型

SQLite、ChromaDB 和嵌入模型均在本地运行，不需要 MongoDB。

## 快速开始

### 1. 获取项目

```bash
git clone https://github.com/maliang233/astcho-github.git
cd astcho-github
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Windows PowerShell：

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

开发环境可安装测试与格式化工具：

```bash
pip install -e '.[dev]'
```

### 2. 创建配置

```bash
cp .env.example .env
cp config/profile.example.json config/profile.json
cp config/schedule.example.json config/schedule.json
```

至少需要在 `.env` 中填写：

```dotenv
ASTCHO_ADMINS=123456789
ASTCHO_ALLOWED_GROUPS=123456789

ASTCHO_LLM_API_KEY=replace-me
ASTCHO_LLM_BASE_URL=https://api.example.com/v1
ASTCHO_CHAT_MODEL=your-chat-model
ASTCHO_PLANNER_MODEL=your-fast-json-model
ASTCHO_VISION_MODEL=your-vision-model
ASTCHO_REASONING_MODEL=your-reasoning-model
```

`ASTCHO_ALLOWED_GROUPS` 留空表示不限制群聊。Planner 与 Reasoning Replyer 可以复用聊天模型；独立 Key 或 Base URL 留空时会回落到文本模型配置。

建议：

- Planner 使用速度快、JSON 输出稳定的模型。
- Replyer 使用适合自然中文聊天的模型。
- 视觉模型需要支持 `image_url` 输入。
- Reasoning Replyer 使用提示词内的结构化推理，不依赖模型供应商的原生 thinking 模式。

### 3. 配置 NapCat

Astcho 默认监听：

```text
0.0.0.0:8080
```

在 NapCat 中启用 OneBot v11 **WebSocket 客户端（反向 WebSocket）**，连接地址填写：

```text
ws://127.0.0.1:8080/onebot/v11/ws
```

如果 NapCat 运行在 Docker Desktop，而 Astcho 直接运行在宿主机，使用：

```text
ws://host.docker.internal:8080/onebot/v11/ws
```

如果修改了 `.env` 中的 `PORT`，连接地址中的端口也要同步修改。确保该端口没有被其他程序占用。

### 4. 启动 Astcho

```bash
python -m astcho
```

也可以使用安装后的命令：

```bash
astcho
```

正常启动后会看到类似日志：

```text
✅ 星回启动完成，等待 OneBot 连接
🔗 OneBot 已连接 | bot_id=...
```

首次启动需要下载嵌入模型，耗时取决于网络环境。运行数据会自动创建在 `var/`。

## 配置说明

### 模型与连接

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `HOST` | NoneBot 监听地址 | `0.0.0.0` |
| `PORT` | NoneBot 监听端口 | `8080` |
| `ASTCHO_LLM_API_KEY` | 文本模型 API Key | 必填 |
| `ASTCHO_LLM_BASE_URL` | 文本模型 OpenAI-compatible 地址 | 必填 |
| `ASTCHO_CHAT_MODEL` | 普通回复及后台文本任务模型 | 必填 |
| `ASTCHO_PLANNER_MODEL` | Planner 模型 | 必填 |
| `ASTCHO_PLANNER_API_KEY` | Planner 独立 Key | 文本模型 Key |
| `ASTCHO_PLANNER_BASE_URL` | Planner 独立地址 | 文本模型地址 |
| `ASTCHO_REASONING_ENABLED` | 是否启用 Reasoning Replyer | `true` |
| `ASTCHO_REASONING_MODEL` | Reasoning Replyer 模型 | `ASTCHO_CHAT_MODEL` |
| `ASTCHO_REASONING_API_KEY` | Reasoning 独立 Key | 文本模型 Key |
| `ASTCHO_REASONING_BASE_URL` | Reasoning 独立地址 | 文本模型地址 |
| `ASTCHO_VISION_MODEL` | 视觉模型 | `ASTCHO_CHAT_MODEL` |
| `ASTCHO_VISION_API_KEY` | 视觉模型独立 Key | 文本模型 Key |
| `ASTCHO_VISION_BASE_URL` | 视觉模型独立地址 | 文本模型地址 |

### 行为与数据

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `ASTCHO_ADMINS` | 管理员 QQ 号，多个值用逗号分隔 | 必填 |
| `ASTCHO_ALLOWED_GROUPS` | 群聊白名单，留空表示不限制 | 空 |
| `ASTCHO_DATA_DIR` | SQLite、Chroma、图片和日志目录 | `var` |
| `ASTCHO_EMBEDDING_MODEL` | Sentence Transformers 嵌入模型 | `BAAI/bge-small-zh-v1.5` |
| `ASTCHO_SHORT_HISTORY_LIMIT` | 短期历史上限；`0` 表示不保留 | `10` |
| `ASTCHO_MAX_MEMORIES` | 单次回复最多检索的记忆数 | `8` |
| `ASTCHO_MEME_LIMIT` | 策展表情库容量 | `300` |
| `ASTCHO_EXPRESSION_LEARNING` | 是否启用表达学习 | `true` |
| `ASTCHO_EXPRESSION_LEARN_INTERVAL` | 同一群两次学习的最短间隔（秒） | `900` |
| `ASTCHO_EXPRESSION_LEARN_MIN_MESSAGES` | 触发学习所需消息数 | `10` |
| `ASTCHO_FORWARD_MAX_TEXT_SEGMENTS` | 合并转发最大文本段数 | `200` |
| `ASTCHO_FORWARD_MAX_MEDIA_SEGMENTS` | 转发中最多理解的媒体数 | `20` |
| `ASTCHO_REPLY_COOLDOWN_SECONDS` | 回复后的基础冷却时间（秒） | `5` |
| `ASTCHO_INPUT_PRICE_PER_MILLION` | 每百万输入 Token 的费用估值 | `0` |
| `ASTCHO_OUTPUT_PRICE_PER_MILLION` | 每百万输出 Token 的费用估值 | `0` |
| `ASTCHO_DEBUG` | 是否在终端显示详细运行节点 | `false` |

完整配置见 [.env.example](.env.example)。

## 人格配置

`config/profile.json` 用于定义 Astcho 的稳定人格：

```json
{
  "name": "Astcho",
  "identity": {
    "name": "Astcho",
    "english_name": "Astcho",
    "self_cognition": "A warm, thoughtful AI companion.",
    "personality_tags": ["warm", "thoughtful", "playful"],
    "behavioral_habits": ["Speak naturally and briefly"]
  },
  "preferences": {
    "likes": ["natural conversation"],
    "dislikes": ["preachy slogans"]
  },
  "style": ["Use conversational language"],
  "relationships": {
    "123456789": {
      "role": "close_friend",
      "appellation": "朋友",
      "desc": "A trusted friend."
    }
  }
}
```

身份、性格、习惯、偏好和表达风格会进入群聊、私聊与 MemeCurator。`relationships` 仅在群聊回复对应用户时注入，不会进入私聊或全局表情策展提示。

请勿提交真实 QQ 号、私人关系描述或其他个人资料。`config/profile.json` 已被 Git 忽略。

## 日程配置

`config/schedule.json` 使用时间段控制说话欲望与当前状态：

```json
{
  "default": [
    {"start": "00:00", "end": "07:59", "talk_value": 5, "mood": "sleepy"},
    {"start": "08:00", "end": "23:59", "talk_value": 50, "mood": "calm"}
  ]
}
```

`talk_value` 范围为 `0-100`，数值越高，Astcho 越愿意主动参与没有明确 @ 它的群聊。明确 @ 或引用仍会优先触发 Planner。

高级配置可以使用 `routines`、`weekly_rules` 和 `yearly_specials`。`/schedule override` 以及状态快捷命令要求配置中存在对应的 routine。

## 数据与隐私

默认运行目录：

```text
var/
├── astcho.sqlite3    # 关系、Meme 元数据、表达规则、视觉缓存和用量
├── chroma/           # episodic_memory 与 meme_curated_library
├── memes/            # 本地策展图片
└── logs/             # 每日日志
```

- Chroma 记忆使用 `group_id` 与 `user_id` 元数据限定检索范围。
- 私聊最近消息按 `user_id` 隔离并保存在当前进程内，重启后清空。
- 用户关系按 `(group_id, user_id)` 隔离。
- 表达学习按群隔离，只持久化抽象后的表达规则。
- Planner 与结构化模型输出经过 Pydantic 校验，非法结果使用安全降级。
- `.env`、本地人格、日程、数据库、向量索引、日志和图片均不会被 Git 跟踪。
- 日志不会记录 API Key 或完整模型思维链，但聊天内容与调试节点可能包含私人信息；不要公开上传 `var/`。

## 命令

普通用户可用：

| 命令 | 说明 |
| --- | --- |
| `/what` | 查看当前会话最近发送的表情信息 |
| `/schedule status` | 查看当前日程状态 |

管理员可用：

| 命令 | 说明 |
| --- | --- |
| `/astcho_status` | 查看运行状态 |
| `/stats` | 查看记忆、策展表情和表达规则数量 |
| `/recent`、`/astcho_memories` | 查看当前会话最近记忆 |
| `/astcho_reset_memory` | 重置当前会话记忆 |
| `/clean` | 合并重复记忆，不清空整个记忆库 |
| `/bill` | 查看 Token 用量与费用估值 |
| `/del_meme` | 删除当前会话最近发送的策展表情 |
| `/learn`、`/learn_meme` | 收藏当前会话最近发送的表情 |
| `/teach_meme` | 回复一张图片并主动加入策展库 |
| `/reset_meme` | 清空策展表情库及本地文件 |
| `/schedule override <routine> [minutes] [mood]` | 临时切换日程状态 |
| `/schedule clear` | 清除临时日程 |
| `/schedule reload` | 重新加载日程文件 |
| `/打游戏输了`、`/生病了`、`/恢复正常` | 日程状态快捷命令 |
| `/shutdown` | 保存待处理记忆并安全停止进程 |

私聊中的记忆命令始终限制在当前用户，不会读取其他用户的私聊记忆。

## 日志与排错

设置以下变量显示详细链路：

```dotenv
ASTCHO_DEBUG=true
```

文件日志始终保留 DEBUG 信息，位置为 `var/logs/YYYY-MM-DD.log`。

### NapCat 已收到消息，但 Astcho 不回复

依次检查：

1. 启动日志是否出现 `OneBot 已连接`。
2. 群号是否包含在 `ASTCHO_ALLOWED_GROUPS` 中。
3. DEBUG 日志中的 `is_mention`、`is_reply` 和注意力判定结果。
4. Planner 是否返回 `REPLY`，以及 Reasoning Replyer 是否成功生成正文。

Astcho 不会回复每一条普通群消息；这是注意力系统的预期行为。使用 @ 或引用可直接触发注意力判断。

### 启动时报 `address already in use`

`PORT` 已被其他程序占用。停止占用该端口的程序，或修改 `.env` 中的 `PORT`，并同步修改 NapCat 的反向 WebSocket 地址。

### 首次启动较慢

ChromaDB 初始化时会加载 Sentence Transformers 嵌入模型。首次运行需要下载模型，之后会使用本地缓存。

### 图片理解失败

确认视觉模型支持图片输入，并确保 Astcho 所在环境能够访问 NapCat 提供的图片 URL。

## 项目结构

```text
src/astcho/
├── handlers/       # 群聊、私聊、管理命令、媒体和定时任务
├── services/       # 对话、注意力、情绪、记忆、视觉、Meme 和表达学习
├── storage/        # SQLite 与 ChromaDB
├── domain/         # Pydantic 数据模型
├── prompts.py      # Planner、Replyer 和后台任务提示词
├── runtime.py      # 服务容器、会话锁与后台任务管理
├── config.py       # 环境变量与人格配置
└── bot.py          # NoneBot 初始化和生命周期
```

程序入口：

```bash
python -m astcho
```

模块导入本身不会连接模型或写入数据库；所有服务都在运行入口统一初始化。

## 开发

```bash
pip install -e '.[dev]'
ruff format src tests
ruff check src tests
python -m compileall -q src tests
pytest
```

提交代码前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

## License

Astcho 使用 [MIT License](LICENSE)。
