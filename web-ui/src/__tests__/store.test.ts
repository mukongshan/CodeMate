import { describe, expect, it } from 'vitest';
import { useStore } from '../store';

describe('store', () => {
  it('adds and removes toasts with stable state updates', () => {
    const first = useStore.getState().toasts.length;
    useStore.getState().addToast({ type: 'info', message: 'hello' });
    const toast = useStore.getState().toasts.at(-1);

    expect(useStore.getState().toasts.length).toBe(first + 1);
    expect(toast?.message).toBe('hello');

    if (toast) {
      useStore.getState().removeToast(toast.id);
    }

    expect(useStore.getState().toasts.length).toBe(first);
  });

  it('updates messages and tool calls', () => {
    useStore.getState().addMessage({
      message_id: 'm1',
      role: 'assistant',
      content: '',
      timestamp: 1,
      is_streaming: true,
    });
    useStore.getState().appendMessageText('m1', 'hello');
    useStore.getState().updateMessage('m1', { is_streaming: false });

    expect(useStore.getState().messages[0].content).toBe('hello');
    expect(useStore.getState().messages[0].is_streaming).toBe(false);

    useStore.getState().updateToolCall('c1', {
      call_id: 'c1',
      tool_name: 'read_file',
      args: { path: 'a.txt' },
      status: 'pending',
    });
    useStore.getState().updateToolCall('c1', { status: 'success', result: 'ok' });

    expect(useStore.getState().toolCalls.get('c1')?.status).toBe('success');
  });
});
