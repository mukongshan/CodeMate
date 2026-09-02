import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ActivityBar from '../components/workbench/ActivityBar';
import { SearchPanel } from '../components/workbench/WorkbenchPanels';
import { useStore } from '../store';
import { resetStore } from '../test/test-utils';

describe('Workbench activity bar', () => {
  beforeEach(() => {
    resetStore();
  });

  it('toggles the active side panel when the same tool is clicked', () => {
    render(<ActivityBar />);

    const explorer = screen.getByRole('button', { name: '资源管理器' });
    expect(explorer).toHaveAttribute('aria-pressed', 'true');
    expect(useStore.getState().activeWorkbenchView).toBe('explorer');

    fireEvent.click(explorer);

    expect(explorer).toHaveAttribute('aria-pressed', 'false');
    expect(useStore.getState().activeWorkbenchView).toBeNull();
  });

  it('opens and closes the terminal from the activity bar', () => {
    render(<ActivityBar />);

    const terminal = screen.getByRole('button', { name: '打开终端' });
    fireEvent.click(terminal);

    expect(useStore.getState().terminalOpen).toBe(true);
    expect(screen.getByRole('button', { name: '关闭终端' })).toHaveAttribute('aria-pressed', 'true');

    fireEvent.click(screen.getByRole('button', { name: '关闭终端' }));

    expect(useStore.getState().terminalOpen).toBe(false);
  });

  it('searches the current workspace and shows matching files', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        results: [{ path: 'src/app.ts', line: 4, preview: 'const needle = true;', match_type: 'content' }],
      }),
    });
    vi.stubGlobal('fetch', fetchMock);
    useStore.setState({ sessionId: 'session-1' });

    render(<SearchPanel />);
    fireEvent.change(screen.getByRole('textbox', { name: '搜索文件名或内容' }), { target: { value: 'needle' } });
    fireEvent.click(screen.getByRole('button', { name: '搜索' }));

    expect(await screen.findByText('src/app.ts')).toBeInTheDocument();
    expect(screen.getByText('第 4 行')).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/workspace/search?')));
  });
});
