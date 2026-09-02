import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useWebSocket } from '../hooks/useWebSocket';
import { useStore } from '../store';
import { resetStore } from '../test/test-utils';

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];

  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  url: string;
  readyState = FakeWebSocket.CONNECTING;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: Event) => void) | null = null;
  sent: string[] = [];

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.(new Event('close'));
  }

  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.(new Event('open'));
  }

  emit(payload: unknown) {
    this.onmessage?.(
      new MessageEvent('message', {
        data: JSON.stringify(payload),
      })
    );
  }
}

describe('useWebSocket', () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    vi.stubGlobal('WebSocket', FakeWebSocket as any);
  });

  afterEach(() => {
    resetStore();
    vi.unstubAllGlobals();
  });

  it('syncs snapshot, handles realtime events, and serializes outgoing payloads', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        session_id: 'session-1',
        current_lane: 'main',
        agent_state: 'idle',
        is_running: false,
        lanes: [{ lane: 'main', leaf_id: null, seq: 1, timestamp: 1, created_from: null, description: '' }],
        entries: [],
      }),
    });
    vi.stubGlobal('fetch', fetchMock as any);

    const { result } = renderHook(() => useWebSocket('session-1'));
    expect(FakeWebSocket.instances).toHaveLength(1);

    const ws = FakeWebSocket.instances[0];
    act(() => {
      ws.open();
    });

    await waitFor(() => expect(useStore.getState().wsConnected).toBe(true));
    expect(useStore.getState().currentLane).toBe('main');
    expect(fetchMock).toHaveBeenCalledWith('/api/sessions/session-1');

    act(() => {
      result.current.sendMessage('hello', 'main');
      result.current.sendPermissionResponse('perm-1', 'allow_once');
      result.current.interruptRun();
    });

    expect(JSON.parse(ws.sent[0])).toEqual({
      type: 'send_message',
      content: 'hello',
      lane: 'main',
    });
    expect(JSON.parse(ws.sent[1])).toEqual({
      type: 'permission_response',
      request_id: 'perm-1',
      action: 'allow_once',
    });
    expect(JSON.parse(ws.sent[2])).toEqual({ type: 'interrupt_run' });

    act(() => {
      ws.emit({ type: 'message_start', data: { message_id: 'm1' } });
      ws.emit({ type: 'text_delta', data: { message_id: 'm1', text: 'Hello' } });
      ws.emit({ type: 'node_added', data: { id: 'entry-m1', message_id: 'm1', role: 'assistant' } });
      ws.emit({ type: 'message_end', data: { message_id: 'm1', stop_reason: 'stop' } });
      ws.emit({ type: 'tool_call_start', data: { call_id: 'c1', tool_name: 'read_file', args: { path: 'a.txt' } } });
      ws.emit({
        type: 'tool_call_end',
        data: {
          call_id: 'c1',
          status: 'success',
          result: 'ok',
          metadata: {
            file_change: {
              path: 'src/app.ts',
              binary: false,
              diff: '+new line',
              added_lines: 1,
              removed_lines: 0,
            },
          },
        },
      });
      ws.emit({ type: 'subagent_started', data: { subagent_id: 'sub-1', task: 'inspect', max_steps: 8, status: 'pending' } });
      ws.emit({ type: 'subagent_progress', data: { subagent_id: 'sub-1', step: 2, max_steps: 8, status: 'running', tool_name: 'grep', message: '正在调用 grep' } });
      ws.emit({ type: 'subagent_done', data: { subagent_id: 'sub-1', status: 'completed', content: 'done', details: { tool_calls: 2 } } });
      ws.emit({ type: 'permission_request', data: { request_id: 'p1', tool_name: 'bash', args: { command: 'dir' }, risk_level: 'high', warning: 'danger' } });
      ws.emit({ type: 'lane_created', data: { lane: 'feature-x' } });
      ws.emit({ type: 'lane_switched', data: { lane: 'feature-x' } });
      ws.emit({ type: 'run_error', data: { message: 'boom' } });
      ws.emit({ type: 'status_update', data: { state: 'executing_tool' } });
      ws.emit({ type: 'run_completed', data: { run_id: 'r1', status: 'completed', iterations: 1, total_tokens: 10, duration: 0.1 } });
    });

    expect(useStore.getState().messages).toHaveLength(1);
    expect(useStore.getState().messages[0].message_id).toBe('entry-m1');
    expect(useStore.getState().messages[0].content).toBe('Hello');
    expect(useStore.getState().toolCalls.get('c1')?.status).toBe('success');
    expect(useStore.getState().fileReviews.get('c1')).toMatchObject({
      review_id: 'c1',
      tool_name: 'read_file',
      file_change: { path: 'src/app.ts' },
    });
    expect(useStore.getState().subagents.get('sub-1')).toMatchObject({
      status: 'completed',
      step: 2,
      tool_name: 'grep',
      content: 'done',
    });
    expect(useStore.getState().permissionRequest).toBeNull();
    expect(useStore.getState().agentState).toBe('executing_tool');
    expect(useStore.getState().runtimeError?.message).toBe('boom');
    expect(useStore.getState().toasts.at(-1)?.message).toBe('boom');

    act(() => {
      result.current.sendMessage('next conversation', 'main');
    });
    expect(useStore.getState().fileReviews.size).toBe(0);

    act(() => {
      ws.emit({ type: 'run_started', data: { run_id: 'r2', lane: 'main' } });
    });
    expect(useStore.getState().isRunning).toBe(true);
    expect(useStore.getState().subagents.size).toBe(0);

    act(() => {
      ws.emit({ type: 'run_completed', data: { run_id: 'r2', status: 'completed', iterations: 1, total_tokens: 1, duration: 0.1 } });
    });
    expect(useStore.getState().isRunning).toBe(false);

    act(() => {
      ws.emit({ type: 'run_started', data: { run_id: 'r3', lane: 'main' } });
      ws.emit({ type: 'message_start', data: { message_id: 'm2' } });
      ws.emit({ type: 'text_delta', data: { message_id: 'm2', text: 'partial' } });
      ws.emit({ type: 'run_completed', data: { run_id: 'r3', status: 'aborted', iterations: 1, total_tokens: 2, duration: 0.1 } });
    });
    expect(useStore.getState().isRunning).toBe(false);
    expect(useStore.getState().messages.at(-1)).toMatchObject({
      content: 'partial',
      is_streaming: false,
    });
    expect(useStore.getState().toasts.at(-1)?.message).toBe('已中断当前回复');

    act(() => {
      ws.close();
    });
    expect(useStore.getState().wsConnected).toBe(false);
    expect(useStore.getState().wsReconnecting).toBe(true);
    expect(useStore.getState().runtimeError?.source).toBe('connection');
  });

  it('updates automatic title silently without changing running state', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        session_id: 'session-1',
        title: '原始标题',
        current_lane: 'main',
        agent_state: 'idle',
        is_running: false,
        lanes: [],
        entries: [],
      }),
    });
    vi.stubGlobal('fetch', fetchMock as any);

    renderHook(() => useWebSocket('session-1'));
    const ws = FakeWebSocket.instances[0];
    act(() => ws.open());
    await waitFor(() => expect(useStore.getState().wsConnected).toBe(true));

    act(() => {
      ws.emit({
        type: 'session_title_updated',
        data: { title: '自动标题', source: 'auto', locked: false },
      });
    });

    expect(useStore.getState().sessionTitle).toBe('自动标题');
    expect(useStore.getState().isRunning).toBe(false);
    expect(useStore.getState().toasts.some((toast) => toast.message.includes('自动标题'))).toBe(false);
  });
});
