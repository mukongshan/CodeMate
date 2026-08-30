import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import Toolbar from '../components/toolbar/Toolbar';
import { useStore } from '../store';

describe('Toolbar', () => {
  it('switches lanes and opens compare drawer', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({}),
    });
    vi.stubGlobal('fetch', fetchMock as any);

    useStore.setState({
      sessionId: 'session-1',
      currentLane: 'main',
      lanes: [
        { lane: 'main', leaf_id: 'root', seq: 1, timestamp: 1, created_from: null, description: '' },
        { lane: 'feature-x', leaf_id: 'node-1', seq: 2, timestamp: 2, created_from: 'root', description: 'branch' },
      ],
      agentState: 'idle',
    } as any);

    const user = userEvent.setup();
    render(<Toolbar />);

    await user.click(screen.getByRole('button', { name: /main/i }));
    await user.click(screen.getByRole('button', { name: 'feature-x' }));

    await waitFor(() => expect(useStore.getState().currentLane).toBe('feature-x'));
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/sessions/session-1/lanes/feature-x/switch',
      expect.objectContaining({ method: 'POST' })
    );

    await user.click(screen.getByRole('button', { name: '对比' }));
    expect(useStore.getState().showCompareDrawer).toBe(true);
  });
});
