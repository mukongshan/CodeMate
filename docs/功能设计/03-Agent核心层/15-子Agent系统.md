# 15 - 子 Agent 系统

> 当前实现基线：2026-09-02
>
> 子 Agent 是主 Agent 的只读侦察能力：它使用独立临时上下文调查跨文件问题，最终只把结论摘要作为一次工具结果交还父 Agent。

## 一、定位与边界

子 Agent 适合跨文件追踪、影响范围分析、风险排查、测试失败定位和只读代码审查，不适合简单单文件读取、写入、编辑或命令执行。当前实现明确限制：

- 最大派生深度为 1，子 Agent 不能继续派生子 Agent；
- 只注册 `read_file`、`list_directory`、`glob`、`grep` 等只读工具；
- 单次最多 20 个工具调用轮数，默认 8 轮；
- 单次 wall-clock 超时为 120 秒；
- 同一 `DelegateTaskTool` 实例最多并发 3 个子 Agent；
- 子 Agent 不写入父 Session 的 Entry、Lane 或 Git。

## 二、调用流程

```text
父 Agent tool_use: delegate_task
        │
        ├─ 权限检查（delegate_task 为 SAFE）
        ├─ 校验 task / max_steps / depth
        ├─ 创建 EphemeralMessageProvider
        ├─ 构造只读 ToolRegistry 和子 Agent
        ├─ 最多 3 个并发、单任务 120 秒超时
        ├─ 推送 started / progress / done
        └─ 返回一个 ToolResult 给父 Agent
```

父 Agent 对单个委托调用是同步等待的；如果同一轮 LLM 返回多个独立 `delegate_task`，主 Agent 的工具执行层可以并发执行它们。每个调用都有独立的 `subagent_id`，异常只影响对应调用，不取消其他兄弟任务。

## 三、上下文隔离

子 Agent 使用 `EphemeralMessageProvider`，初始内容由系统提示和任务描述组成。它不会读取父 Agent 的历史树，也不会把中间 assistant/tool message 追加到 `SessionStorage`。子 Agent 使用父 Agent 当前 Lane 的工作目录和 LLM 客户端，但只读工具集合由 `ToolRegistry.readonly()` 单独创建。

权限管理器与父 Agent 共用，子 Agent 没有权限豁免；因为只读工具默认为 SAFE，正常调查不会弹出写入或命令确认。

## 四、步数、超时和收尾

`max_steps` 由工具参数传入，再限制为 1–20。步数耗尽且没有最终文本时，系统追加一次 `tool_choice=none` 的收尾请求，让子 Agent 自己总结，不直接截断半句话。超时返回错误 ToolResult，并发送 `subagent_done`；父 Agent 可以依据错误继续修正或改为当前层级调查。

摘要长度 2000 字是软提示，不是硬截断。系统保留完整结论，前端详情中记录 `summary_length` 和 `summary_over_limit`，避免按字符数静默丢失证据。

## 五、双通道结果

子 Agent 完成后生成两个通道：

| 通道 | 内容 | 去向 |
|---|---|---|
| `content` | 带 `completed`、`partial` 或 `error` 状态的结论摘要 | 父 Agent 的 `tool_result`，会占用上下文 |
| `details` | 工具调用次数、访问文件、耗时、token、摘要长度和错误 | 前端状态卡和日志，不进入父 Agent 上下文 |

这样父 Agent 只看到可用于决策的结论，用户仍能看到子 Agent 做了多少调查以及是否超时。

## 六、实时事件

当前事件顺序为：

1. `subagent_started`：任务、`subagent_id`、最大步数和 pending 状态；
2. `subagent_progress`：每次只读工具调用的步数、工具名和提示；
3. `subagent_done`：最终状态、摘要和详情。

子 Agent 的内部 `status_update`、`text_delta` 和工具细节不会原样进入父 Session WebSocket 事件流；只通过上述聚合事件展示。父 Agent 中的 `tool_call_start`/`tool_call_end` 仍照常显示 `delegate_task` 这一层工具调用。

## 七、父树写入语义

子 Agent 的最终 `ToolResult` 由父 Agent 主循环按普通工具结果处理。一次 assistant 回复中多个工具调用的结果，仍然在所有工具完成后打包为一条 role=tool Entry；不会为每个子 Agent 创建独立的父树分支，也不会把子 Agent 的中间消息写入父树。

## 八、前端展示

`SubagentPanel` 根据 `subagent_id` 渲染独立状态卡，展示：

- 任务描述和运行状态；
- 当前步数与最大步数；
- 最近调用的只读工具；
- 最终摘要、错误和调查统计；
- `partial`、`timeout`、`cancelled` 等非完整状态。

子 Agent 卡片属于当前运行视图，不是独立 Session，不提供单独的历史列表、恢复、重放或 Lane 切换入口。

## 九、错误和取消

- 空任务直接返回错误 ToolResult；
- 深度达到上限时拒绝递归；
- 单个子 Agent 异常被转换为错误结果，不让父 Run 直接崩溃；
- 父 Agent 取消时，子 Agent 任务随之取消并发送 `cancelled`；
- 事件推送失败只记录日志，不改变子 Agent 的最终结果；
- 子 Agent 只读工具失败会返回给子 Agent 自己修正，最终再把摘要交给父 Agent。

## 十、实现对应

| 代码 | 职责 |
|---|---|
| `backend/src/tools/subagent_tool.py` | `DelegateTaskTool`、并发上限、超时、收尾和双通道结果 |
| `backend/src/agent/loop.py` | 主 Agent 工具并发、结果打包和父树写入 |
| `backend/src/agent/providers.py` | `EphemeralMessageProvider` |
| `backend/src/tools/registry.py` | 主工具集和只读工具集 |
| `web-ui/src/components/conversation/SubagentPanel.tsx` | 前端状态卡 |
| `backend/tests/test_subagent.py` | 深度、超时、并发和结果行为 |

## 十一、后续不属于当前实现

background/continuable 子 Agent、持久化子会话、递归子 Agent、远程子 Agent、子 Agent 独立管理台和基于任务图的复杂编排均未实现。新增这些能力时仍需保留父树隔离和双通道结果边界。
