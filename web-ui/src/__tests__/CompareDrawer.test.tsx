import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import CompareDrawer from '../components/modals/CompareDrawer';
import { useStore } from '../store';

describe('CompareDrawer', () => {
  it('loads and renders lane differences', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        common_ancestor: 'root',
        lane_a_diff: [],
        lane_b_diff: ['node-b'],
        lane_a_entries: [],
        lane_b_entries: [
          { id: 'node-b', role: 'user', content: 'branch message' },
        ],
        identical: false,
      }),
    });
    vi.stubGlobal('fetch', fetchMock as any);

    useStore.setState({
      sessionId: 'session-1',
      currentLane: 'main',
      lanes: [
        { lane: 'main', leaf_id: 'root', seq: 1, timestamp: 1, created_from: null, description: '' },
        { lane: 'feature-x', leaf_id: 'node-b', seq: 2, timestamp: 2, created_from: 'root', description: 'branch' },
      ],
      showCompareDrawer: true,
    } as any);

    render(<CompareDrawer />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(await screen.findByRole('heading', { name: 'feature-x' })).toBeInTheDocument();
    expect(screen.getByText('branch message')).toBeInTheDocument();
  });
});
