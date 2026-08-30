# CodeMate 测试报告

**报告日期**：2026-08-30  
**测试环境**：Windows，Python 3.12.4，pytest 9.1.1，Node.js/npm 项目  
**报告范围**：后端核心逻辑、后端集成契约、前端状态与关键交互、前端构建

## 1. 执行结论

本轮新增并执行了后端集成测试和前端自动化测试，同时修复了测试过程中发现的两个高风险问题：

1. Windows 下 `BashTool` 使用 Unix 风格命令执行方式，导致实际命令执行失败或行为不一致。现已按当前平台调用 `cmd.exe`，并继续保持 `shell=False`。
2. WebSocket 消息链路重复发送 `run_completed` 事件，可能导致前端重复收尾、状态异常甚至白屏。现已将该事件收敛为 Agent 单点发送。

测试结果：

| 测试范围 | 结果 | 覆盖率 |
|---|---:|---:|
| 后端 pytest | **85 passed**，11.90s | **77%**（`src`） |
| 前端 Vitest | **10 passed**，8 个测试文件 | **69.31% statements** |
| 前端生产构建 | **通过** | 不适用 |

当前结果表明核心后端逻辑和关键前端交互已具备可重复验证能力，但系统还不应仅凭本轮结果宣称完全稳定。真实 LLM、真实浏览器环境、多客户端并发和长时间运行仍需要继续补充测试。

## 2. 本轮新增测试结构

### 后端

- `backend/tests/conftest.py`
  - 统一测试导入路径。
- `backend/tests/integration/test_runtime_contracts.py`
  - WebSocket `run_completed` 事件只发送一次。
  - Windows/当前平台 Bash 命令可执行。
  - Shell 链式命令会被拒绝。
  - 树形记忆与 Lane 在重新加载后仍可恢复并执行对比。

### 前端

- `web-ui/vitest.config.ts`
- `web-ui/src/test/setup.ts`
- `web-ui/src/test/test-utils.ts`
- `web-ui/src/__tests__/store.test.ts`
- `web-ui/src/__tests__/useWebSocket.test.tsx`
- `web-ui/src/__tests__/SessionPicker.test.tsx`
- `web-ui/src/__tests__/PermissionModal.test.tsx`
- `web-ui/src/__tests__/CreateLaneModal.test.tsx`
- `web-ui/src/__tests__/CompareDrawer.test.tsx`
- `web-ui/src/__tests__/ConversationPanel.test.tsx`
- `web-ui/src/__tests__/Toolbar.test.tsx`

覆盖的重点包括：

- 树形记忆状态更新、节点与 Lane 状态管理。
- Lane 创建、基于指定节点创建、切换、对比分析。
- WebSocket 连接、快照恢复、事件分发和消息序列化。
- Wei-UI 消息发送、历史消息展示、权限确认和系统信息反馈。
- Session 创建、加载和切换。

## 3. 实际执行命令

### 后端

在 `backend` 目录执行：

```powershell
pytest -q
```

结果：

```text
85 passed in 11.90s
```

覆盖率命令：

```powershell
pytest --cov=src `
  --cov-report=term-missing `
  --cov-report=json:tests\report\coverage.json `
  --cov-report=html:tests\report\htmlcov
```

结果：

```text
TOTAL coverage: 77%
```

机器可读覆盖率数据：

- `backend/tests/report/coverage.json`
- `backend/tests/report/htmlcov/`

### 前端

在 `web-ui` 目录执行：

```powershell
npm run test
npm run coverage
npm run build
```

结果：

```text
Vitest: 8 files passed, 10 tests passed
Statements: 69.31%
Branches: 50.22%
Functions: 75%
Lines: 70.27%
Build: passed
```

关键模块覆盖率：

| 模块 | Statements |
|---|---:|
| `ConversationPanel.tsx` | 91.66% |
| `CompareDrawer.tsx` | 82.75% |
| `CreateLaneModal.tsx` | 75% |
| `PermissionModal.tsx` | 73.33% |
| `Toolbar.tsx` | 75% |
| `useWebSocket.ts` | 67.96% |
| `store/index.ts` | 65.90% |

## 4. 已修复问题

### 4.1 BashTool 跨平台执行问题

文件：`backend/src/tools/exec_tool.py`

修复内容：

- Windows 下通过 `cmd.exe /d /s /c` 执行命令。
- 继续使用 `subprocess.run(..., shell=False)`。
- 增加对 `&` 等 Shell 链式元字符的拒绝。
- 补充命令失败和超时的清晰错误返回。

对应测试：

- `test_builtin_commands_work_on_current_platform`
- `test_shell_chaining_is_rejected`

### 4.2 WebSocket 完成事件重复发送

文件：`backend/src/api/ws.py`

修复内容：

- 删除 WebSocket 层重复发送的 `run_completed`。
- 保持 Agent 作为运行完成事件的唯一发送方。

对应测试：

- `test_send_message_emits_run_completed_once`

## 5. 风险与未完成项

以下项目本轮尚未作为完整自动化门禁执行，因此仍是后续稳定性重点：

1. 真实 LLM/API 集成测试：当前主要使用 Mock，尚未验证外部模型异常、超时、限流和响应格式漂移。
2. 浏览器级端到端测试：本轮完成了前端组件和 Hook 测试，但尚未覆盖启动真实前后端服务后，在真实浏览器中完成“创建 Session → 发送消息 → 推送事件 → 查看历史 → 创建/切换/对比 Lane”的完整链路。
3. 多客户端并发和长连接稳定性：尚未建立并发连接、断线重连、重复连接和长时间消息推送压力测试。
4. 前端分支覆盖率为 50.22%，后端总体覆盖率为 77%；异常路径、重连路径和复杂 UI 状态仍需提高覆盖。

## 6. 后续验收建议

建议将以下条件作为后续合并或发布门槛：

- 后端所有 pytest 用例通过。
- 后端覆盖率不低于当前基线 77%，新增核心模块不得明显下降。
- 前端 Vitest 用例全部通过，生产构建通过。
- WebSocket 完成事件在单次运行中只能出现一次。
- Lane 创建、切换、对比在刷新/重新加载后状态一致。
- 消息推送失败、断线、权限拒绝和工具执行失败时，页面保持可交互，不出现白屏。
- 补充真实浏览器 E2E 后，再进行一次完整回归。

**报告结论**：本轮测试基础设施和核心回归用例已建立，已发现并修复跨平台命令执行和 WebSocket 重复事件两个问题。当前测试结果通过，但在真实浏览器、真实模型服务及并发稳定性验证完成前，仍应将系统视为测试阶段版本。
