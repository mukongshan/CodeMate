import { useEffect, useRef } from 'react';
import { useStore } from '../store';
import { WSEnvelope } from '../types';

const WS_URL = 'ws://localhost:8000/ws';

export function useWebSocket(sessionId: string | null) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number>();

  const {
    setWsConnected,
    setWsReconnecting,
    setAgentState,
    addEntry,
    addMessage,
    updateMessage,
    appendMessageText,
    updateToolCall,
    updateSubagent,
    setPermissionRequest,
    addToast,
  } = useStore();

  useEffect(() => {
    if (!sessionId) return;

    const connect = () => {
      const ws = new WebSocket(`${WS_URL}/${sessionId}`);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log('WebSocket connected');
        setWsConnected(true);
        setWsReconnecting(false);
        addToast({ type: 'success', message: '连接已建立' });
      };

      ws.onmessage = (event) => {
        const envelope: WSEnvelope = JSON.parse(event.data);
        handleEvent(envelope);
      };

      ws.onerror = (error) => {
        console.error('WebSocket error:', error);
      };

      ws.onclose = () => {
        console.log('WebSocket disconnected');
        setWsConnected(false);
        setWsReconnecting(true);
        addToast({ type: 'warning', message: '连接已断开，正在重连...' });

        // 自动重连
        reconnectTimerRef.current = window.setTimeout(() => {
          connect();
        }, 3000);
      };
    };

    connect();

    return () => {
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [sessionId]);

  const handleEvent = (envelope: WSEnvelope) => {
    const { type, data } = envelope;

    switch (type) {
      case 'node_added':
        // 树上新增节点
        addEntry(data as any);
        break;

      case 'text_delta':
        // 流式追加文字
        appendMessageText(data.message_id, data.text);
        break;

      case 'message_start':
        // 开始新消息
        addMessage({
          message_id: data.message_id,
          role: 'assistant',
          content: '',
          timestamp: Date.now(),
          is_streaming: true,
        });
        break;

      case 'message_end':
        // 消息结束
        updateMessage(data.message_id, { is_streaming: false });
        break;

      case 'tool_call_start':
        // 工具开始执行
        updateToolCall(data.call_id, {
          call_id: data.call_id,
          tool_name: data.tool_name,
          args: data.args,
          status: 'pending',
        });
        break;

      case 'tool_call_end':
        // 工具执行完成
        updateToolCall(data.call_id, {
          call_id: data.call_id,
          status: data.status,
          result: data.result,
        });
        break;

      case 'subagent_started':
        // 子 Agent 开始
        updateSubagent(data.subagent_id, {
          subagent_id: data.subagent_id,
          task: data.task,
          max_steps: data.max_steps,
          step: 0,
          status: 'pending',
        });
        break;

      case 'subagent_progress':
        // 子 Agent 进度更新
        updateSubagent(data.subagent_id, {
          step: data.step,
          tool_name: data.tool_name,
        });
        break;

      case 'subagent_done':
        // 子 Agent 完成
        updateSubagent(data.subagent_id, {
          status: data.status,
          content: data.content,
          details: data.details,
        });
        break;

      case 'status_update':
        // Agent 状态更新
        setAgentState(data.state);
        break;

      case 'permission_request':
        // 权限请求
        setPermissionRequest({
          request_id: data.request_id,
          tool_name: data.tool_name,
          args: data.args,
          risk_level: data.risk_level,
          warning: data.warning,
        });
        break;

      case 'lane_created':
        addToast({ type: 'success', message: `已创建分支 ${data.lane}` });
        break;

      case 'lane_switched':
        addToast({ type: 'info', message: `切换到 ${data.lane}` });
        break;

      case 'run_error':
        addToast({ type: 'error', message: data.error || '运行出错' });
        break;

      case 'error':
        addToast({ type: 'error', message: data.message });
        break;

      default:
        console.log('Unknown event:', type, data);
    }
  };

  const sendMessage = (content: string, lane?: string) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      addToast({ type: 'error', message: '连接未建立' });
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
