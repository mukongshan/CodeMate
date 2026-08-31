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
  archived?: boolean;
  git?: LaneGitState;
}

export interface LaneGitState {
  enabled: boolean;
  reason?: string;
  managed_branch?: string;
  worktree_path?: string;
  workspace?: string;
  base_commit?: string;
  head_commit?: string;
  short_head?: string;
  sync_state?: 'clean' | 'dirty' | 'conflict' | 'out_of_sync' | 'unavailable';
  last_checkpoint_id?: string | null;
  changed_files?: string[];
  blocked_files?: Array<{ path: string; reason: string }>;
  published_branch?: string | null;
  published_commit?: string | null;
  published_lane_head?: string | null;
  published_mode?: 'branch' | 'squash' | null;
  published_base_branch?: string | null;
  publication_count?: number;
  published_at?: number | null;
  pending_checkpoint_since?: number | null;
  pending_checkpoint_last_run_at?: number | null;
  pending_run_ids?: string[];
  pending_conversation_entry_ids?: string[];
  updated_at?: number;
}

export interface CodeCheckpoint {
  checkpoint_id: string;
  lane: string;
  commit_sha: string;
  previous_commit: string | null;
  reason: string;
  conversation_entry_id?: string | null;
  run_id?: string | null;
  run_status?: string | null;
  changed_files: CodeDiffFile[];
  created_at: number;
}

export interface CodeDiffFile {
  status: 'A' | 'M' | 'D' | 'R' | 'C' | 'T' | string;
  path: string;
  old_path?: string;
  score?: string | null;
}

export interface WorkspaceFileEntry {
  name: string;
  path: string;
  kind: 'file' | 'directory';
  size: number | null;
  modified_at: number;
  hidden: boolean;
}

export interface WorkspaceDirectoryPayload {
  path: string;
  entries: WorkspaceFileEntry[];
  truncated: boolean;
  workspace: string;
  lane: string;
}

export interface WorkspaceFilePayload {
  path: string;
  content: string | null;
  encoding: string | null;
  binary: boolean;
  size: number;
  lines: number | null;
  workspace: string;
  lane: string;
}

export interface LaneCodeComparison {
  enabled: boolean;
  reason?: string;
  merge_base?: string;
  identical?: boolean;
  lane_a?: {
    lane: string;
    head_commit: string;
    short_head: string;
    managed_branch: string;
    dirty: boolean;
    sync_state: LaneGitState['sync_state'];
  };
  lane_b?: {
    lane: string;
    head_commit: string;
    short_head: string;
    managed_branch: string;
    dirty: boolean;
    sync_state: LaneGitState['sync_state'];
  };
  files: CodeDiffFile[];
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
  source_workspace?: string;
  git_enabled?: boolean;
  git_disabled_reason?: string;
  repository_root?: string | null;
  command_blacklist: string[];
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
  lane?: string;
}

// 子 Agent 状态
export interface SubAgent {
  subagent_id: string;
  task: string;
  max_steps: number;
  step: number;
  tool_name?: string;
  status: 'pending' | 'running' | 'completed' | 'partial' | 'error' | 'cancelled' | 'timeout';
  message?: string;
  content?: string;
  parent_run_id?: string;
  parent_lane?: string;
  lane?: string;
  details?: {
    subagent_id?: string;
    tool_calls?: number;
    files_touched?: string[];
    duration?: number;
    total_tokens?: number;
    summary_length?: number;
    summary_over_limit?: boolean;
    error?: string;
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

export interface RuntimeErrorNotice {
  title: string;
  message: string;
  code?: string;
  retryable?: boolean;
  suggestions?: string[];
  source: 'agent' | 'connection' | 'api';
}

// 消息
export interface Message {
  message_id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  lane?: string;
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
