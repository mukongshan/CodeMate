# Agent 记忆系统与上下文管理

> 当前实现基线：2026-09-02

## 1. 背景与目标

当前 Agent 已经能够保存树形对话历史，但上下文主要依赖固定窗口裁剪，历史达到上限后会直接丢失较早信息。对于需要多轮分析、反复修改和运行测试的中小型项目，这会导致 Agent 忘记任务目标、已完成的文件修改、失败原因和用户约束。

本方案将记忆系统升级为“持久化事实 + 会话摘要 + 最近上下文 + 项目指令”四层结构，使 Agent 能够在上下文受限时继续工作，同时保留现有 Workspace、Session、Lane 和 JSONL 树形历史边界。

目标：

- 支持中小项目的多轮开发任务，不因上下文窗口增长而失去关键进展。
- 压缩结果可落盘、可重启恢复，并能沿 Lane 分支正确投影。
- 保留工具调用和工具结果的协议配对，避免生成非法 LLM 请求。
- 将项目级约束和长期记忆注入每次 Agent 运行，而不是只依赖当前聊天记录。
- 压缩失败时继续使用原始历史，不破坏已有会话。

## 2. 范围与非目标

### 2.1 本期范围

- 在 Entry 中增加 entry_type 和 metadata，兼容旧 JSONL 数据。
- 增加会话压缩摘要 Entry，保存覆盖范围、保留范围、token 估算和摘要调用用量。
- 增加自动阈值压缩，以及 POST /api/sessions/{session_id}/compact 手动压缩接口。
- 在 Agent 系统提示中加载当前工作区的 AGENTS.md、CODEMATE.md 和 .codemate/memory.md。
- 在上下文投影阶段优先使用最新摘要，再拼接摘要之后的有效历史和最近消息。

### 2.2 非目标

- 本期不引入向量数据库、Embedding、远程 RAG 或 MCP 记忆服务。
- 本期不自动修改项目中的记忆文件；长期事实由 Agent 或用户显式整理后写入。
- 本期不改变现有树形历史、Lane 指针和前端整树快照协议。

## 3. 记忆分层

| 层级 | 存储位置 | 内容 | 生命周期 |
| --- | --- | --- | --- |
| 项目指令 | 工作区根目录 AGENTS.md / CODEMATE.md | 工作方式、边界、安全要求 | 项目级 |
| 项目记忆 | 工作区 .codemate/memory.md | 稳定架构事实、已知坑、约定 | 项目级，可人工维护 |
| 会话摘要 | Session JSONL 中的 entry_type=compaction | 目标、约束、进展、阻塞、决策、文件和下一步 | 会话级，按 Lane 投影 |
| 最近上下文 | Session JSONL 的摘要后历史 | 当前任务最近的用户消息、Agent 回复和工具结果 | 会话级，自动保留 |

项目文件只在当前 Lane 工作目录中读取。单个文件读取上限为 128KB，避免异常文件直接占满上下文。

## 4. 上下文组装

每次调用 LLM 时，消息顺序为：

1. Agent 主系统提示。
2. 当前 Lane、当前工作目录和执行边界。
3. 当前工作区项目指令与项目记忆。
4. 会话压缩摘要（如果存在）。
5. 摘要之后的保留消息和最近消息。
6. 本轮新增的用户消息、Agent 回复及工具结果。

历史投影仍由 parent 链决定，Entry.lane 不参与路径判断。压缩摘要是一个新的树节点，父节点指向压缩前叶子；其 metadata 记录投影所需的保留 Entry id，因此重启后可以从 JSONL 重建同样的有效上下文。

## 5. 自动压缩策略

### 5.1 触发条件

在每轮 LLM 调用前估算当前 Lane 的有效上下文 token 数。当其超过以下两者中的较小值时触发压缩：

- max_context_tokens * compaction_threshold_ratio；
- max_context_tokens - context_reserve_tokens。

手动压缩忽略阈值，但仍要求至少存在一段可压缩历史。

### 5.2 压缩范围

压缩器从历史前部选择需要归纳的消息，保留最近约 compaction_keep_recent_tokens 的消息。若保留区从工具结果开始，则向前扩展到对应的非工具消息，避免留下孤立的工具结果。

摘要必须包含以下章节：

- 目标
- 约束与偏好
- 已完成
- 进行中
- 阻塞与未知
- 关键决策
- 相关文件
- 下一步

已有压缩摘要会作为输入传给下一次压缩，新的摘要以最新历史为准合并更新，避免多次压缩后只剩最后一小段内容。

### 5.3 失败安全

摘要调用失败、返回空内容或写入失败时：

- 不更新 Lane 指针。
- 保留原始历史。
- 向运行时发送 compaction_failed 事件并继续当前 Agent 流程。
- 记录失败原因，便于诊断和重试。

## 6. 数据模型

| 字段 | 普通消息 | 压缩摘要 |
| --- | --- | --- |
| role | user / assistant / tool | assistant，投影为 system |
| content | 文本或结构化块 | 结构化摘要文本 |
| entry_type | message | compaction |
| metadata | {} | 覆盖/保留 id、token 估算、原因、调用用量 |

旧 JSONL 缺少新增字段时分别按 message 和空字典处理，因此可以直接加载历史数据。

## 7. Lane 与分支语义

压缩只移动目标 Lane 的叶子指针，不删除任何原始 Entry。其他 Lane 仍然沿自己的 parent 链读取原始历史，不会被主 Lane 的压缩影响。

从已压缩节点创建的新 Lane 会继承摘要投影。不同 Lane 后续产生的消息会在各自叶子下继续追加；未来如果某个 Lane 再次压缩，只更新该 Lane 的指针和对应摘要节点。

## 8. 配置项

| 环境变量 | 默认值 | 作用 |
| --- | ---: | --- |
| MAX_CONTEXT_TOKENS | 8000 | 历史上下文预算 |
| CONTEXT_RESERVE_TOKENS | 2000 | 为当前回复和协议开销预留空间 |
| COMPACTION_KEEP_RECENT_TOKENS | 3000 | 压缩后保留最近消息预算 |
| COMPACTION_SUMMARY_MAX_TOKENS | 1200 | 摘要模型输出上限 |
| COMPACTION_THRESHOLD_RATIO | 0.8 | 自动压缩比例阈值 |

## 9. 实现分期

### P0：已实现

- Entry 扩展和 JSONL 向后兼容。
- 项目指令与 .codemate/memory.md 加载。
- 会话摘要生成、持久化和重启恢复。
- Agent 自动阈值压缩。
- 手动压缩 REST 接口。

### 已接入前端的能力

- 前端显示记忆预算、使用量和阈值状态。
- 前端提供“立即压缩”操作，调用手动压缩 REST 接口并同步快照。

### 后续增强

- 在摘要节点上提供展开原始历史的查看入口。
- 增加压缩耗时、token 节省和失败率指标。

### P2：规模化增强

- 项目记忆的结构化分区与冲突检测。
- 重要事实提取和用户确认后写入项目记忆。
- 针对超大仓库的按目录、按任务动态加载记忆。
- 可选的语义检索层，但不能替代摘要和最近上下文。

## 10. 验收标准

- 老版本 JSONL 可以正常加载。
- 上下文达到阈值后能生成并持久化摘要，下一轮能看到摘要和最近历史。
- 重启 Session 后摘要投影保持一致。
- 工具调用/工具结果不产生孤立消息。
- 摘要失败不破坏原始对话，Agent 仍可继续运行。
- 手动压缩在会话运行期间返回冲突错误，在空闲会话中返回明确结果。
- 项目指令和项目记忆只从当前工作区加载，并限制文件大小。

## 11. 参考实现借鉴

- Pi：使用专门的 compaction Entry，保存摘要和覆盖范围，并在后续压缩时合并既有摘要。
- DeepSeek Harness：将压缩作为独立能力，配合 token 计量、上下文裁剪、持久化事件和失败恢复。
- OpenCode：区分持久化会话历史与动态系统上下文，并支持上下文 epoch/snapshot 思路。

本实现保留 CodeMate 已有的树形 Entry、SessionStorage 和 LaneManager，将上述经验收敛为本地、离线友好的首版记忆闭环。

**实现对应**：`backend/src/memory/manager.py`、`backend/src/memory/project.py`、`backend/src/storage/session_storage.py`、`web-ui/src/components/conversation/MemoryBudgetBar.tsx`。
