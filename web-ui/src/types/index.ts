// Entry 数据模型
export interface Entry {
  id: string;
  parent: string | null;
  lane: string;
  seq: number;
  role: 'user' | 'assistant' | 'tool';
  content: string;
  full_content: string | ContentBlock[];
  tool_names: string[];
  is_error: boolean;
  timestamp: number;
  tokens: number;
}

export interface ContentBlock {
  kind: 'text' | 'tool_use' | 'tool_result';
  text?: string;
  id?: string;
  name?: string;
  arguments?: Record<string, any>;
  tool_call_id?: string;
  content?: string;
  is_error?: boolean;
}

// Lane 数据模型
export interface LanePointer {
  lane: string;
  leaf_id: string | null;
  seq: number;
  timestamp: number;
  created_from: string | null;
  description: string;
}

// Agent 状态
export type AgentState =
  | 'idle'
  | 'preparing'
  | 'calling_llm'
  | 'executing_tool'
  | 'waiting_permission'
  | 'completed'
  | 'error';

// WebSocket 事件类型
export interface WSEnvelope {
  type: string;
  data: Record<string, any>;
}

// 会话快照
export interface SessionSnapshot {
  session_id: string;
  workspace: string;
  command_allowlist: string[];
  current_lane: string;
  agent_state: AgentState;
  is_running: boolean;
  lanes: LanePointer[];
  entries: Entry[];
}

// 工具调用状态
export interface ToolCall {
  call_id: string;
  tool_name: string;
  args: Record<string, any>;
  status: 'pending' | 'success' | 'error';
  result?: string;
}

// 子 Agent 状态
export interface SubAgent {
  subagent_id: string;
  task: string;
  max_steps: number;
  step: number;
  tool_name?: string;
  status: 'pending' | 'completed' | 'partial' | 'error';
  content?: string;
  details?: {
    subagent_id: string;
    tool_calls: number;
    files_touched: string[];
    duration: number;
    total_tokens: number;
  };
}

// 权限请求
export interface PermissionRequest {
  request_id: string;
  tool_name: string;
  args: Record<string, any>;
  risk_level: 'low' | 'medium' | 'high';
  warning: string;
}

// 消息
export interface Message {
  message_id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  is_streaming?: boolean;
  tool_calls?: ToolCall[];
  subagents?: SubAgent[];
}

// Toast 通知
export interface Toast {
  id: string;
  type: 'success' | 'error' | 'warning' | 'info';
  title?: string;
  message: string;
  duration?: number;
}
