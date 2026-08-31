import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import WorkspaceFileViewer from '../components/modals/WorkspaceFileViewer';
import { useStore } from '../store';

describe('WorkspaceFileViewer', () => {
  it('loads directories lazily and displays a selected file', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.includes('/workspace/file?')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            path: 'src/main.py',
            content: "print('hello')\n",
            encoding: 'utf-8',
            binary: false,
            size: 15,
            lines: 1,
            workspace: 'D:/worktree/main',
            lane: 'main',
          }),
        });
      }
      if (url.includes('path=src')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            path: 'src',
            entries: [{ name: 'main.py', path: 'src/main.py', kind: 'file', size: 15, modified_at: 1, hidden: false }],
            truncated: false,
            workspace: 'D:/worktree/main',
            lane: 'main',
          }),
        });
      }
      return Promise.resolve({
        ok: true,
        json: async () => ({
          path: '',
          entries: [{ name: 'src', path: 'src', kind: 'directory', size: null, modified_at: 1, hidden: false }],
          truncated: false,
          workspace: 'D:/worktree/main',
          lane: 'main',
        }),
      });
    });
    vi.stubGlobal('fetch', fetchMock as any);
    useStore.setState({
      sessionId: 'session-1',
      currentLane: 'main',
      workspace: 'D:/worktree/main',
      showWorkspaceFiles: true,
    } as any);

    render(<WorkspaceFileViewer />);

    const sourceDirectory = await screen.findByRole('button', { name: /src/ });
    await userEvent.click(sourceDirectory);
    const sourceFile = await screen.findByRole('button', { name: /main\.py/ });
    await userEvent.click(sourceFile);

    expect(await screen.findByText("print('hello')")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/workspace/files?path=src'),
      expect.anything(),
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/workspace/file?path=src%2Fmain.py'),
    ));
  });
});
