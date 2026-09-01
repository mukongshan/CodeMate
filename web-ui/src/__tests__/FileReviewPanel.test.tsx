import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import FileReviewPanel from '../components/conversation/FileReviewPanel';
import { useStore } from '../store';

const review = {
  review_id: 'call-1',
  tool_name: 'edit_file',
  lane: 'main',
  created_at: 1,
  file_change: {
    path: 'src/app.ts',
    binary: false,
    diff: [
      '--- a/src/app.ts',
      '+++ b/src/app.ts',
      '@@ -1,3 +1,3 @@',
      ' const ready = true;',
      '-old line',
      '+new line',
    ].join(String.fromCharCode(10)),
    added_lines: 1,
    removed_lines: 1,
  },
};

describe('FileReviewPanel', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('keeps reviews until accepted and starts collapsed', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ review_id: 'call-1' }) }));
    useStore.setState({
      sessionId: 'session-1',
      currentLane: 'main',
      fileReviews: new Map([['call-1', review]]),
    });

    const user = userEvent.setup();
    render(<FileReviewPanel />);

    const panelToggle = screen.getByRole('button', { name: '文件变更审查面板' });
    expect(panelToggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByText('1 个文件等待确认')).toBeInTheDocument();
    expect(screen.queryByText('等待你查看这次文件修改')).not.toBeInTheDocument();

    await user.click(panelToggle);
    const cardToggle = screen.getByRole('button', { name: '展开文件变更审查 src/app.ts' });
    expect(cardToggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('old line')).not.toBeInTheDocument();

    await user.click(cardToggle);
    expect(screen.getByText('old line').parentElement).toHaveClass('bg-rose-50');
    expect(screen.getByText('new line').parentElement).toHaveClass('bg-emerald-50');

    await user.click(screen.getByRole('button', { name: '接受变更' }));
    expect(useStore.getState().fileReviews.size).toBe(0);
    expect(screen.queryByLabelText('文件变更审查面板')).not.toBeInTheDocument();
  });

  it('rejects a file change through the backend and removes the review after rollback', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ review_id: 'call-1' }) });
    vi.stubGlobal('fetch', fetchMock);
    useStore.setState({
      sessionId: 'session-1',
      currentLane: 'main',
      fileReviews: new Map([['call-1', review]]),
    });

    const user = userEvent.setup();
    render(<FileReviewPanel />);
    await user.click(screen.getByRole('button', { name: '文件变更审查面板' }));
    await user.click(screen.getByRole('button', { name: '展开文件变更审查 src/app.ts' }));
    await user.click(screen.getByRole('button', { name: '拒绝并回滚' }));

    await waitFor(() => expect(useStore.getState().fileReviews.size).toBe(0));
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/sessions/session-1/file-reviews/call-1/reject',
      { method: 'POST' },
    );
  });

  it('accepts all visible file changes with one action', async () => {
    const secondReview = { ...review, review_id: 'call-2', file_change: { ...review.file_change, path: 'src/other.ts' } };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ review_ids: ['call-1', 'call-2'] }) }));
    useStore.setState({
      sessionId: 'session-1',
      currentLane: 'main',
      fileReviews: new Map([['call-1', review], ['call-2', secondReview]]),
    });

    const user = userEvent.setup();
    render(<FileReviewPanel />);
    await user.click(screen.getByRole('button', { name: '全部接受' }));

    await waitFor(() => expect(useStore.getState().fileReviews.size).toBe(0));
    expect(screen.queryByLabelText('文件变更审查面板')).not.toBeInTheDocument();
  });

  it('rejects all visible file changes after confirmation', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ review_ids: ['call-1'] }) });
    vi.stubGlobal('fetch', fetchMock);
    useStore.setState({
      sessionId: 'session-1',
      currentLane: 'main',
      fileReviews: new Map([['call-1', review]]),
    });

    const user = userEvent.setup();
    render(<FileReviewPanel />);
    await user.click(screen.getByRole('button', { name: '全部拒绝' }));
    await user.click(screen.getAllByRole('button', { name: '全部拒绝' })[1]);

    await waitFor(() => expect(useStore.getState().fileReviews.size).toBe(0));
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/sessions/session-1/file-reviews/reject-all',
      { method: 'POST' },
    );
  });
});
