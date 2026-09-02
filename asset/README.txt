CodeMate

Git仓库地址：
https://github.com/mukongshan/CodeMate

一、最具创新性的设计
CodeMate的核心创新是“树形记忆管理+泳道管理+Git分支管理”的统一：它把智能体的思考过程和代码演化过程放进同一套可追踪模型，而不是把聊天记录、临时文件和Git操作割裂开。

树形记忆管理：用户消息、模型回复、工具调用和工具结果都保存为记忆节点，并通过父节点形成对话树。用户可以查看任意历史节点详情；可以创建分支并操作，主目录不会被自动覆盖；系统按照当前路径生成模型上下文，保留共享记忆，同时隔离分叉后的新记忆。

泳道管理：每条方案路径对应一个泳道（Lane），泳道拥有独立的名称、描述、当前记忆叶节点和运行状态。用户可以并行探索多个修复或设计方案，在泳道之间切换、比较和选择，而不会把不同思路混在同一条对话中。

与Git分支结合：在Git项目中，泳道不仅是对话分支，也绑定代码分支和独立Worktree。不同方案可以同时修改代码而互不覆盖；Agent运行过程可形成检查点，用户能够查看差异、恢复版本、放弃修改、发布泳道，并在集成前预览变更，最后将选中的方案合并回主工作区。这样实现了从“记忆分叉”到“代码分叉”再到“方案集成”的完整闭环。即使项目没有Git，仍可使用树形记忆和泳道功能，代码能力会明确降级。

二、功能完整性
CodeMate覆盖一次本地智能编程任务的完整流程：
1. 项目管理：Workspace、Session、Lane三级管理，支持创建、命名、切换、归档和删除。
2. Agent能力：支持OpenAI、DeepSeek兼容接口、流式回复、工具调用、并行执行、上下文预算、自动压缩和智能命名。
3. 代码工具：支持读写文件、精确编辑、目录浏览、文件名和内容搜索、命令执行及网页搜索。
4. 安全控制：工具按SAFE、WRITE、DANGEROUS分级，结合路径保护、危险命令识别、黑名单和用户确认。
5. 开发工作台：提供文件树、编辑器标签、终端、Source Control、对话面板、运行状态和Agent修改审查。
6. 子Agent与恢复：支持只读子Agent调查任务；对话、泳道、检查点和操作记录本地持久化，便于恢复和追踪。

三、运行方法
环境要求：Python 3.11+、Node.js/npm，以及OpenAI或DeepSeek兼容接口的LLM API Key。

1. 启动后端（Windows PowerShell）：
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
cd backend
python -m pip install -r requirements.txt
Copy-Item .env.example .env
编辑根目录.env，填写LLM_API_KEY，并将WORKSPACE设为待分析的代码目录。
python main.py

2. 启动前端（新终端）：
cd web-ui
npm ci
npm run dev

访问：http://localhost:5173
健康检查：http://127.0.0.1:8000/health
API文档：http://127.0.0.1:8000/docs

四、补充说明
运行数据默认保存在data/，前端通过REST和WebSocket连接后端。使用Git隔离时，目标项目需已有初始提交；联网搜索需额外配置搜索服务。详细设计和生产部署说明见README.md及local_docs/功能设计/。
