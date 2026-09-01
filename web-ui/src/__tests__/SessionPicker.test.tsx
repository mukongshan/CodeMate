import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import SessionPicker from '../components/SessionPicker';
import { useStore } from '../store';

const workspace = {
  workspace_id: 'workspace-a',
  path: 'D:/workspace/project-a',
  title: '项目 A',
  session_count: 1,
  status: 'ok',
  updated_at: 10,
};

const snapshot = {
  session_id: 'session-a',
  workspace_id: 'workspace-a',
  title: '会话 A',
  current_lane: 'main',
  agent_state: 'idle',
  is_running: false,
  lanes: [{ lane: 'main', leaf_id: null, seq: 1, timestamp: 1, created_from: null, description: '' }],
  entries: [],
};

describe('SessionPicker', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    useStore.getState().clearSession();
  });

  it('selects a workspace before opening one of its sessions', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ workspaces: [workspace] }) })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ sessions: [{ session_id: 'session-a', workspace_id: 'workspace-a', title: '会话 A', updated_at: 10, loaded: false, workspace: workspace.path }] }),
      })
      .mockResolvedValueOnce({ ok: true, json: async () => snapshot });
    vi.stubGlobal('fetch', fetchMock as any);

    const user = userEvent.setup();
    render(<SessionPicker />);

    await user.click(await screen.findByRole('button', { name: /项目 A/ }));
    const sessionTitle = await screen.findByText('会话 A');
    await user.click(sessionTitle.closest('button')!);

    await waitFor(() => expect(useStore.getState().sessionId).toBe('session-a'));
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/workspaces/workspace-a/sessions');
    expect(fetchMock).toHaveBeenNthCalledWith(3, '/api/sessions/session-a');
  });

  it('adds a workspace and creates a session inside it', async () => {
    const emptyWorkspace = { ...workspace, session_count: 0 };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ workspaces: [] }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ workspace: emptyWorkspace, created: true }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ workspaces: [emptyWorkspace] }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ sessions: [] }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ session_id: 'created-session' }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ ...snapshot, session_id: 'created-session' }) });
    vi.stubGlobal('fetch', fetchMock as any);

    const user = userEvent.setup();
    render(<SessionPicker />);

    await user.click(await screen.findByRole('button', { name: /添加工作区/ }));
    await user.type(await screen.findByPlaceholderText('会话名称（可选）'), '设计讨论');
    await user.click(screen.getByRole('button', { name: /新建会话/ }));

    await waitFor(() => expect(useStore.getState().sessionId).toBe('created-session'));
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/workspaces/workspace-a/sessions',
      expect.objectContaining({ method: 'POST' })
    );
  });

  it('keeps workspace controls visible while the registry scrolls', async () => {
    const workspaces = Array.from({ length: 30 }, (_, index) => ({
      ...workspace,
      workspace_id: `workspace-${index}`,
      title: `项目 ${index}`,
      path: `D:/workspace/project-${index}`,
    }));
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ workspaces }),
    }) as any);

    render(<SessionPicker />);

    expect(await screen.findByText('项目 29')).toBeInTheDocument();
    expect(screen.getByText('添加本地工作区')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /添加工作区/ })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: '工作区列表' })).toHaveClass('overflow-y-auto');
  });
});
