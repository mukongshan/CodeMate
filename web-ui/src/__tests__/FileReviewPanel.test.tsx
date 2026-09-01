import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
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
  it('keeps reviews until accepted and starts collapsed', async () => {
    useStore.setState({
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
});
