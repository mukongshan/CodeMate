import { create } from 'zustand';
import type {
  Entry,
  LanePointer,
  AgentState,
  Message,
  ToolCall,
  SubAgent,
  PermissionRequest,
  Toast,
} from '../types';

interface AppState {
  // Session 相关
  sessionId: string | null;
  workspace: string;
  commandAllowlist: string[];
  currentLane: string;
  lanes: LanePointer[];
  agentState: AgentState;
  isRunning: boolean;

  // 树数据
  entries: Entry[];
  highlightedPaths: Set<string>; // 高亮的节点 ID 集合

  // 对话数据
  messages: Message[];
  toolCalls: Map<string, ToolCall>;
  subagents: Map<string, SubAgent>;

  // WebSocket 连接
  wsConnected: boolean;
  wsReconnecting: boolean;

  // UI 状态
  selectedNodeId: string | null;
  showNodeDetail: boolean;
  showCompareDrawer: boolean;
  compareLanes: [string, string] | null;
  permissionRequest: PermissionRequest | null;
  toasts: Toast[];

  // Actions
  setSession: (sessionId: string, data: any) => void;
  clearSession: () => void;
  setCurrentLane: (lane: string) => void;
  setAgentState: (state: AgentState) => void;
  setIsRunning: (running: boolean) => void;
  setCommandAllowlist: (commands: string[]) => void;

  addEntry: (entry: Entry) => void;
  updateEntries: (entries: Entry[]) => void;
  setHighlightedPaths: (nodeIds: Set<string>) => void;

  addMessage: (message: Message) => void;
  updateMessage: (messageId: string, update: Partial<Message>) => void;
  appendMessageText: (messageId: string, text: string) => void;

  updateToolCall: (callId: string, update: Partial<ToolCall>) => void;
  updateSubagent: (subagentId: string, update: Partial<SubAgent>) => void;

  setWsConnected: (connected: boolean) => void;
  setWsReconnecting: (reconnecting: boolean) => void;

  setSelectedNode: (nodeId: string | null) => void;
  setShowNodeDetail: (show: boolean) => void;
  setShowCompareDrawer: (show: boolean) => void;
  setCompareLanes: (lanes: [string, string] | null) => void;
  setPermissionRequest: (request: PermissionRequest | null) => void;

  addToast: (toast: Omit<Toast, 'id'>) => void;
  removeToast: (id: string) => void;
}

export const useStore = create<AppState>((set) => ({
  // 初始状态
  sessionId: null,
  workspace: '',
  commandAllowlist: [],
  currentLane: 'main',
  lanes: [],
  agentState: 'idle',
  isRunning: false,

  entries: [],
  highlightedPaths: new Set(),

  messages: [],
  toolCalls: new Map(),
  subagents: new Map(),

  wsConnected: false,
  wsReconnecting: false,

  selectedNodeId: null,
  showNodeDetail: false,
  showCompareDrawer: false,
  compareLanes: null,
  permissionRequest: null,
  toasts: [],

  // Actions
  setSession: (sessionId, data) =>
    set({
      sessionId,
      workspace: data.workspace || '',
      commandAllowlist: data.command_allowlist || [],
      currentLane: data.current_lane || 'main',
      lanes: data.lanes || [],
      agentState: data.agent_state || 'idle',
      isRunning: data.is_running || false,
      entries: data.entries || [],
      messages: [],
      toolCalls: new Map(),
      subagents: new Map(),
      selectedNodeId: null,
      permissionRequest: null,
    }),

  clearSession: () =>
    set({
      sessionId: null,
      workspace: '',
      commandAllowlist: [],
      currentLane: 'main',
      lanes: [],
      agentState: 'idle',
      isRunning: false,
      entries: [],
      highlightedPaths: new Set(),
      messages: [],
      toolCalls: new Map(),
      subagents: new Map(),
      selectedNodeId: null,
      showNodeDetail: false,
      showCompareDrawer: false,
      compareLanes: null,
      permissionRequest: null,
      wsConnected: false,
      wsReconnecting: false,
    }),

  setCurrentLane: (lane) => set({ currentLane: lane }),
  setAgentState: (state) => set({ agentState: state }),
  setIsRunning: (running) => set({ isRunning: running }),
  setCommandAllowlist: (commands) => set({ commandAllowlist: commands }),

  addEntry: (entry) =>
    set((state) => ({
      entries: [...state.entries, entry],
    })),

  updateEntries: (entries) => set({ entries }),

  setHighlightedPaths: (nodeIds) => set({ highlightedPaths: nodeIds }),

  addMessage: (message) =>
    set((state) => ({
      messages: [...state.messages, message],
    })),

  updateMessage: (messageId, update) =>
    set((state) => ({
      messages: state.messages.map((msg) =>
        msg.message_id === messageId ? { ...msg, ...update } : msg
      ),
    })),

  appendMessageText: (messageId, text) =>
    set((state) => ({
      messages: state.messages.map((msg) =>
        msg.message_id === messageId
          ? { ...msg, content: msg.content + text }
          : msg
      ),
    })),

  updateToolCall: (callId, update) =>
    set((state) => {
      const newToolCalls = new Map(state.toolCalls);
      const existing = newToolCalls.get(callId);
      if (existing) {
        newToolCalls.set(callId, { ...existing, ...update });
      } else {
        newToolCalls.set(callId, update as ToolCall);
      }
      return { toolCalls: newToolCalls };
    }),

  updateSubagent: (subagentId, update) =>
    set((state) => {
      const newSubagents = new Map(state.subagents);
      const existing = newSubagents.get(subagentId);
      if (existing) {
        newSubagents.set(subagentId, { ...existing, ...update });
      } else {
        newSubagents.set(subagentId, update as SubAgent);
      }
      return { subagents: newSubagents };
    }),

  setWsConnected: (connected) => set({ wsConnected: connected }),
  setWsReconnecting: (reconnecting) => set({ wsReconnecting: reconnecting }),

  setSelectedNode: (nodeId) => set({ selectedNodeId: nodeId }),
  setShowNodeDetail: (show) => set({ showNodeDetail: show }),
  setShowCompareDrawer: (show) => set({ showCompareDrawer: show }),
  setCompareLanes: (lanes) => set({ compareLanes: lanes }),
  setPermissionRequest: (request) => set({ permissionRequest: request }),

  addToast: (toast) =>
    set((state) => ({
      toasts: [
        ...state.toasts,
        { ...toast, id: `toast-${Date.now()}-${Math.random()}` },
      ],
    })),

  removeToast: (id) =>
    set((state) => ({
      toasts: state.toasts.filter((t) => t.id !== id),
    })),
}));
