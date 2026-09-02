import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import CreateLaneModal from '../components/modals/CreateLaneModal';
import { useStore } from '../store';

describe('CreateLaneModal', () => {
  it('validates input and submits the current lane leaf as from_id', async () => {
    const onClose = vi.fn();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ lane: 'feature-x' }),
    });
    vi.stubGlobal('fetch', fetchMock as any);

    useStore.setState({
      sessionId: 'session-1',
      currentLane: 'main',
      lanes: [
        { lane: 'main', leaf_id: 'node-main', seq: 1, timestamp: 1, created_from: null, description: '' },
      ],
    } as any);

    const user = userEvent.setup();
    render(<CreateLaneModal onClose={onClose} />);

    await user.type(screen.getByLabelText('分支名称'), 'feature-x');
    await user.click(screen.getByRole('button', { name: '创建分支' }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/sessions/session-1/lanes',
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: 'feature-x', from_id: 'node-main' }),
      })
    );
    expect(useStore.getState().toasts.at(-1)?.message).toContain('feature-x');
  });

  it('requests suggestions and submits selected display metadata', async () => {
    const onClose = vi.fn();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          suggestions: [{
            name: 'cache-v2',
            display_name: '缓存优化',
            description: '尝试更高命中率',
            source: 'auto',
          }],
        }),
      })
      .mockResolvedValue({ ok: true, json: async () => ({ lanes: [] }) });
    vi.stubGlobal('fetch', fetchMock as any);

    useStore.setState({
      sessionId: 'session-2',
      currentLane: 'main',
      lanes: [
        { lane: 'main', leaf_id: 'node-main', seq: 1, timestamp: 1, created_from: null, description: '' },
      ],
    } as any);

    const user = userEvent.setup();
    render(<CreateLaneModal onClose={onClose} />);
    await user.type(screen.getByLabelText('方案意图（可选）'), '优化缓存');
    await user.click(screen.getByRole('button', { name: '智能建议' }));
    await user.click(await screen.findByRole('button', { name: /缓存优化/ }));
    await user.click(screen.getByRole('button', { name: '创建分支' }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/sessions/session-2/lanes',
      expect.objectContaining({
        body: JSON.stringify({
          name: 'cache-v2',
          from_id: 'node-main',
          display_name: '缓存优化',
          description: '尝试更高命中率',
          name_source: 'auto',
        }),
      })
    );
  });
});
