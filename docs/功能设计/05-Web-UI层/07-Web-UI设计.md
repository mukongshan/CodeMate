# 07 - Web UI 设计基础

> 当前实现基线：2026-09-02
>
> 本文描述 CodeMate Web UI 的通用交互约束；工作台的完整区域布局和文件/终端能力见 [08-VSCode 风格会话工作台](08-VSCode风格会话工作台.md)。

## 一、页面状态

前端只有两个顶层状态：

1. 没有 `sessionId` 时显示 `SessionPicker`，负责 Workspace 选择、Session 创建/打开/重命名/删除。
2. 有 `sessionId` 时显示 `Workspace`，连接当前 Session 的快照和 WebSocket。

Session Picker 使用原生目录选择接口 `POST /api/filesystem/pick-directory`，在浏览器本地保存最近一次路径 `codemate:last-workspace`。它不实现自定义全盘文件树。

## 二、数据投影

同一份 Session 数据在界面中有三种投影：

| 投影 | 组件 | 关注点 |
|---|---|---|
| 结构投影 | `TreeCanvas` / `TreeNode` | Entry 树、分叉、Lane 路径和轮次关系 |
| 内容投影 | `ConversationPanel` / `MessageBubble` | 当前 Lane 的用户消息、Agent 回复和工具过程 |
| 工作区投影 | Explorer / Editor / Source Control / Terminal | 当前 Lane 文件和 Git 状态 |

树和工作区不是两套事实数据；切换 Lane 后都从当前 Session/Lane 状态重新投影。

## 三、会话树

### 3.1 轮次卡片

树布局使用 `buildRoundGraph()` 将一个用户 Entry 与其后续 assistant/tool 条目聚合成 `ConversationRound`。一轮对话渲染为一张语义卡片，工具详情折叠在详情面板，不把每个工具结果误显示成一轮新对话。

同层兄弟 Lane 的轮次共享 `round.depth`，横向使用 Lane 索引排列：`x = laneIndex × 228`，`y = round.depth × 136`。这样不同 Lane 的第一轮处于同一高度。

### 3.2 路径和颜色

路径判断只沿 Entry 的 `parent` 指针完成，不能按 `Entry.lane` 过滤。公共祖先可能同时属于多个 Lane 的当前路径，UI 应以当前关注 Lane 或多色状态环表达，而不是创建虚假的第三种 Lane。

节点使用图标表达角色，颜色表达 Lane 分类，状态点表达成功、等待、警告和错误。Lane 顺序以服务端返回顺序为准；超过视觉色板容量的非当前 Lane 可降为中性灰，但不从列表中删除。

### 3.3 节点操作

- 点击轮次打开 `TreeNodeDetailPanel`，查看用户内容、Agent 内容和工具摘要。
- 点击 Lane 切换入口后刷新当前路径、对话和工作区状态。
- 分支对比通过 `CompareDrawer` 加载两个 Lane 的对话差异，代码差异由 Source Control 或同一抽屉加载。
- 节点详情和对比是 UI 状态，不写入 Session JSONL。

## 四、对话面板

### 4.1 流式消息

WebSocket 收到 `message_start` 时登记当前 assistant message；收到 `text_delta` 时追加文本；`message_end` 时结束流式状态。工具调用挂接到同一 assistant message，避免在 UI 中生成不属于当前轮次的独立对话。

用户提交时先插入临时 `local-user-*` 消息，后端 `node_added` 返回真实 Entry ID 后完成替换。历史快照和实时事件合并时，临时消息不能重复显示。

### 4.2 工具、子 Agent 和错误

工具卡片展示工具名、参数、运行状态、结果和文件变更入口。子 Agent 只显示 `subagent_started`、`subagent_progress`、`subagent_done` 的摘要和进度；子 Agent 内部 Entry 不进入父树。

运行错误使用结构化通知，区分 Agent 错误、API 错误和 WebSocket 连接错误，并展示可用建议。WebSocket 断开时保留当前界面状态，显示自动重连横幅；成功连接后重新同步快照。

## 五、权限确认

权限弹窗展示工具名、参数、风险等级和警告，用户可以 `allow_once`、`allow_always` 或 `deny`。权限等待期间后端仍保持 WebSocket 接收循环，前端响应必须能在 Agent 长时间运行时到达。

权限设置页提供 Session 级命令黑名单；黑名单、危险命令检查、Workspace 路径检查和系统路径拒绝共同构成安全边界。前端提示不是安全边界，所有判断由后端重复执行。

## 六、文件修改审查

Agent 的 `write_file`/`edit_file` 成功后，后端通过 `tool_call_end` 携带 `file_change` 元数据；前端在独立的 `fileReviews` Map 中创建 `FileReviewPanel`。审查卡片包含文件路径、统一 Diff、增加/删除统计、二进制或截断提示和接受/拒绝操作。

审查状态不嵌入普通 `ToolCallCard`，其生命周期为：

- Run 完成后仍保留；
- 同一 Session 的快照同步和 Lane 切换不清空；
- 接受单条只移除该 review；
- 发送下一条用户消息或切换 Workspace/Session 时清空；
- 后端接受/拒绝前校验文件版本，版本不一致则拒绝覆盖。

## 七、WebSocket 约束

所有服务端事件使用 `{type, data}` 信封，字段使用 `snake_case`。当前主要事件如下：

| 类别 | 事件 |
|---|---|
| Run | `run_started`、`run_completed`、`run_error`、`run_interrupt_requested` |
| 消息 | `message_start`、`text_delta`、`message_end`、`node_added` |
| 工具 | `tool_call_start`、`tool_call_end`、`permission_request`、`permission_resolved` |
| Lane/Git | `lane_created`、`lane_switched`、`lane_renamed`、`lane_deleted`、`lane_checkpoint_created`、`lane_code_integrated` |
| 记忆/标题 | `context_loaded`、`compaction_completed`、`compaction_failed`、`session_title_updated` |
| 子 Agent | `subagent_started`、`subagent_progress`、`subagent_done` |
| 终端 | `terminal_ready`、`terminal_output`、`terminal_exit`、`terminal_closed`、`terminal_error` |

客户端消息包括 `send_message`、`permission_response`、`interrupt_run` 和终端的 `terminal_open`、`terminal_input`、`terminal_signal`、`terminal_close`。

## 八、实现边界

- UI 不直接读写 JSONL，不把前端临时状态当作持久化事实。
- UI 不绕过后端的 Workspace/Lane 路径校验和权限检查。
- 当前桌面布局优先，移动端 Tab 化布局、跨刷新布局持久化和独立日志查询不属于当前实现。
- UI 中的 Source Control 是 CodeMate Lane/Git 能力的入口，不承诺替代完整 Git 客户端。

## 九、实现对应

| 代码 | 作用 |
|---|---|
| `web-ui/src/App.tsx` | 顶层页面状态 |
| `web-ui/src/components/SessionPicker.tsx` | Workspace/Session 入口 |
| `web-ui/src/components/Workspace.tsx` | 工作台外壳 |
| `web-ui/src/components/tree/` | 树形历史和轮次详情 |
| `web-ui/src/components/conversation/` | 对话、工具、权限、审查和记忆 |
| `web-ui/src/hooks/useWebSocket.ts` | 事件解析和连接恢复 |
| `web-ui/src/store/index.ts` | 快照、运行态和 UI 状态 |

