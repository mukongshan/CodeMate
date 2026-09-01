import { useStore } from '../store';

export function resetStore() {
  useStore.setState({
    sessionId: null,
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
    wsConnected: false,
    wsReconnecting: false,
    selectedNodeId: null,
    showNodeDetail: false,
    showCompareDrawer: false,
    compareLanes: null,
    permissionRequest: null,
    runtimeError: null,
    toasts: [],
  });
}
