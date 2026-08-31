import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import LaneCodeManagerModal from '../components/modals/LaneCodeManagerModal';
import { useStore } from '../store';

describe('LaneCodeManagerModal', () => {
  it('shows an existing publication as an updateable target', async () => {
    const lane = {
      lane: 'feature-x',
      leaf_id: null,
      seq: 1,
      timestamp: 1,
      created_from: null,
      description: '',
    };
    useStore.setState({
      sessionId: 'session-1',
      currentLane: 'feature-x',
      lanes: [lane],
    });
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/status')) {
        return {
          ok: true,
          json: async () => ({
            git: {
              enabled: true,
              head_commit: 'new-head',
              sync_state: 'clean',
              changed_files: [],
              blocked_files: [],
              published_branch: 'feature/result',
              published_commit: 'published-commit',
              published_lane_head: 'old-head',
              published_mode: 'branch',
              publication_count: 1,
            },
          }),
        } as Response;
      }
      if (url.includes('/checkpoints')) {
        return { ok: true, json: async () => ({ checkpoints: [] }) } as Response;
      }
      if (url.includes('include_archived=true')) {
        return { ok: true, json: async () => ({ lanes: [lane] }) } as Response;
      }
      return { ok: true, json: async () => ({}) } as Response;
    }));

    render(<LaneCodeManagerModal onClose={vi.fn()} />);

    expect(await screen.findByDisplayValue('feature/result')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '更新已发布分支' })).toBeEnabled();
    expect(screen.getByText('Lane 有新的检查点，可以继续更新该分支。')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByDisplayValue('保留检查点历史')).toBeDisabled();
    });
  });
});
