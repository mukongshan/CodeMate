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

  it('renders changed files and loads a selected file diff', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.includes('/compare/file?')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ path: 'src/app.ts', diff: '-old\n+new', binary: false }),
        });
      }
      return Promise.resolve({
        ok: true,
        json: async () => ({
          common_ancestor: 'root',
          lane_a_entries: [],
          lane_b_entries: [],
          identical: false,
          code: {
            enabled: true,
            files: [{ status: 'M', path: 'src/app.ts' }],
            lane_a: { lane: 'main', short_head: 'aaaa1111' },
            lane_b: { lane: 'feature-x', short_head: 'bbbb2222' },
          },
        }),
      });
    });
    vi.stubGlobal('fetch', fetchMock as any);

    useStore.setState({
      sessionId: 'session-1',
      currentLane: 'main',
      lanes: [
        { lane: 'main', leaf_id: 'root' },
        { lane: 'feature-x', leaf_id: 'node-b' },
      ],
      showCompareDrawer: true,
    } as any);

    render(<CompareDrawer />);

    expect(await screen.findByText('src/app.ts')).toBeInTheDocument();
    expect(await screen.findByText(/\+new/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/compare/file?'),
      expect.objectContaining({ signal: expect.any(AbortSignal) })
    );
  });
});
