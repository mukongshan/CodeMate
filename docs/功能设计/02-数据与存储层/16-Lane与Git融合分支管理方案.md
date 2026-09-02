# 16 - Lane 与 Git 融合分支管理方案

> 当前实现基线：2026-09-02
>
> 本文描述当前已实现的 Lane 代码隔离、检查点、发布和集成能力。它不把 CodeMate 描述成完整 Git 客户端。

## 一、核心关系

Lane 同时包含两个相互关联但不等价的指针：

| 指针 | 指向 | 作用 |
|---|---|---|
| 对话指针 | Entry `leaf_id` | 恢复当前方案的对话上下文 |
| 代码指针 | Git binding 的 Worktree/HEAD | 恢复当前方案的文件状态 |

一个 Lane 可以产生很多对话 Entry 而没有代码改动，也可以一次 Run 修改多个文件后只形成一个代码检查点。因此 Entry 与 commit 不是一一对应关系；检查点通过 `run_id`、`conversation_entry_id` 和变更文件建立关联。

## 二、仓库与工作目录

Session 初始化时，`GitLaneManager` 检测配置的 Workspace 是否为已有初始提交的 Git 仓库：

- Git 可用时，`main` Lane 使用用户源目录，其余 Lane 使用 CodeMate 管理的独立 Worktree；
- 托管分支使用 `codemate/<session-id>/<lane>` 命名空间；
- 托管 Worktree 根目录必须位于源仓库之外；
- Agent、子 Agent、文件工具、命令工具和终端均使用当前 Lane 的实际工作目录；
- 非 Git 工作区保留对话 Lane，但 `git` 能力返回 `enabled=false` 和降级原因。

用户源目录和 CodeMate 数据目录始终分离。Lane 删除、Session 删除和 Workspace 移除都不会递归删除用户源目录；已发布的普通分支也不会因托管 Lane 删除而自动删除。

## 三、检查点策略

### 3.1 自动检查点

成功 Run 结束后，系统先扫描当前 Lane Worktree 的变化。如果存在可保存的变更，就把 `run_id` 和对话 Entry 记录到 binding 的待处理状态中。满足以下任一条件时合并提交：

- 最近一次 Run 后空闲窗口已结束；
- 待处理时间达到最大年龄；
- 待处理 Run 数达到上限；
- 变更文件数达到上限。

自动检查点使用 CodeMate 专用提交身份和禁用用户 hooks 的提交参数，避免把内部恢复提交误当成用户正式提交。检查点状态会记录 `reason`、Run 状态、变更文件、前后 commit 和时间。

### 3.2 手动和选择性检查点

用户可以通过 Lane 检查点接口指定文件范围，或者允许处理默认阻断项。敏感文件、私钥、凭证、密钥后缀、疑似 API Key、超大文件、冲突和外部 ref 不一致会阻止或要求显式处理。

检查点只表示“代码状态已保存”，不表示测试通过、代码正确或已经发布。若仍有排除文件未提交，Lane 继续显示 dirty。

### 3.3 检查点与 Agent 结果解耦

Agent Run 的 `completed`/`error`/`aborted` 是执行结果；检查点是代码持久化结果。检查点创建失败时不回滚已经完成的 Agent 对话，也不把 Agent 成功改写成失败；前端应分别展示运行结果和代码保存状态。

## 四、Lane 代码操作

当前 SessionRuntime 和 REST 层支持：

| 操作 | 说明 |
|---|---|
| 状态 | 返回 Worktree、托管分支、HEAD、dirty、冲突、同步和待检查点信息 |
| Diff | 支持 Lane 或单文件差异，返回新增/修改/删除/重命名等文件状态 |
| 暂存/取消暂存/提交 | 作用于指定 Lane 的 Worktree，提交前要求路径位于该 Worktree |
| 恢复 | 按检查点恢复，默认检查当前版本，避免覆盖恢复后产生的新修改 |
| 丢弃 | 显式丢弃当前 Lane 未保存代码变更 |
| 发布 | 将 Lane 发布为普通本地分支，支持 `branch` 和 `squash` 模式 |
| 归档/恢复 | 保留 Lane 历史和必要元数据，控制是否继续出现在活动列表 |
| 集成 | 先预览，再按 `merge`、`ff` 或 `squash` 策略写入目标分支 |

所有操作前重新读取 Git 状态，不长期相信内存中的 HEAD 或 Worktree 状态。目标分支 dirty、来源未发布、分支不匹配或冲突时返回结构化错误，不静默覆盖。

## 五、创建与切换

### 5.1 创建 Lane

创建请求包含安全 slug、可选展示名、方案描述和名称来源。服务端校验 slug 为小写字母/数字加单个短横线，长度不超过 64；`main` 是保留名称。Git 启用时，系统在当前代码基线创建托管分支和 Worktree，再写入 LanePointer 与 Binding。

Lane 名称建议由独立 NamingService 生成，最多返回三个候选；候选不足时本地补齐。展示名不进入 Git 分支路径、命令或文件系统路径。

### 5.2 切换 Lane

切换会更新 Session 的当前 Lane、对话叶子、PermissionManager 工作目录和后续 Agent 构建上下文。Git 启用时确保目标 Worktree 可用；前端同时刷新历史、资源管理器、编辑器请求和 Source Control。

同一 Session 内不允许并行 Agent Run。切换、删除、压缩和代码结构操作在运行中会被阻止或按明确的内部调用规则执行。

## 六、对比与集成

对话对比由 Entry 的最近公共祖先计算，代码对比由 Git merge-base 和文件 diff 计算，两种基线可能不同，不能互相替代。两个 Lane 指向同一叶子或相同代码状态时，接口返回 `identical=true` 和空差异。

集成流程为：

1. 校验来源 Lane、已发布来源分支和目标分支；
2. 计算目标当前 HEAD、merge-base、文件变化和 dirty 状态；
3. 返回预览，等待用户确认策略；
4. 执行 `merge`、`ff` 或 `squash`；
5. 记录 `CodeIntegration`，成功后为目标状态生成 main 检查点，并推送 `lane_code_integrated`。

当前不提供交互式冲突编辑器；冲突和目标外部变化会保留结构化失败信息，交由用户在专业 Git 工具或终端处理。

## 七、持久化和恢复

每个 Session 的 `git/bindings.json` 保存 LaneCodeBinding 当前状态；`checkpoints.ndjson` 保存检查点；`operations.ndjson` 保存 Git 操作过程。创建和删除等跨 Git/元数据操作使用 Operation Journal，启动时会重放或标记未完成操作。

binding 重点字段包括：托管分支、Worktree、base/head commit、sync state、last checkpoint、published branch、发布模式、待检查点 Run/Entry 和更新时间。外部删除分支、移动 Worktree、reset 或 rebase 会被重新读取并标记为 unavailable/out_of_sync，不自动 reset 覆盖外部历史。

## 八、安全边界

- 检查点忽略或阻断敏感凭证和超大文件；
- 内部 checkpoint 使用独立提交身份，不代表用户提交；
- 目标分支当前状态不一致时拒绝自动覆盖；
- Git 命令使用参数数组和规范绝对路径，不拼接 shell 字符串；
- 删除只清理 CodeMate 托管资源，不清理用户源目录和已发布分支；
- 非 Git 工作区明确降级，不伪造隔离、检查点或发布成功。

## 九、接口清单

| 功能 | 接口 |
|---|---|
| Lane 状态 | `GET /api/sessions/{id}/lanes/{lane}/status` |
| Git 状态/Diff | `GET .../git/status`、`GET .../git/diff` |
| 暂存/提交 | `POST .../git/stage`、`unstage`、`commit` |
| 检查点 | `POST .../checkpoint`、`GET .../checkpoints`、`POST .../restore` |
| 丢弃/发布 | `POST .../discard`、`POST .../publish` |
| 对比/集成 | `GET .../lanes/compare`、`GET .../integrate/preview`、`POST .../integrate` |
| 归档/恢复 | `POST .../archive`、`POST .../restore-lane` |
| 集成记录 | `GET /api/sessions/{id}/integrations` |

完整路径中的 `...` 为 `/sessions/{session_id}/lanes/{lane}`，前端工作台映射见 [08-VSCode 风格会话工作台](../05-Web-UI层/08-VSCode风格会话工作台.md)。

## 十、实现对应

| 代码 | 职责 |
|---|---|
| `backend/src/version_control/manager.py` | 仓库检测、Worktree、检查点、Diff、发布和集成 |
| `backend/src/version_control/models.py` | Binding、Checkpoint、Integration 数据模型 |
| `backend/src/version_control/store.py` | Git 元数据持久化 |
| `backend/src/api/session_service.py` | Session 与 Lane/Git 生命周期编排 |
| `backend/tests/test_version_control.py` | Git Lane 核心行为 |
| `backend/tests/test_checkpoint_strategy.py` | 自动检查点阈值和恢复 |
