import { useCallback, useEffect, useRef } from 'react';
import { useStore } from '../store';
import type { WSEnvelope } from '../types';

export function useWebSocket(sessionId: string | null) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | undefined>(undefined);

  const {
    setSession,
    setWsConnected,
    setWsReconnecting,
    setAgentState,
    setIsRunning,
    addMessage,
    updateMessage,
    appendMessageText,
    updateToolCall,
    updateSubagent,
    setPermissionRequest,
    setRuntimeError,
    clearRuntimeError,
    addToast,
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
    clearRuntimeError,
    setRuntimeError,
  ]);

  const handleEvent = (envelope: WSEnvelope) => {
    const { type, data } = envelope;

    switch (type) {
      case 'node_added':
        break;

      case 'text_delta':
        appendMessageText(data.message_id, data.text);
        break;

      case 'message_start':
        addMessage({
          message_id: data.message_id,
          role: 'assistant',
          content: '',
          timestamp: Date.now(),
          is_streaming: true,
        });
        break;

      case 'message_end':
        updateMessage(data.message_id, { is_streaming: false });
        break;

      case 'tool_call_start':
        updateToolCall(data.call_id, {
          call_id: data.call_id,
          tool_name: data.tool_name,
          args: data.args,
          status: 'pending',
        });
        break;

      case 'tool_call_end':
        updateToolCall(data.call_id, {
          call_id: data.call_id,
          status: data.status,
          result: data.result,
        });
        break;

      case 'subagent_started':
        updateSubagent(data.subagent_id, {
          subagent_id: data.subagent_id,
          task: data.task,
          max_steps: data.max_steps,
          step: 0,
          status: 'pending',
        });
        break;

      case 'subagent_progress':
        updateSubagent(data.subagent_id, {
          step: data.step,
          tool_name: data.tool_name,
        });
        break;

      case 'subagent_done':
        updateSubagent(data.subagent_id, {
          status: data.status,
          content: data.content,
          details: data.details,
        });
        break;

      case 'status_update':
        setAgentState(data.state);
        break;

      case 'run_started':
        clearRuntimeError();
        setAgentState('preparing');
        setIsRunning(true);
        break;

      case 'run_completed':
        setIsRunning(false);
        void syncSessionSnapshot();
        break;

      case 'llm_response':
        break;

      case 'permission_request':
        setPermissionRequest({
          request_id: data.request_id,
          tool_name: data.tool_name,
          args: data.args,
          risk_level: data.risk_level,
          warning: data.warning,
        });
        break;

      case 'lane_created':
        addToast({ type: 'success', message: `Created lane ${data.lane}` });
        break;

      case 'lane_switched':
        addToast({ type: 'info', message: `Switched to ${data.lane}` });
        break;

      case 'run_error':
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

    wsRef.current.send(
      JSON.stringify({
        type: 'send_message',
        content,
        lane,
      })
    );
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

  return {
    sendMessage,
    sendPermissionResponse,
  };
}
