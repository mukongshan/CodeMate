# 08 - VSCode 风格会话工作台

> 当前实现基线：2026-09-02
>
> 本文将草稿“VSCode 风格会话工作台改造需求与实施方案”正式化，并以当前 `Workspace.tsx`、`WorkbenchPanels.tsx`、Zustand Store 和 WebSocket Hook 的实际行为为准。

## 一、产品定位

进入 Session 后，CodeMate 不是单纯的“树形图 + 对话”页面，而是围绕当前 Lane 工作目录组织的桌面开发工作台。它借鉴 VSCode 的信息架构，但不追求复制完整 IDE：

- 左侧活动栏负责选择功能视图；
- 可关闭、可拖动的侧边栏承载资源管理器、分支历史、源代码管理和搜索；
- 中间主区承载文件标签页和编辑器；
- 底部可展开终端；
- 右侧固定对话区承载 Agent 的实时运行反馈。

工作台所有文件操作都针对当前 Lane 的工作目录。切换 Lane 后，文件树、Git 状态、编辑器请求和终端新会话都随当前 Lane 更新。

## 二、当前布局

```text
┌──────────────────────────────────────────────────────────────────────┐
│ Toolbar：工作区 / Session 标题 / Lane / Agent 状态 / 连接 / 操作      │
├────┬──────────────────────┬─────────────────────────┬───────────────┤
│活动│ 可关闭侧边栏          │ 文件编辑主区             │ Agent 对话区    │
│栏  │ explorer              │ tabs + 内容 + 保存      │ 消息 / 工具      │
│    │ history               │                         │ 权限 / 子Agent   │
│    │ source-control        │                         │ 输入 / 状态      │
│    │ search                │                         │                 │
├────┴──────────────────────┴─────────────────────────┴───────────────┤
│ 终端（按需显示，可拖动高度，绑定当前 Lane）                           │
└──────────────────────────────────────────────────────────────────────┘
```

活动栏的当前视图再次点击会关闭侧边栏；侧边栏和对话区都有尺寸拖动条，宽度由 Store 约束在安全范围内。双击分隔条可恢复默认宽度。布局尺寸目前只保存在前端内存中，刷新后回到默认值。

## 三、功能视图

### 3.1 资源管理器

`ExplorerPanel` 按需请求当前 Lane 工作区的目录列表，支持展开目录、刷新根目录和打开文件。目录接口最多返回 500 项，并返回 `truncated` 标志；前端不构造自定义全盘浏览器，也不访问 Session 数据目录。

打开文件会创建一个编辑器标签页，再读取文件内容和版本摘要。标签页保存路径、编码、原始内容、当前内容、大小、行数、二进制标志、版本摘要、dirty 和 saving 状态。

### 3.2 分支历史

历史视图复用 `TreeCanvas`。它不是按单条消息绘制多个视觉卡片，而是将一个用户轮次及其后续 assistant/tool 条目聚合为一个 `ConversationRound`：

- 同一轮的用户消息、Agent 回复和工具细节归属一张语义卡；
- 同层兄弟 Lane 的轮次按共同 `round.depth` 横向对齐；
- `x = laneIndex × 228`、`y = round.depth × 136`；
- 工具调用不作为独立树节点，折叠在 `TreeNodeDetailPanel`；
- 点击轮次打开详情，路径高亮由 `parent` 链计算，不使用 `Entry.lane` 判断祖先关系。

### 3.3 源代码管理

`SourceControlPanel` 面向当前 Lane 提供：

- Git 启用状态、托管分支、Worktree、HEAD、同步状态和待保存文件数；
- 文件状态刷新、选中文件的 stage/unstage；
- 已暂存文件的提交；
- 当前 Lane 的检查点、恢复、丢弃、发布、归档/恢复和代码集成入口（由 `LaneCodeManagerModal` 承载）；
- 进入对比抽屉查看两个 Lane 的文件清单和逐文件 Diff。

非 Git 工作区显示降级说明，不能把对话 Lane 伪装成有代码隔离能力的 Git 分支。

### 3.4 搜索

搜索视图请求当前 Lane 工作区的独立搜索接口，同时匹配文件名和文本内容。支持当前目录范围、大小写敏感和结果数量限制；服务端忽略 `.git`、依赖目录、构建产物、缓存目录等常见目录，跳过二进制和超过 512 KB 的单文件。结果可直接打开编辑器标签页。

### 3.5 编辑器

当前编辑器是受控文本编辑区，不是完整语言服务 IDE。已实现：

- 多标签页打开、切换和关闭；
- 文本内容编辑和 dirty 标志；
- 显示编码、文本/二进制状态和文件路径；
- 通过保存按钮写回当前 Lane 文件；
- 保存中、错误和外部修改冲突反馈。

保存接口只允许修改工作区内已有的文本文件，不允许通过编辑器新建文件、修改 `.git` 元数据或保存二进制文件；单文件上限为 1 MB。读取文件时返回 SHA-256 版本摘要，保存携带 `expected_revision`，文件被外部修改时返回 409，前端要求重新加载后再保存。

Agent 通过 `write_file`/`edit_file` 产生的修改仍走独立的文件审查卡片，不会自动混入编辑器的 dirty 状态。

### 3.6 终端

终端是当前 Lane 的持续双向会话，不复用一次性 Agent `bash` 工具结果。前端通过当前 Session WebSocket 发送终端控制消息，后端创建受工作区约束的交互式进程：Windows 优先使用 WSL Bash，WSL 不可用时使用 PowerShell；非 Windows 使用 `$SHELL` 或 Bash。

当前支持打开、输入、输出、调整尺寸消息、发送中断/终止信号和关闭。终端实例带有 `terminal_id` 与 Lane，打开时拒绝与当前 Lane 不一致的请求；输入前再次经过 bash 权限和命令黑名单检查。断开连接或关闭终端时会终止子进程并清理输出任务。

终端当前状态包括 `closed`、`connecting`、`ready`、`running`、`exited` 和 `error`。输出只保留前端最近 200000 个字符；当前没有多终端标签、终端历史持久化、完整 PTY 尺寸传递或远程终端能力。

## 四、对话区保留能力

右侧 `ConversationPanel` 不因工作台改造而降级，继续负责：

- 用户消息和 Agent 流式回复；
- 工具调用卡片、结果和错误；
- 子 Agent 进度与结论；
- 权限确认；
- 运行状态、运行错误和重连提示；
- 记忆预算与手动上下文压缩；
- 文件修改审查、统一 Diff 和逐条接受/拒绝；
- 中断当前 Run 和提交下一条消息。

提交消息时先插入 `local-user-*` 临时用户气泡，再发送 WebSocket `send_message`，收到后端真实 Entry ID 后替换临时 ID。这样网络或 Agent 延迟不会让用户看不到已提交的消息。

文件审查是独立于工具卡片的前端状态：审查卡片在 Run 完成、Lane 切换或同一 Session 快照同步后仍保留；接受单条只移除对应审查；发送下一条消息或切换 Workspace/Session 时清空。服务端接受/拒绝前会重新校验文件当前版本，避免误覆盖后续修改。

## 五、前端状态模型

Zustand Store 将持久快照、实时运行态和纯界面状态分开：

| 类别 | 典型字段 |
|---|---|
| Session 快照 | `sessionId`、`sessionTitle`、`workspaceId`、`workspace`、`currentLane`、`lanes`、`entries` |
| Agent 运行态 | `agentState`、`isRunning`、`messages`、`toolCalls`、`subagents`、`permissionRequest` |
| 历史联动 | `selectedNodeId`、`showNodeDetail`、`highlightedPaths` |
| 工作台 | `activeWorkbenchView`、侧栏/对话宽度、`editorTabs`、`activeEditorPath` |
| 终端 | `terminalOpen`、高度、`terminalSessionId`、状态、输出和错误 |
| 独立审查 | `fileReviews` |

`setSession` 根据 Session ID 和 Lane 是否变化清理临时消息、工具调用、子 Agent、权限请求、编辑器标签和终端状态；同一 Session 的 Lane 切换保留会话数据但重置当前 Lane 相关运行视图。

## 六、通信契约

### 6.1 初始化顺序

进入 Session 后先由 `GET /api/sessions/{session_id}` 获取完整快照，再建立 `/ws/{session_id}`。WebSocket 建连成功后再次同步快照，处理建连期间可能发生的事件。连接断开后每 3 秒自动重连，并显示连接横幅。

### 6.2 REST 能力

工作台使用的主要接口如下：

| 区域 | 接口 |
|---|---|
| 文件 | `GET /sessions/{id}/workspace/files`、`GET/POST /sessions/{id}/workspace/file`、`GET /sessions/{id}/workspace/search` |
| 文件审查 | `POST /sessions/{id}/file-reviews/{review_id}/accept` 或 `reject`，以及批量接口 |
| Lane/Git | `GET /sessions/{id}/lanes/{lane}/status`、`/git/status`、`/git/diff`、stage、unstage、commit、checkpoint、restore、discard、publish、integrate |
| 会话 | `GET/PATCH /sessions/{id}`、`POST /sessions/{id}/compact` |
| 权限 | `GET/PUT /sessions/{id}/permissions/gate`、审计接口 |

### 6.3 WebSocket 事件

所有服务端事件统一为 `{ "type": string, "data": object }`。核心事件分组：

| 分组 | 事件 |
|---|---|
| Run 生命周期 | `run_started`、`run_completed`、`run_error`、`run_interrupt_requested`、`run_interrupt_rejected` |
| Agent 流式 | `context_loaded`、`message_start`、`text_delta`、`message_end`、`llm_request`、`llm_response`、`status_update` |
| 工具与权限 | `tool_call_start`、`tool_call_end`、`permission_request`、`permission_resolved` |
| 历史与 Lane | `node_added`、`lane_created`、`lane_switched`、`lane_renamed`、`lane_deleted` |
| 代码状态 | `lane_checkpoint_created`、`lane_code_integrated`、文件修改审查相关事件 |
| 记忆与标题 | `compaction_completed`、`compaction_failed`、`session_title_updated` |
| 子 Agent | `subagent_started`、`subagent_progress`、`subagent_done` |
| 终端 | `terminal_ready`、`terminal_output`、`terminal_exit`、`terminal_resized`、`terminal_closed`、`terminal_error` |

客户端发送的主要消息是 `send_message`、`permission_response`、`interrupt_run`、`terminal_open`、`terminal_input`、`terminal_signal` 和 `terminal_close`。

## 七、当前边界

- 没有独立的通用文件新建、重命名和删除编辑器操作。
- 没有语言服务器、语法高亮、诊断、补全、搜索结果行定位和多文件替换。
- Source Control 不是完整 Git 客户端，不提供远程推送、rebase、cherry-pick 或冲突编辑器。
- 终端不提供跨浏览器共享、持久化历史和多实例管理。
- 移动端响应式布局、布局跨刷新持久化和独立日志查询 UI 不属于当前实现。

## 八、实现对应

| 代码 | 职责 |
|---|---|
| `web-ui/src/components/Workspace.tsx` | 工作台整体布局和尺寸拖动 |
| `web-ui/src/components/workbench/ActivityBar.tsx` | 活动栏视图切换和终端开关 |
| `web-ui/src/components/workbench/WorkbenchPanels.tsx` | 资源管理器、编辑器、源代码管理、搜索和终端 |
| `web-ui/src/components/conversation/ConversationPanel.tsx` | 对话和运行控制 |
| `web-ui/src/hooks/useWebSocket.ts` | 快照同步、事件分发和终端消息 |
| `web-ui/src/store/index.ts` | 全局状态和生命周期清理 |
| `backend/src/api/workspace_files.py` | 文件浏览、读取、搜索、安全保存和回滚 |
| `backend/src/api/terminal.py` / `backend/src/api/ws.py` | 终端进程与双向事件 |

