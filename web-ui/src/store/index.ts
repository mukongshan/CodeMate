import { create } from 'zustand';
import type {
  Entry,
  LanePointer,
  AgentState,
  Message,
  ToolCall,
  FileReview,
  SubAgent,
  PermissionRequest,
  RuntimeErrorNotice,
  Toast,
  MemoryBudget,
  EditorTab,
  WorkbenchView,
  TerminalStatus,
} from '../types';

interface AppState {
  // Session 相关
  sessionId: string | null;
  sessionTitle: string;
  sessionTitleSource: string;
  sessionTitleLocked: boolean;
  workspaceId: string | null;
  workspace: string;
  commandBlacklist: string[];
  currentLane: string;
  lanes: LanePointer[];
  agentState: AgentState;
  isRunning: boolean;
  memoryBudget: MemoryBudget;

  // 树数据
  entries: Entry[];
  highlightedPaths: Set<string>; // 高亮的节点 ID 集合

  // 对话数据
  messages: Message[];
  toolCalls: Map<string, ToolCall>;
  fileReviews: Map<string, FileReview>;
  subagents: Map<string, SubAgent>;
  /** 当前 LLM 轮次的消息 id，工具调用挂到它名下 */
  pendingAssistantId: string | null;
  pendingAssistantLane?: string;

  // WebSocket 连接
  wsConnected: boolean;
  wsReconnecting: boolean;

  // UI 状态
  selectedNodeId: string | null;
  showNodeDetail: boolean;
  showCompareDrawer: boolean;
  showWorkspaceFiles: boolean;
  compareLanes: [string, string] | null;
  permissionRequest: PermissionRequest | null;
  runtimeError: RuntimeErrorNotice | null;
  toasts: Toast[];

  // 工作台状态
  activeWorkbenchView: WorkbenchView | null;
  sidePanelWidth: number;
  conversationWidth: number;
  terminalOpen: boolean;
  terminalHeight: number;
  terminalSessionId: string | null;
  terminalStatus: TerminalStatus;
  terminalOutput: string;
  terminalError: string | null;
  editorTabs: EditorTab[];
  activeEditorPath: string | null;

  // Actions
  setSession: (sessionId: string, data: any) => void;
  setSessionTitle: (title: string, source?: string, locked?: boolean) => void;
  clearSession: () => void;
  setCurrentLane: (lane: string) => void;
  setAgentState: (state: AgentState) => void;
  setIsRunning: (running: boolean) => void;
  setMemoryBudget: (budget: Partial<MemoryBudget>) => void;
  setCommandBlacklist: (commands: string[]) => void;

  addEntry: (entry: Entry) => void;
  updateEntries: (entries: Entry[]) => void;
  setHighlightedPaths: (nodeIds: Set<string>) => void;

  addMessage: (message: Message) => void;
  updateMessage: (messageId: string, update: Partial<Message>) => void;
  appendMessageText: (messageId: string, text: string, lane?: string) => void;
  finishStreamingMessages: (removeEmptyInterrupted?: boolean) => void;

  resolveLocalUserMessage: (realId: string) => void;

  beginAssistantMessage: (messageId: string, lane?: string) => void;
  attachToolCall: (call: ToolCall) => void;
  updateToolCall: (callId: string, update: Partial<ToolCall>) => void;
  addFileReview: (review: FileReview) => void;
  acceptFileReview: (reviewId: string) => void;
  acceptFileReviews: (reviewIds: string[]) => void;
  clearFileReviews: () => void;
  updateSubagent: (subagentId: string, update: Partial<SubAgent>) => void;
  clearSubagents: () => void;

  setWsConnected: (connected: boolean) => void;
  setWsReconnecting: (reconnecting: boolean) => void;

  setSelectedNode: (nodeId: string | null) => void;
  setShowNodeDetail: (show: boolean) => void;
  setShowCompareDrawer: (show: boolean) => void;
  setShowWorkspaceFiles: (show: boolean) => void;
  setCompareLanes: (lanes: [string, string] | null) => void;
  setPermissionRequest: (request: PermissionRequest | null) => void;
  setRuntimeError: (error: RuntimeErrorNotice | null) => void;
  clearRuntimeError: () => void;

  setWorkbenchView: (view: WorkbenchView | null) => void;
  setSidePanelWidth: (width: number) => void;
  setConversationWidth: (width: number) => void;
  setTerminalOpen: (open: boolean) => void;
  setTerminalHeight: (height: number) => void;
  setTerminalSession: (sessionId: string | null, status: TerminalStatus) => void;
  setTerminalOutput: (output: string) => void;
  appendTerminalOutput: (output: string) => void;
  clearTerminalOutput: () => void;
  setTerminalError: (error: string | null) => void;
  openEditorTab: (tab: EditorTab) => void;
  updateEditorTab: (path: string, update: Partial<EditorTab>) => void;
  setEditorContent: (path: string, content: string) => void;
  closeEditorTab: (path: string) => void;
  setActiveEditorPath: (path: string | null) => void;

  addToast: (toast: Omit<Toast, 'id'>) => void;
  removeToast: (id: string) => void;
}

export const useStore = create<AppState>((set) => ({
  // 初始状态
  sessionId: null,
  sessionTitle: '',
  sessionTitleSource: 'default',
  sessionTitleLocked: false,
  workspaceId: null,
  workspace: '',
  commandBlacklist: [],
  currentLane: 'main',
  lanes: [],
  agentState: 'idle',
  isRunning: false,
  memoryBudget: {
    used_tokens: 0,
    max_tokens: 8000,
    reserve_tokens: 2000,
    threshold_tokens: 6400,
    remaining_tokens: 8000,
    utilization_ratio: 0,
  },

  entries: [],
  highlightedPaths: new Set(),

  messages: [],
  toolCalls: new Map(),
  fileReviews: new Map(),
  subagents: new Map(),
  pendingAssistantId: null,
  pendingAssistantLane: undefined,

  wsConnected: false,
  wsReconnecting: false,

  selectedNodeId: null,
  showNodeDetail: false,
  showCompareDrawer: false,
  showWorkspaceFiles: false,
  compareLanes: null,
  permissionRequest: null,
  runtimeError: null,
  toasts: [],

  activeWorkbenchView: 'explorer',
  sidePanelWidth: 280,
  conversationWidth: 380,
  terminalOpen: false,
  terminalHeight: 260,
  terminalSessionId: null,
  terminalStatus: 'closed',
  terminalOutput: '',
  terminalError: null,
  editorTabs: [],
  activeEditorPath: null,

  // Actions
  setSession: (sessionId, data) =>
    set((state) => {
      const nextLane = data.current_lane || 'main';
      const sameSession = state.sessionId === sessionId;
      const laneChanged = sameSession && state.currentLane !== nextLane;
      const resetTransient = !sameSession || laneChanged;
      return {
        sessionId,
        sessionTitle: data.title || state.sessionTitle || sessionId,
        sessionTitleSource: data.title_source || state.sessionTitleSource,
        sessionTitleLocked: data.title_locked ?? state.sessionTitleLocked,
        workspaceId: data.workspace_id ?? state.workspaceId,
        workspace: data.workspace || '',
        commandBlacklist: data.command_blacklist || [],
        currentLane: nextLane,
        lanes: data.lanes || [],
        agentState: data.agent_state || 'idle',
        isRunning: data.is_running || false,
        memoryBudget: data.memory ? { ...state.memoryBudget, ...data.memory } : state.memoryBudget,
        entries: data.entries || [],
        messages: resetTransient ? [] : state.messages,
        toolCalls: resetTransient ? new Map() : state.toolCalls,
        fileReviews: !sameSession ? new Map() : state.fileReviews,
        subagents: resetTransient ? new Map() : state.subagents,
        selectedNodeId: null,
        permissionRequest: resetTransient ? null : state.permissionRequest,
        runtimeError: resetTransient ? null : state.runtimeError,
        activeWorkbenchView: resetTransient ? 'explorer' : state.activeWorkbenchView,
        editorTabs: resetTransient ? [] : state.editorTabs,
        activeEditorPath: resetTransient ? null : state.activeEditorPath,
      };
    }),

  clearSession: () =>
    set({
      sessionId: null,
      sessionTitle: '',
      sessionTitleSource: 'default',
      sessionTitleLocked: false,
      workspaceId: null,
      workspace: '',
      commandBlacklist: [],
      currentLane: 'main',
      lanes: [],
      agentState: 'idle',
      isRunning: false,
      memoryBudget: {
        used_tokens: 0,
        max_tokens: 8000,
        reserve_tokens: 2000,
        threshold_tokens: 6400,
        remaining_tokens: 8000,
        utilization_ratio: 0,
      },
      entries: [],
      highlightedPaths: new Set(),
      messages: [],
      toolCalls: new Map(),
      fileReviews: new Map(),
      subagents: new Map(),
      pendingAssistantId: null,
      pendingAssistantLane: undefined,
      selectedNodeId: null,
      showNodeDetail: false,
      showCompareDrawer: false,
      showWorkspaceFiles: false,
      compareLanes: null,
      permissionRequest: null,
      runtimeError: null,
      wsConnected: false,
      wsReconnecting: false,
      activeWorkbenchView: 'explorer',
      sidePanelWidth: 280,
      conversationWidth: 380,
      terminalOpen: false,
      terminalHeight: 260,
      terminalSessionId: null,
      terminalStatus: 'closed',
      terminalOutput: '',
      terminalError: null,
      editorTabs: [],
      activeEditorPath: null,
    }),

  setCurrentLane: (lane) =>
    set((state) =>
      state.currentLane === lane
        ? { currentLane: lane }
        : {
            currentLane: lane,
            messages: [],
            toolCalls: new Map(),
            subagents: new Map(),
            pendingAssistantId: null,
            pendingAssistantLane: undefined,
            permissionRequest: null,
            runtimeError: null,
          }
    ),
  setSessionTitle: (title, source = 'auto', locked = false) =>
    set({ sessionTitle: title, sessionTitleSource: source, sessionTitleLocked: locked }),
  setAgentState: (state) => set({ agentState: state }),
  setIsRunning: (running) => set({ isRunning: running }),
  setMemoryBudget: (budget) =>
    set((state) => ({ memoryBudget: { ...state.memoryBudget, ...budget } })),
  setCommandBlacklist: (commands) => set({ commandBlacklist: commands }),

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

  resolveLocalUserMessage: (realId) =>
    set((state) => {
      const index = state.messages.findLastIndex(
        (message) => message.role === 'user' && message.message_id.startsWith('local-user-')
      );
      if (index === -1) return {};
      const messages = [...state.messages];
      messages[index] = { ...messages[index], message_id: realId };
      return { messages };
    }),

  updateMessage: (messageId, update) =>
    set((state) => {
      const nextMessageId = update.message_id;
      return {
        messages: state.messages.map((msg) =>
          msg.message_id === messageId ? { ...msg, ...update } : msg
        ),
        pendingAssistantId:
          nextMessageId && state.pendingAssistantId === messageId
            ? nextMessageId
            : state.pendingAssistantId,
      };
    }),

  appendMessageText: (messageId, text, lane) =>
    set((state) => {
      const exists = state.messages.some((msg) => msg.message_id === messageId);
      if (!exists) {
        // 气泡在收到首个 delta 时才创建，纯工具调用轮次不会留下空气泡
        return {
          messages: [
            ...state.messages,
            {
              message_id: messageId,
              role: 'assistant' as const,
              content: text,
              timestamp: Date.now(),
              is_streaming: true,
              lane,
            },
          ],
        };
      }
      return {
        messages: state.messages.map((msg) =>
          msg.message_id === messageId
            ? { ...msg, content: msg.content + text, is_streaming: true }
            : msg
        ),
      };
    }),

  finishStreamingMessages: (removeEmptyInterrupted = false) =>
    set((state) => ({
      // 只有工具调用、没有正文的轮次不该留下一个空气泡
      messages: (removeEmptyInterrupted
        ? state.messages.filter(
          (message) =>
            message.content.trim().length > 0 ||
            (message.tool_calls?.length ?? 0) > 0 ||
            message.role === 'user'
        )
        : state.messages
      ).map((message) =>
          message.is_streaming ? { ...message, is_streaming: false } : message
        ),
    })),

  beginAssistantMessage: (messageId, lane) =>
    set({ pendingAssistantId: messageId, pendingAssistantLane: lane }),

  attachToolCall: (call) =>
    set((state) => {
      const toolCalls = new Map(state.toolCalls);
      toolCalls.set(call.call_id, { ...toolCalls.get(call.call_id), ...call });

      const targetId = state.pendingAssistantId;
      if (!targetId) return { toolCalls };

      const index = state.messages.findIndex((message) => message.message_id === targetId);
      if (index === -1) {
        // 本轮还没有正文，只有工具调用：建一条无正文的载体，不渲染气泡
        return {
          toolCalls,
          messages: [
            ...state.messages,
            {
              message_id: targetId,
              role: 'assistant' as const,
              content: '',
              timestamp: Date.now(),
              lane: state.pendingAssistantLane,
              tool_calls: [call],
            },
          ],
        };
      }

      const target = state.messages[index];
      if (target.tool_calls?.some((item) => item.call_id === call.call_id)) {
        return { toolCalls };
      }
      const messages = [...state.messages];
      messages[index] = {
        ...target,
        tool_calls: [...(target.tool_calls ?? []), call],
      };
      return { toolCalls, messages };
    }),

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

  addFileReview: (review) =>
    set((state) => {
      const fileReviews = new Map(state.fileReviews);
      fileReviews.set(review.review_id, review);
      return { fileReviews };
    }),

  acceptFileReview: (reviewId) =>
    set((state) => {
      const fileReviews = new Map(state.fileReviews);
      fileReviews.delete(reviewId);
      return { fileReviews };
    }),

  acceptFileReviews: (reviewIds) =>
    set((state) => {
      const fileReviews = new Map(state.fileReviews);
      for (const reviewId of reviewIds) fileReviews.delete(reviewId);
      return { fileReviews };
    }),

  clearFileReviews: () => set({ fileReviews: new Map() }),

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

  clearSubagents: () => set({ subagents: new Map() }),

  setWsConnected: (connected) => set({ wsConnected: connected }),
  setWsReconnecting: (reconnecting) => set({ wsReconnecting: reconnecting }),

  setSelectedNode: (nodeId) => set({ selectedNodeId: nodeId }),
  setShowNodeDetail: (show) => set({ showNodeDetail: show }),
  setShowCompareDrawer: (show) => set({ showCompareDrawer: show }),
  setShowWorkspaceFiles: (show) => set({ showWorkspaceFiles: show }),
  setCompareLanes: (lanes) => set({ compareLanes: lanes }),
  setPermissionRequest: (request) => set({ permissionRequest: request }),
  setRuntimeError: (error) => set({ runtimeError: error }),
  clearRuntimeError: () => set({ runtimeError: null }),

  setWorkbenchView: (view) => set({ activeWorkbenchView: view }),
  setSidePanelWidth: (width) => set({ sidePanelWidth: Math.max(220, Math.min(480, width)) }),
  setConversationWidth: (width) => set({ conversationWidth: Math.max(320, Math.min(560, width)) }),
  setTerminalOpen: (open) => set({ terminalOpen: open }),
  setTerminalHeight: (height) => set({ terminalHeight: Math.max(160, Math.min(520, height)) }),
  setTerminalSession: (terminalSessionId, terminalStatus) => set({ terminalSessionId, terminalStatus, terminalError: terminalStatus === 'error' ? '终端启动失败' : null }),
  setTerminalOutput: (terminalOutput) => set({ terminalOutput }),
  appendTerminalOutput: (output) => set((state) => ({ terminalOutput: (state.terminalOutput + output).slice(-200000) })),
  clearTerminalOutput: () => set({ terminalOutput: '' }),
  setTerminalError: (terminalError) => set({ terminalError, terminalStatus: terminalError ? 'error' : 'ready' }),
  openEditorTab: (tab) =>
    set((state) => ({
      editorTabs: state.editorTabs.some((item) => item.path === tab.path)
        ? state.editorTabs.map((item) => (item.path === tab.path ? { ...item, ...tab } : item))
        : [...state.editorTabs, tab],
      activeEditorPath: tab.path,
    })),
  updateEditorTab: (path, update) =>
    set((state) => ({
      editorTabs: state.editorTabs.map((tab) => (tab.path === path ? { ...tab, ...update } : tab)),
    })),
  setEditorContent: (path, content) =>
    set((state) => ({
      editorTabs: state.editorTabs.map((tab) =>
        tab.path === path ? { ...tab, content, dirty: content !== tab.originalContent, error: undefined } : tab,
      ),
    })),
  closeEditorTab: (path) =>
    set((state) => {
      const remaining = state.editorTabs.filter((tab) => tab.path !== path);
      const nextActive = state.activeEditorPath === path
        ? remaining.at(-1)?.path || null
        : state.activeEditorPath;
      return { editorTabs: remaining, activeEditorPath: nextActive };
    }),
  setActiveEditorPath: (path) => set({ activeEditorPath: path }),

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
