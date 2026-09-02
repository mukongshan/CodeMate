import { useCallback, useEffect, useRef } from 'react';
import { useStore } from '../store';
import type { WSEnvelope } from '../types';

export function useWebSocket(sessionId: string | null) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | undefined>(undefined);

  const {
    setSession,
    setSessionTitle,
    setWsConnected,
    setWsReconnecting,
    setAgentState,
    setIsRunning,
    setMemoryBudget,
    resolveLocalUserMessage,
    updateMessage,
    appendMessageText,
    finishStreamingMessages,
    beginAssistantMessage,
    attachToolCall,
    updateToolCall,
    addFileReview,
    clearFileReviews,
    updateSubagent,
    clearSubagents,
    setPermissionRequest,
    setRuntimeError,
    clearRuntimeError,
    addToast,
    setTerminalSession,
    appendTerminalOutput,
    clearTerminalOutput,
    setTerminalError,
  } = useStore();

  const syncSessionSnapshot = useCallback(async () => {
    if (!sessionId) return;
    try {
      const res = await fetch(`/api/sessions/${sessionId}`);
      if (!res.ok) return;
      const data = await res.json();
      setSession(sessionId, data);
    } catch (error) {
      console.warn('Failed to sync session snapshot:', error);
    }
  }, [sessionId, setSession]);

  useEffect(() => {
    if (!sessionId) return;

    const connect = () => {
      const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const ws = new WebSocket(`${wsProtocol}//${window.location.host}/ws/${sessionId}`);
      const currentWs = ws;
      wsRef.current = ws;

      ws.onopen = () => {
        if (wsRef.current !== currentWs) return;
        setWsConnected(true);
        setWsReconnecting(false);
        clearRuntimeError();
        if (reconnectTimerRef.current !== undefined) {
          clearTimeout(reconnectTimerRef.current);
          reconnectTimerRef.current = undefined;
        }
        addToast({ type: 'success', message: 'Connected' });
        void syncSessionSnapshot();
      };

      ws.onmessage = (event) => {
        if (wsRef.current !== currentWs) return;
        const envelope: WSEnvelope = JSON.parse(event.data);
        handleEvent(envelope);
      };

      ws.onerror = (error) => {
        if (wsRef.current !== currentWs) return;
        console.error('WebSocket error:', error);
      };

      ws.onclose = () => {
        if (wsRef.current !== currentWs) return;
        setWsConnected(false);
        setWsReconnecting(true);
        setRuntimeError({
          title: '后端连接已断开',
          message: '正在自动重连，当前请求可能无法继续。',
          retryable: true,
          source: 'connection',
        });
        addToast({ type: 'warning', message: 'Connection lost, reconnecting...' });

        if (reconnectTimerRef.current !== undefined) {
          clearTimeout(reconnectTimerRef.current);
        }
        reconnectTimerRef.current = window.setTimeout(() => {
          connect();
        }, 3000);
      };
    };

    connect();

    return () => {
      if (reconnectTimerRef.current !== undefined) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = undefined;
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [
    sessionId,
    syncSessionSnapshot,
    setWsConnected,
    setWsReconnecting,
    addToast,
    clearSubagents,
    clearRuntimeError,
    setRuntimeError,
  ]);

  const handleEvent = (envelope: WSEnvelope) => {
    const { type, data } = envelope;
    const eventBelongsToCurrentLane =
      !data.lane || data.lane === useStore.getState().currentLane;

    switch (type) {
      case 'node_added':
        if (data.role === 'user' && data.id) {
          // 用后端真实 entry id 替换本地乐观插入的 id，
          // 避免快照回放时同一条用户消息按新 id 重新排到末尾
          resolveLocalUserMessage(data.id);
        } else if (data.message_id && data.id) {
          updateMessage(data.message_id, { message_id: data.id });
        }
        break;

      case 'text_delta':
        appendMessageText(data.message_id, data.text, data.lane);
        break;

      case 'message_start':
        // 只登记轮次，气泡等首个 text_delta 或工具调用再建
        beginAssistantMessage(data.message_id, data.lane);
        break;

      case 'message_end':
        updateMessage(data.message_id, { is_streaming: false });
        finishStreamingMessages();
        break;

      case 'tool_call_start':
        attachToolCall({
          call_id: data.call_id,
          tool_name: data.tool_name,
          args: data.args,
          status: 'pending',
          lane: data.lane,
        });
        break;

      case 'tool_call_end':
        updateToolCall(data.call_id, {
          call_id: data.call_id,
          status: data.status,
          result: data.result,
        });
        if (data.status === 'success' && data.metadata?.file_change) {
          const toolCall = useStore.getState().toolCalls.get(data.call_id);
          addFileReview({
            review_id: data.call_id,
            tool_name: toolCall?.tool_name || 'file_edit',
            file_change: data.metadata.file_change,
            lane: data.lane,
            created_at: Date.now(),
          });
        }
        break;

      case 'subagent_started':
        updateSubagent(data.subagent_id, {
          subagent_id: data.subagent_id,
          task: data.task,
          max_steps: data.max_steps,
          step: 0,
          status: data.status || 'pending',
          parent_run_id: data.parent_run_id,
          parent_lane: data.parent_lane,
          lane: data.lane || data.parent_lane,
        });
        break;

      case 'subagent_progress':
        updateSubagent(data.subagent_id, {
          step: data.step,
          tool_name: data.tool_name,
          status: data.status || 'running',
          message: data.message,
        });
        break;

      case 'subagent_done':
        updateSubagent(data.subagent_id, {
          status: data.status,
          content: data.content,
          details: data.details,
          message: data.message,
        });
        break;

      case 'status_update':
        if (eventBelongsToCurrentLane) setAgentState(data.state);
        break;

      case 'context_loaded':
        if (eventBelongsToCurrentLane && data.memory) {
          setMemoryBudget(data.memory);
        }
        break;

      case 'compaction_completed':
        if (!eventBelongsToCurrentLane) break;
        if (data.memory) setMemoryBudget(data.memory);
        addToast({ type: 'success', message: '上下文已压缩，Agent 已保留关键进展' });
        break;

      case 'compaction_failed':
        if (!eventBelongsToCurrentLane) break;
        addToast({ type: 'warning', message: data.reason || '上下文压缩失败，将继续使用现有记忆' });
        break;

      case 'run_started':
        if (!eventBelongsToCurrentLane) break;
        clearRuntimeError();
        clearSubagents();
        setAgentState('preparing');
        setIsRunning(true);
        break;

      case 'run_completed':
        if (!eventBelongsToCurrentLane) break;
        setIsRunning(false);
        finishStreamingMessages(data.status === 'aborted');
        setPermissionRequest(null);
        if (data.status === 'aborted') {
          addToast({ type: 'info', message: '已中断当前回复' });
        }
        void syncSessionSnapshot();
        break;

      case 'session_title_updated':
        setSessionTitle(data.title || '', data.source || 'auto', data.locked ?? false);
        break;

      case 'run_interrupt_requested':
        break;

      case 'run_interrupt_rejected':
        setIsRunning(false);
        addToast({ type: 'warning', message: data.message || '当前运行无法中断' });
        break;

      case 'llm_response':
        break;

      case 'permission_request':
        if (!eventBelongsToCurrentLane) break;
        setPermissionRequest({
          request_id: data.request_id,
          tool_name: data.tool_name,
          args: data.args,
          risk_level: data.risk_level,
          warning: data.warning,
        });
        break;

      case 'lane_created':
        addToast({ type: 'success', message: `Created lane ${data.display_name || data.lane}` });
        void syncSessionSnapshot();
        break;

      case 'lane_switched':
        addToast({ type: 'info', message: `Switched to ${data.lane}` });
        void syncSessionSnapshot();
        break;

      case 'lane_checkpoint_created':
        addToast({
          type: 'success',
          message: `代码检查点 ${data.short_head || data.checkpoint_id} 已保存`,
        });
        void syncSessionSnapshot();
        window.dispatchEvent(new Event('codemate:refresh-workspace'));
        window.dispatchEvent(new Event('codemate:refresh-source-control'));
        break;

      case 'lane_code_integrated':
        addToast({
          type: 'success',
          message: `${data.source_branch || data.lane} 已集成到 ${data.target_branch || 'main'}`,
        });
        void syncSessionSnapshot();
        window.dispatchEvent(new Event('codemate:refresh-workspace'));
        window.dispatchEvent(new Event('codemate:refresh-source-control'));
        break;

      case 'lane_sync_state_changed':
        addToast({
          type: 'warning',
          message: data.message || `${data.lane} 存在未保存的代码修改`,
        });
        void syncSessionSnapshot();
        window.dispatchEvent(new Event('codemate:refresh-workspace'));
        window.dispatchEvent(new Event('codemate:refresh-source-control'));
        break;

      case 'terminal_ready':
        setTerminalSession(data.terminal_id || null, 'ready');
        setTerminalError(null);
        break;

      case 'terminal_output':
        appendTerminalOutput(data.text || '');
        break;

      case 'terminal_exit':
        setTerminalSession(null, 'exited');
        addToast({ type: 'info', message: '终端进程已退出（' + (data.exit_code ?? '未知') + '）' });
        break;

      case 'terminal_closed':
        setTerminalSession(null, 'closed');
        break;

      case 'terminal_error':
        setTerminalError(data.message || '终端操作失败');
        addToast({ type: 'warning', message: data.message || '终端操作失败' });
        break;

      case 'run_error':
        if (!eventBelongsToCurrentLane) break;
        setIsRunning(false);
        setRuntimeError({
          title: 'Agent 运行失败',
          message: data.message || data.error || 'Run failed',
          code: data.code,
          retryable: Boolean(data.retryable),
          suggestions: Array.isArray(data.suggestions) ? data.suggestions : [],
          source: 'agent',
        });
        addToast({ type: 'error', message: data.message || data.error || 'Run failed' });
        break;

      case 'error':
        setRuntimeError({
          title: '请求处理失败',
          message: data.message || 'Request failed',
          code: data.code,
          source: 'api',
        });
        addToast({ type: 'error', message: data.message });
        break;

      default:
        console.log('Unknown event:', type, data);
    }
  };

  const sendMessage = (content: string, lane?: string) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      addToast({ type: 'error', message: 'Connection is not ready' });
      return;
    }

    clearFileReviews();

    wsRef.current.send(
      JSON.stringify({
        type: 'send_message',
        content,
        lane,
      })
    );
  };

  const compactSession = async (lane?: string) => {
    if (!sessionId) return false;
    try {
      const res = await fetch(`/api/sessions/${sessionId}/compact`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lane: lane || useStore.getState().currentLane }),
      });
      const data = await res.json();
      if (!res.ok) {
        addToast({ type: 'warning', message: data.detail || '当前无法压缩上下文' });
        return false;
      }
      if (data.memory) setMemoryBudget(data.memory);
      if (data.status === 'completed') {
        addToast({ type: 'success', message: '上下文压缩完成' });
      } else if (data.reason) {
        addToast({ type: 'info', message: data.reason });
      }
      await syncSessionSnapshot();
      return data.status === 'completed';
    } catch (error) {
      console.warn('Failed to compact session:', error);
      addToast({ type: 'error', message: '上下文压缩请求失败' });
      return false;
    }
  };

  const sendPermissionResponse = (requestId: string, action: string) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      return;
    }

    wsRef.current.send(
      JSON.stringify({
        type: 'permission_response',
        request_id: requestId,
        action,
      })
    );
  };

  const interruptRun = () => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      addToast({ type: 'error', message: 'Connection is not ready' });
      return false;
    }

    wsRef.current.send(JSON.stringify({ type: 'interrupt_run' }));
    return true;
  };

  const openTerminal = () => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      addToast({ type: 'warning', message: '连接尚未就绪，暂时无法打开终端' });
      return false;
    }
    clearTerminalOutput();
    setTerminalSession(null, 'connecting');
    wsRef.current.send(JSON.stringify({ type: 'terminal_open', lane: useStore.getState().currentLane }));
    return true;
  };

  const sendTerminalInput = (text: string) => {
    const terminalId = useStore.getState().terminalSessionId;
    if (!terminalId || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return false;
    wsRef.current.send(JSON.stringify({ type: 'terminal_input', terminal_id: terminalId, text }));
    return true;
  };

  const signalTerminal = (signal = 'interrupt') => {
    const terminalId = useStore.getState().terminalSessionId;
    if (!terminalId || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return false;
    wsRef.current.send(JSON.stringify({ type: 'terminal_signal', terminal_id: terminalId, signal }));
    return true;
  };

  const closeTerminal = () => {
    const terminalId = useStore.getState().terminalSessionId;
    if (terminalId && wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'terminal_close', terminal_id: terminalId }));
    }
    setTerminalSession(null, 'closed');
  };

  return {
    sendMessage,
    sendPermissionResponse,
    interruptRun,
    compactSession,
    openTerminal,
    sendTerminalInput,
    signalTerminal,
    closeTerminal,
  };
}
