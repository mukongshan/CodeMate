# 02 - API 设计

> HTTP REST 端点 + WebSocket 事件契约的具体字段定义。交互流程与前端消费方式见 [07-Web-UI设计](../系统设计/05-Web-UI层/07-Web-UI设计.md)，本篇只定协议。

---

## 一、总体划分：为什么 REST 和 WebSocket 分工

对齐 [01-系统架构概览](../系统设计/01-系统架构概览.md) 2.2 节的通信层职责：

- **HTTP REST**：Session/Lane 的增删查这类"一次请求-一次响应"的管理操作，天然适合 REST 语义，也方便用 `curl`/Swagger UI 单独调试。
- **WebSocket**：Agent 运行时的所有流式事件（文本增量、工具调用、权限确认、子 Agent 进度）——这些是服务端主动推送、且顺序敏感的事件流，REST 轮询做不到实时性，必须用长连接。

`send_message`（用户发消息触发一次 Run）本身也走 WebSocket 而不是 REST POST，因为它的响应不是一次性的,而是一连串流式事件——用 REST 表达这个语义会变成"POST 后再单独开一个 SSE/WS 连接接结果"的两段式设计,不如直接把请求也放进同一条 WebSocket 连接里干净。

---

## 二、REST API

### 2.1 Session 管理

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/sessions` | 创建新 session,返回 `session_id` |
| `GET` | `/api/sessions` | 列出所有 session（本地单用户场景,仅供切换历史会话用） |
| `GET` | `/api/sessions/{session_id}` | 获取 session 详情：全部 Entry（用于前端首次加载渲染树） |
| `DELETE` | `/api/sessions/{session_id}` | 删除 session（连同其 JSONL 文件） |

**`GET /api/sessions/{session_id}` 响应体**：

```json
{
  "session_id": "sess_abc123",
  "entries": [
    {"id": "e1", "parent": null, "lane": "main", "seq": 1, "role": "user", "content": "优化函数", "timestamp": 1756425600.0}
  ],
  "lanes": [
    {"lane": "main", "leaf_id": "e4", "seq": 3, "created_from": null, "description": "主分支"}
  ]
}
```

前端拿到这个响应后在本地重建 `entries`/`children_index`/`lane_index`（复用 [12-存储层设计](../系统设计/02-数据与存储层/12-存储层设计.md) 第四节的同一套索引算法思路,只是搬到浏览器端做树形渲染,不重新发请求查询单个节点）。

### 2.2 Lane 管理

对应 [03-Lane分支管理系统](../系统设计/02-数据与存储层/03-Lane分支管理系统.md) 第三、四节。

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/sessions/{session_id}/lanes` | 创建分支 |
| `GET` | `/api/sessions/{session_id}/lanes` | 列出所有分支及其状态 |
| `POST` | `/api/sessions/{session_id}/lanes/{lane}/switch` | 切换当前活跃分支 |
| `DELETE` | `/api/sessions/{session_id}/lanes/{lane}` | 删除分支（不删节点,只删指针;保护 `main` 和当前活跃分支,见 [03 号文档](../系统设计/02-数据与存储层/03-Lane分支管理系统.md) 3.4 节） |
| `GET` | `/api/sessions/{session_id}/lanes/compare?a={lane_a}&b={lane_b}` | 对比两个分支 |

**`POST /lanes` 请求体**：

```json
{"name": "algo-approach", "from_id": "e2", "description": "尝试算法优化方案"}
```

**`GET /lanes/compare` 响应体**（直接对应 [03 号文档](../系统设计/02-数据与存储层/03-Lane分支管理系统.md) 4.1 节 `compare_lanes` 的返回结构）：

```json
{
  "common_ancestor": "e2",
  "lane_a_diff": ["e3", "e4"],
  "lane_b_diff": ["e5", "e6"],
  "identical": false
}
```

`identical: true` 对应 [03 号文档](../系统设计/02-数据与存储层/03-Lane分支管理系统.md) 1.5.4 节"两个 Lane 指向同一叶子"的边界情况,此时 `*_diff` 均为空列表,前端据此展示"两个分支尚无差异"而不是空白对比栏（见 [07 号文档](../系统设计/05-Web-UI层/07-Web-UI设计.md) 7.2 节）。

### 2.3 权限配置

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/sessions/{session_id}/permissions/audit` | 拉取本 session 的权限决策审计记录（对应 [09 号文档](../系统设计/04-支撑模块/09-权限控制系统.md) 第七节） |

---

## 三、WebSocket 事件契约

端点：`WS /ws/{session_id}`。这套契约直接落地 [07-Web-UI设计](../系统设计/05-Web-UI层/07-Web-UI设计.md) 第六节定的事件表,本篇补充每个事件的完整字段类型和 Pydantic/TypeScript 双端对齐方式。

### 3.1 客户端 → 服务端

**`send_message`**（用户发送新消息,触发一次 Run）：

```json
{"type": "send_message", "content": "优化这个函数", "lane": "main"}
```

**`permission_response`**（响应权限确认请求）：

```json
{"type": "permission_response", "request_id": "perm_001", "action": "allow_once"}
```

`action` 取值：`"allow_once" | "allow_always" | "deny"`,对应 [09-权限控制系统](../系统设计/04-支撑模块/09-权限控制系统.md) 3.1 节 `_ask_user` 的三种响应。

**`interrupt_run`**（用户中断当前执行,P2 功能,见 [03-Lane分支管理系统](../系统设计/02-数据与存储层/03-Lane分支管理系统.md) 7.3 节"不做的部分"——先在协议里预留字段,不在首版实现处理逻辑）：

```json
{"type": "interrupt_run", "run_id": "run_abc123"}
```

### 3.2 服务端 → 客户端

| 事件 | 字段 | 说明 |
|---|---|---|
| `node_added` | `id, parent, lane, role, content, timestamp` | 树上新增一个 Entry,对应 [02-树形对话历史系统](../系统设计/02-数据与存储层/02-树形对话历史系统.md) |
| `text_delta` | `message_id, text` | assistant 消息流式追加 |
| `tool_call_start` | `call_id, tool_name, args` | 工具开始执行 |
| `tool_call_end` | `call_id, status, result` | `status: "success" \| "error"` |
| `subagent_started` | `subagent_id, parent_call_id, task` | 子 Agent 开始,见 [15-子Agent系统](../系统设计/03-Agent核心层/15-子Agent系统.md) |
| `subagent_progress` | `subagent_id, step, max_steps` | 子 Agent 内循环进度 |
| `subagent_done` | `subagent_id, status, content, details` | 双通道结果,`status: "completed" \| "partial" \| "error"` |
| `lane_created` | `lane, from_id` | 新建分支 |
| `lane_switched` | `lane, leaf_id` | 当前活跃分支变化 |
| `permission_request` | `request_id, tool_name, args, risk_level, warning` | 需要用户确认,`risk_level: "low" \| "medium" \| "high"` |
| `run_started` | `run_id, lane, user_message_id` | 一次 Run 开始 |
| `run_completed` | `run_id, status, iterations, total_tokens, duration` | 一次 Run 结束 |
| `run_error` | `run_id, error, retryable` | 主循环级错误 |
| `status_update` | `state, current_operation, current_lane` | Agent 状态面板数据,对应 [11-日志与可观测性](../系统设计/04-支撑模块/11-日志与可观测性.md) 六节 |

**信封格式**：所有服务端事件统一包一层 `{"type": "<事件名>", "data": {...}}`,不是每个事件类型各自的裸 JSON——这样前端只需要一个 `switch(msg.type)` 分发,不用对每种消息形状做鸭子类型判断。

```json
{"type": "text_delta", "data": {"message_id": "e5", "text": "我建议"}}
```

### 3.3 Pydantic 端的 Schema 定义

```python
# src/api/schemas.py
from pydantic import BaseModel
from typing import Literal, Optional, Any

class WSEnvelope(BaseModel):
    type: str
    data: dict[str, Any]

class TextDeltaData(BaseModel):
    message_id: str
    text: str

class ToolCallEndData(BaseModel):
    call_id: str
    status: Literal["success", "error"]
    result: str

class PermissionRequestData(BaseModel):
    request_id: str
    tool_name: str
    args: dict
    risk_level: Literal["low", "medium", "high"]
    warning: str

class SubagentDoneData(BaseModel):
    subagent_id: str
    status: Literal["completed", "partial", "error"]
    content: str
    details: dict
```

每种 `data` 都有独立的 Pydantic 模型,只用于服务端内部构造 payload 时的类型检查;实际下发走 `WSEnvelope(type=..., data=model.model_dump()).model_dump_json()`,不要求前端引入同一套 schema（前端用手写的 TypeScript interface 对齐即可,详见 [07 号文档](../系统设计/05-Web-UI层/07-Web-UI设计.md) 第六节的表格）。

---

## 四、错误响应格式

REST 端点的错误响应统一格式,对应 [08-错误处理机制](../系统设计/04-支撑模块/08-错误处理机制.md) 的 `AgentError` 体系在 HTTP 层的落地：

```json
{
  "error": {
    "code": "LANE_NOT_FOUND",
    "message": "分支 'algo' 不存在",
    "suggestions": ["使用 GET /lanes 查看当前所有分支"]
  }
}
```

HTTP 状态码映射：

| AgentError 子类 | HTTP 状态码 |
|---|---|
| `ValidationError` | 400 |
| `PermissionDeniedError` | 403 |
| 资源不存在（session/lane not found） | 404 |
| `LLMAPIError`（不可重试） | 502 |
| `SystemError` | 500 |

WebSocket 侧的错误不走 HTTP 状态码,统一走 `run_error` 事件（第 3.2 节），字段里带 `retryable` 供前端决定是否展示"重试"按钮（对应 [07 号文档](../系统设计/05-Web-UI层/07-Web-UI设计.md) 8.2 节的两级错误反馈）。

---

## 五、鉴权与安全边界说明

当前设计目标是**单人本地 demo**,`main.py` 默认监听 `127.0.0.1`,不做用户登录/鉴权体系——这是范围内的主动简化,不是遗漏。如果这个后端被部署到非本机、可被网络访问的地址,必须在此基础上补一层鉴权（如固定 token 校验中间件),否则任何能访问该端口的人都可以让 Agent 执行文件写入和命令执行操作。这一点在 [00-总览与目录结构](00-总览与目录结构.md) 和 README 中都需要明确提示,不能被误解为"已经是安全的对外服务"。

---

**文档版本**: v0.1
**上次更新**: 2026-08-29
**关联文档**: [00-总览与目录结构](00-总览与目录结构.md)、[01-数据模型设计](01-数据模型设计.md)、[03-核心模块与类设计](03-核心模块与类设计.md)、[07-Web-UI设计](../系统设计/05-Web-UI层/07-Web-UI设计.md)
