# 06 - LLM 接口层

> 基于当前源码的实现说明，基线日期：2026-09-02。

## 一、职责与边界

LLM 接口层把 Agent 的统一消息模型转换为 OpenAI Chat Completions 兼容请求，并把 Provider 的流式响应归一化为文本、工具调用、完成和错误事件。

它负责 Provider 适配、流式工具参数拼接、错误分类和指数退避重试；它不负责对话树持久化、上下文裁剪、权限判断或工具执行。

当前只支持两种 Provider 名称：`openai` 和 `deepseek`。其中 DeepSeek 使用 OpenAI 兼容接口；OpenAI Provider 也可以通过 `base_url` 连接兼容服务，但配置层不会为第三种 Provider 单独注册实现。

## 二、调用链

```text
Agent
  ↓ list[Message] + tool schemas
LLMClient
  ↓ 重试、错误归一化
OpenAIProvider / DeepSeekProvider
  ↓ OpenAI Chat Completions 流式请求
StreamBuffer
  ↓ 拼接分片工具参数
TextDeltaEvent / ToolCallEvent / DoneEvent / ErrorEvent
```

上下文由 `TreeMessageProvider` 从 Entry 树投影为 `Message`；该转换发生在 Agent 层，不由 Provider 读取 JSONL。`Message` 与存储层 `Entry` 是两套类型：Entry 保存 `parent`、`lane`、`seq` 等事实字段，Message 只保存模型协议字段。

## 三、统一消息模型

`backend/src/llm/events.py` 定义当前协议类型：

| 类型 | 关键字段 | 用途 |
|---|---|---|
| `Message` | `role`、`content`、`tool_calls`、`tool_call_id`、`reasoning_content` | Provider 请求消息 |
| `ToolCall` | `id`、`name`、`arguments` | assistant 工具调用 |
| `TextDeltaEvent` | `text` | 流式文本增量 |
| `ToolCallEvent` | `id`、`name`、`arguments` | 参数已拼接完成的工具调用 |
| `DoneEvent` | `stop_reason`、`usage`、`reasoning_content`、`partial_tool_calls` | 本轮响应结束 |
| `ErrorEvent` | `message`、`retryable` | Provider 流式错误 |

消息序列化遵守 OpenAI 兼容协议：

- assistant 只有工具调用而没有文本时，`content` 明确为 `null`。
- tool 消息必须携带 `tool_call_id`，内容为空时使用空字符串。
- 工具调用的 `arguments` 在协议中编码为 JSON 字符串，而不是对象。
- DeepSeek 请求允许携带 `reasoning_content`；其他 Provider 默认不发送该字段。

## 四、Provider 实现

### 4.1 OpenAI Provider

`OpenAIProvider` 使用 `openai.AsyncOpenAI`，开启流式请求并设置 `stream_options.include_usage`，默认模型为 `gpt-4o-mini`、温度为 `0.7`、最大输出 Token 为 `2000`。配置了 `base_url` 时，客户端使用该地址作为 OpenAI 兼容端点。

Provider 对每个 chunk 做以下处理：

1. 收集 usage 信息。
2. 发出文本增量事件。
3. 把工具调用的 id、名称和参数片段交给 `StreamBuffer`。
4. 读取 `finish_reason`。
5. 流结束后发出完整工具调用和 `DoneEvent`。

### 4.2 DeepSeek Provider

`DeepSeekProvider` 继承 `OpenAIProvider`，默认端点为 `https://api.deepseek.com`，默认模型为 `deepseek-chat`，最大输出 Token 默认值为 `4000`，并以 `name="deepseek"` 标识 Provider。

两者都要求 API Key；未配置时在构造 Provider 阶段抛出 `LLMAPIError`，不会启动一次无效请求。

## 五、流式解析与工具调用

OpenAI 兼容接口可能把同一次工具调用的名称和 JSON 参数拆成多个 chunk。`StreamBuffer` 按调用索引累积片段，只有 JSON 参数完整时才生成 `ToolCallEvent`。

如果流结束时仍有不完整工具调用，Provider 不伪造可执行的参数，而是在 `DoneEvent.partial_tool_calls` 标记该情况。Agent 主循环据此生成补救提示或结束当前轮次，避免把半截 JSON 交给工具。

## 六、LLMClient 与重试

`LLMClient` 对上层隐藏 Provider 的流式错误细节，并使用 `RetryPolicy` 做指数退避：默认最多重试 3 次，等待时间为 `1s`、`2s`、`4s`，上限 `60s`。

重试有两个重要限制：

- 只有 Provider 标记为 `retryable` 且此前尚未产生文本时才重试。
- 已经向前端产生文本后再次失败，不重放请求，直接抛出 `LLMAPIError`，避免 UI 文本重复。

可重试错误包括限流、超时、连接错误、服务端 5xx 和服务不可用等；不可重试错误会立即转换为带 `code`、`provider`、`retryable` 和建议的 `LLMAPIError`。

当前不实现响应缓存。原因是 Agent 上下文持续变化，重复请求命中率低，缓存会引入失效和敏感上下文管理成本。

## 七、配置

配置来自 `LLMConfig` 和环境变量：

| 配置 | 环境变量 | 当前默认值 |
|---|---|---|
| Provider | `LLM_PROVIDER` | `deepseek` |
| API Key | `LLM_API_KEY` | 无默认值，必须提供 |
| Base URL | `LLM_BASE_URL` | 按 Provider 选择默认地址 |
| 模型 | `LLM_MODEL` | DeepSeek 为 `deepseek-chat`，OpenAI 为 `gpt-4o-mini` |
| 温度 | `LLM_TEMPERATURE` | `0.7` |
| 最大输出 Token | `LLM_MAX_TOKENS` | `2000` |
| 最大重试次数 | `LLM_MAX_RETRIES` | `3` |
| 重试基础延迟 | `LLM_RETRY_BASE_DELAY` | `1.0` 秒 |
| 重试最大延迟 | `LLM_RETRY_MAX_DELAY` | `60.0` 秒 |

应用配置会把这些字段转换成 Provider 参数和 `RetryPolicy`。未知 Provider 直接返回不可重试的配置错误。

## 八、与 Agent 主循环的关系

每轮 Agent 执行时：

1. Agent 从当前 Lane 的树形上下文构造 `Message` 列表。
2. Agent 把当前可用工具 schema 传给 `LLMClient.chat()`。
3. 文本事件转发为前端 `text_delta`，工具调用事件进入权限检查和工具执行。
4. 工具结果作为 `role=tool` 消息进入下一轮上下文。
5. `DoneEvent.stop_reason` 决定继续工具迭代、正常结束或处理长度/截断情况。

LLM 接口层只提供模型响应，不决定一次 Run 的最终状态；Run 的终止条件、工具并行和错误提升由 `backend/src/agent/loop.py` 负责。

## 九、错误处理

Provider 网络或 API 异常先转换为 `ErrorEvent`。`LLMClient` 根据 `retryable` 判断是否重试；最终失败时抛出 `LLMAPIError`，由 Agent 主循环和 WebSocket 层分别转换为 `run_error` 与前端错误状态。

API Key 缺失、Provider 名称不支持、模型配置错误属于配置或请求初始化错误，不应当通过无限重试掩盖。

## 十、实现映射

| 代码位置 | 职责 |
|---|---|
| `backend/src/llm/events.py` | Message、ToolCall 与流式事件类型 |
| `backend/src/llm/providers.py` | OpenAI/DeepSeek Provider 和 chunk 解析 |
| `backend/src/llm/stream_buffer.py` | 工具调用分片累积与 JSON 完整性判断 |
| `backend/src/llm/client.py` | 统一入口、指数退避和错误归一化 |
| `backend/src/agent/providers.py` | Entry 树到 Message 上下文的投影和序列修复 |
| `backend/src/agent/loop.py` | Agent 轮次、工具调用和终止状态 |
| `backend/src/config.py` | 环境变量与 Provider 默认配置 |

## 十一、当前限制

- 只注册 `openai` 和 `deepseek` 两种 Provider 名称。
- 不提供响应缓存、离线模型推理、模型路由和多 Provider 自动降级。
- 只使用 Chat Completions 兼容协议，不单独适配其他厂商原生协议。
- 重试发生在尚未产生文本的请求阶段；部分输出后的自动续写由上层 Agent 逻辑决定。
