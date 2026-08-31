import { useStore } from '../store';

export function resetStore() {
  useStore.setState({
    sessionId: null,
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
    runtimeError: null,
    toasts: [],
  });
}
