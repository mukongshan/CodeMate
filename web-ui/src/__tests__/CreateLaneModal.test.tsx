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

    await user.type(screen.getByRole('textbox'), 'feature-x');
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
});
