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

    act(() => {
      ws.emit({ type: 'message_start', data: { message_id: 'm1' } });
      ws.emit({ type: 'text_delta', data: { message_id: 'm1', text: 'Hello' } });
      ws.emit({ type: 'tool_call_start', data: { call_id: 'c1', tool_name: 'read_file', args: { path: 'a.txt' } } });
      ws.emit({ type: 'tool_call_end', data: { call_id: 'c1', status: 'success', result: 'ok' } });
      ws.emit({ type: 'permission_request', data: { request_id: 'p1', tool_name: 'bash', args: { command: 'dir' }, risk_level: 'high', warning: 'danger' } });
      ws.emit({ type: 'lane_created', data: { lane: 'feature-x' } });
      ws.emit({ type: 'lane_switched', data: { lane: 'feature-x' } });
      ws.emit({ type: 'run_error', data: { message: 'boom' } });
      ws.emit({ type: 'status_update', data: { state: 'executing_tool' } });
      ws.emit({ type: 'run_completed', data: { run_id: 'r1', status: 'completed', iterations: 1, total_tokens: 10, duration: 0.1 } });
    });

    expect(useStore.getState().messages).toHaveLength(1);
    expect(useStore.getState().messages[0].content).toBe('Hello');
    expect(useStore.getState().toolCalls.get('c1')?.status).toBe('success');
    expect(useStore.getState().permissionRequest?.request_id).toBe('p1');
    expect(useStore.getState().agentState).toBe('executing_tool');
    expect(useStore.getState().toasts.at(-1)?.message).toBe('boom');

    act(() => {
      ws.emit({ type: 'run_started', data: { run_id: 'r2', lane: 'main' } });
    });
    expect(useStore.getState().isRunning).toBe(true);

    act(() => {
      ws.emit({ type: 'run_completed', data: { run_id: 'r2', status: 'completed', iterations: 1, total_tokens: 1, duration: 0.1 } });
    });
    expect(useStore.getState().isRunning).toBe(false);
  });
});
