import { useEffect, useState } from 'react';
import {
  AlertCircle,
  ArrowLeft,
  ChevronRight,
  Clock,
  FolderKanban,
  FolderOpen,
  MessageSquare,
  Pencil,
  Plus,
  Trash2,
} from 'lucide-react';
import { useStore } from '../store';

interface WorkspaceSummary {
  workspace_id: string;
  path: string;
  title: string;
  session_count: number;
  status: 'ok' | 'missing-dir';
  updated_at: number;
}

interface SessionSummary {
  session_id: string;
  workspace_id: string;
  title: string;
  updated_at: number;
  loaded: boolean;
  workspace: string;
}

function formatRelativeTime(timestampSeconds: number): string {
  const diff = Date.now() - timestampSeconds * 1000;
  if (diff < 60_000) return '刚刚';
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`;
  if (diff < 2_592_000_000) return `${Math.floor(diff / 86_400_000)} 天前`;
  return new Date(timestampSeconds * 1000).toLocaleDateString('zh-CN');
}

async function responseError(response: Response, fallback: string) {
  try {
    const payload = await response.json();
    return payload.error?.message || payload.detail || fallback;
  } catch {
    return fallback;
  }
}

export default function SessionPicker() {
  const { setSession } = useStore();
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [workspacePath, setWorkspacePath] = useState(
    () => localStorage.getItem('codemate:last-workspace') || './workspace'
  );
  const [sessionTitle, setSessionTitle] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [pickingDirectory, setPickingDirectory] = useState(false);
  const [error, setError] = useState('');

  const selectedWorkspace = workspaces.find(
    (workspace) => workspace.workspace_id === selectedWorkspaceId
  );

  useEffect(() => {
    void loadWorkspaces();
  }, []);

  const loadWorkspaces = async () => {
    setError('');
    try {
      const response = await fetch('/api/workspaces');
      if (!response.ok) {
        throw new Error(await responseError(response, '加载工作区失败'));
      }
      const payload = await response.json();
      setWorkspaces(payload.workspaces || []);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '加载工作区失败');
    } finally {
      setLoading(false);
    }
  };

  const loadSessions = async (workspaceId: string) => {
    setBusy(true);
    setError('');
    try {
      const response = await fetch(
        `/api/workspaces/${workspaceId}/sessions`
      );
      if (!response.ok) {
        throw new Error(await responseError(response, '加载会话失败'));
      }
      const payload = await response.json();
      setSessions(payload.sessions || []);
      setSelectedWorkspaceId(workspaceId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '加载会话失败');
    } finally {
      setBusy(false);
    }
  };

  const pickDirectory = async () => {
    setPickingDirectory(true);
    setError('');
    try {
      const params = new URLSearchParams();
      if (workspacePath.trim()) params.set('initial_path', workspacePath.trim());
      const query = params.toString();
      const response = await fetch(
        `/api/filesystem/pick-directory${query ? `?${query}` : ''}`,
        { method: 'POST' }
      );
      if (!response.ok) {
        throw new Error(await responseError(response, '选择目录失败'));
      }
      const payload = await response.json();
      if (payload.path) {
        setWorkspacePath(payload.path);
        localStorage.setItem('codemate:last-workspace', payload.path);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '选择目录失败');
    } finally {
      setPickingDirectory(false);
    }
  };

  const addWorkspace = async () => {
    const path = workspacePath.trim();
    if (!path) {
      setError('工作区目录不能为空');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const response = await fetch('/api/workspaces', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      });
      if (!response.ok) {
        throw new Error(await responseError(response, '添加工作区失败'));
      }
      const payload = await response.json();
      localStorage.setItem('codemate:last-workspace', path);
      await loadWorkspaces();
      await loadSessions(payload.workspace.workspace_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '添加工作区失败');
    } finally {
      setBusy(false);
    }
  };

  const createSession = async () => {
    if (!selectedWorkspaceId) return;
    setBusy(true);
    setError('');
    try {
      const response = await fetch(
        `/api/workspaces/${selectedWorkspaceId}/sessions`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: sessionTitle.trim() || undefined }),
        }
      );
      if (!response.ok) {
        throw new Error(await responseError(response, '创建会话失败'));
      }
      const payload = await response.json();
      setSessionTitle('');
      await openSession(payload.session_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '创建会话失败');
    } finally {
      setBusy(false);
    }
  };

  const openSession = async (sessionId: string) => {
    setError('');
    try {
      const response = await fetch(`/api/sessions/${sessionId}`);
      if (!response.ok) {
        throw new Error(await responseError(response, '打开会话失败'));
      }
      setSession(sessionId, await response.json());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '打开会话失败');
    }
  };

  const renameWorkspace = async () => {
    if (!selectedWorkspace) return;
    const title = window.prompt('新的工作区名称', selectedWorkspace.title)?.trim();
    if (!title || title === selectedWorkspace.title) return;
    const response = await fetch(`/api/workspaces/${selectedWorkspace.workspace_id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    });
    if (!response.ok) {
      setError(await responseError(response, '重命名工作区失败'));
      return;
    }
    await loadWorkspaces();
  };

  const removeWorkspace = async () => {
    if (!selectedWorkspace) return;
    if (selectedWorkspace.session_count > 0) {
      setError('工作区仍包含会话，请先删除这些会话');
      return;
    }
    if (!window.confirm(`从 CodeMate 移除“${selectedWorkspace.title}”？磁盘目录不会被删除。`)) return;
    const response = await fetch(`/api/workspaces/${selectedWorkspace.workspace_id}`, {
      method: 'DELETE',
    });
    if (!response.ok) {
      setError(await responseError(response, '移除工作区失败'));
      return;
    }
    setSelectedWorkspaceId(null);
    setSessions([]);
    await loadWorkspaces();
  };

  const renameSession = async (session: SessionSummary) => {
    const title = window.prompt('新的会话名称', session.title)?.trim();
    if (!title || title === session.title) return;
    const response = await fetch(`/api/sessions/${session.session_id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    });
    if (!response.ok) {
      setError(await responseError(response, '重命名会话失败'));
      return;
    }
    if (selectedWorkspaceId) await loadSessions(selectedWorkspaceId);
  };

  const deleteSession = async (session: SessionSummary) => {
    if (!window.confirm(`彻底删除会话“${session.title}”及其托管 Lane 工作目录？`)) return;
    const response = await fetch(`/api/sessions/${session.session_id}`, {
      method: 'DELETE',
    });
    if (!response.ok) {
      setError(await responseError(response, '删除会话失败'));
      return;
    }
    if (selectedWorkspaceId) {
      await loadSessions(selectedWorkspaceId);
      await loadWorkspaces();
    }
  };

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-surface-1">
        <div className="flex flex-col items-center gap-3 text-text-secondary">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-border border-t-accent" />
          <span className="text-sm">加载中...</span>
        </div>
      </div>
    );
  }

  return (
    <main className="relative flex h-screen overflow-hidden bg-surface-1 p-4 sm:p-6">
      {/* 背景光斑 */}
      <div
        aria-hidden
        className="pointer-events-none absolute -left-32 -top-40 h-[420px] w-[420px] rounded-full bg-accent/10 blur-3xl"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -bottom-44 -right-24 h-[380px] w-[380px] rounded-full bg-lane-aqua/10 blur-3xl"
      />

      <section className="relative mx-auto flex h-full min-h-0 w-full max-w-5xl flex-col">
        <header className="mb-5 flex shrink-0 items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="mb-2.5 flex items-center gap-2 text-[11px] font-medium tracking-wide text-text-muted">
              <span
                className={`rounded-full px-2 py-0.5 ${
                  selectedWorkspace
                    ? 'bg-surface-3 text-text-secondary'
                    : 'bg-accent/10 text-accent'
                }`}
              >
                01 工作区
              </span>
              <ChevronRight className="h-3 w-3" />
              <span
                className={`rounded-full px-2 py-0.5 ${
                  selectedWorkspace ? 'bg-accent/10 text-accent' : 'bg-surface-3'
                }`}
              >
                02 会话
              </span>
              <ChevronRight className="h-3 w-3" />
              <span className="rounded-full bg-surface-3 px-2 py-0.5">03 Lane</span>
            </div>
            <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">◈ CodeMate</h1>
            <p className="mt-1.5 text-sm text-text-secondary">
              {selectedWorkspace
                ? '在当前工作区中管理会话，每个会话有独立的分支树'
                : '先选择一个本地目录作为工作区，分支式对话与 Git 检查点都在其中进行'}
            </p>
          </div>
          {selectedWorkspace && (
            <button
              onClick={() => { setSelectedWorkspaceId(null); setSessions([]); setError(''); }}
              className="inline-flex flex-none items-center gap-1.5 rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm transition-colors hover:bg-surface-3"
            >
              <ArrowLeft size={15} /> 返回工作区
            </button>
          )}
        </header>

        {error && (
          <div className="mb-4 flex shrink-0 items-start gap-2 rounded-lg border border-status-error/40 bg-red-50 px-3 py-2.5 text-sm text-status-error">
            <AlertCircle size={15} className="mt-0.5 flex-none" />
            <span className="min-w-0 break-words">{error}</span>
          </div>
        )}

        {!selectedWorkspace ? (
          <div className="flex min-h-0 flex-1 flex-col gap-4">
            <div className="shrink-0 rounded-xl border border-border bg-surface-2 p-4 shadow-card">
              <label className="mb-2 block text-sm font-medium">添加本地工作区</label>
              <div className="flex flex-wrap gap-2">
                <input
                  value={workspacePath}
                  onChange={(event) => setWorkspacePath(event.target.value)}
                  placeholder="D:/path/to/project"
                  className="min-w-0 flex-1 basis-64 rounded-lg border border-border bg-surface-1 px-3 py-2 font-mono text-sm outline-none transition-colors focus:border-accent focus:ring-1 focus:ring-accent/30"
                />
                <button
                  onClick={pickDirectory}
                  disabled={pickingDirectory}
                  className="flex-none rounded-lg border border-border bg-surface-1 px-3 text-text-secondary transition-colors hover:bg-surface-3 hover:text-text-primary disabled:opacity-50"
                  aria-label="浏览目录"
                >
                  <FolderOpen size={17} />
                </button>
                <button
                  onClick={addWorkspace}
                  disabled={busy}
                  className="inline-flex flex-none items-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white shadow-sm transition-opacity hover:opacity-90 disabled:opacity-50"
                >
                  <Plus size={16} /> 添加工作区
                </button>
              </div>
              <p className="mt-2 text-xs text-text-muted">
                目录不会被复制，CodeMate 只在其中创建托管的 Lane 工作树。
              </p>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto pr-1" aria-label="工作区列表" role="region">
              <div className="grid gap-3 sm:grid-cols-2">
                {workspaces.map((workspace) => (
                  <button
                    key={workspace.workspace_id}
                    onClick={() => loadSessions(workspace.workspace_id)}
                    className="group rounded-xl border border-border bg-surface-2 p-4 text-left shadow-card transition-all hover:-translate-y-0.5 hover:border-accent/50 hover:shadow-pop"
                  >
                    <div className="mb-4 flex items-start justify-between gap-3">
                      <span className="rounded-lg bg-accent/10 p-2 text-accent">
                        <FolderKanban size={20} />
                      </span>
                      <span className="rounded-full bg-surface-3 px-2 py-0.5 text-xs text-text-secondary">
                        {workspace.session_count} 个会话
                      </span>
                    </div>
                    <div className="truncate font-medium" title={workspace.title}>
                      {workspace.title}
                    </div>
                    <div
                      className="mt-1 truncate font-mono text-xs text-text-muted"
                      title={workspace.path}
                    >
                      {workspace.path}
                    </div>
                    <div className="mt-2.5 flex items-center gap-2 text-xs">
                      {workspace.status === 'missing-dir' ? (
                        <span className="inline-flex items-center gap-1 text-status-error">
                          <AlertCircle size={12} /> 目录当前不可用
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-text-muted">
                          <Clock size={12} /> {formatRelativeTime(workspace.updated_at)}
                        </span>
                      )}
                      <ChevronRight
                        size={14}
                        className="ml-auto text-text-muted transition-transform group-hover:translate-x-0.5 group-hover:text-accent"
                      />
                    </div>
                  </button>
                ))}
              </div>
              {workspaces.length === 0 && (
                <div className="flex h-56 flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border text-center">
                  <FolderKanban size={28} className="text-text-muted opacity-40" />
                  <div className="text-sm text-text-muted">还没有工作区</div>
                  <div className="text-xs text-text-muted opacity-70">
                    在上方填入或浏览一个已有目录来添加
                  </div>
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="flex min-h-0 flex-1 flex-col gap-4">
            <div className="shrink-0 rounded-xl border border-border bg-surface-2 p-4 shadow-card">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="flex min-w-0 items-start gap-3">
                  <span className="mt-0.5 flex-none rounded-lg bg-accent/10 p-2 text-accent">
                    <FolderKanban size={18} />
                  </span>
                  <div className="min-w-0">
                    <h2 className="truncate text-lg font-semibold">{selectedWorkspace.title}</h2>
                    <p
                      className="mt-0.5 truncate font-mono text-xs text-text-muted"
                      title={selectedWorkspace.path}
                    >
                      {selectedWorkspace.path}
                    </p>
                  </div>
                </div>
                <div className="flex flex-none gap-2">
                  <button
                    onClick={renameWorkspace}
                    className="inline-flex items-center gap-1 rounded-lg border border-border bg-surface-1 px-2.5 py-1.5 text-xs transition-colors hover:bg-surface-3"
                  >
                    <Pencil size={13} /> 重命名
                  </button>
                  <button
                    onClick={removeWorkspace}
                    className="inline-flex items-center gap-1 rounded-lg border border-border bg-surface-1 px-2.5 py-1.5 text-xs text-status-error transition-colors hover:bg-red-50"
                  >
                    <Trash2 size={13} /> 移除
                  </button>
                </div>
              </div>
              <div className="mt-4 flex flex-wrap gap-2 border-t border-border pt-4">
                <input
                  value={sessionTitle}
                  onChange={(event) => setSessionTitle(event.target.value)}
                  onKeyDown={(event) => { if (event.key === 'Enter') void createSession(); }}
                  placeholder="会话名称（可选）"
                  className="min-w-0 flex-1 basis-52 rounded-lg border border-border bg-surface-1 px-3 py-2 text-sm outline-none transition-colors focus:border-accent focus:ring-1 focus:ring-accent/30"
                />
                <button
                  onClick={createSession}
                  disabled={busy}
                  className="inline-flex flex-none items-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white shadow-sm transition-opacity hover:opacity-90 disabled:opacity-50"
                >
                  <Plus size={16} /> 新建会话
                </button>
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto pr-1" aria-label="会话列表" role="region">
              <div className="space-y-2">
                {sessions.map((session) => (
                  <div
                    key={session.session_id}
                    className="group flex items-center gap-2 rounded-xl border border-border bg-surface-2 p-2.5 transition-colors hover:border-accent/40 hover:bg-surface-3"
                  >
                    <button
                      onClick={() => openSession(session.session_id)}
                      className="flex min-w-0 flex-1 items-center gap-3 text-left"
                    >
                      <span className="flex-none rounded-lg bg-surface-1 p-2 text-accent">
                        <MessageSquare size={17} />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium">{session.title}</span>
                        <span className="mt-0.5 flex items-center gap-1.5 text-xs text-text-muted">
                          <Clock size={11} className="flex-none" />
                          {formatRelativeTime(session.updated_at)}
                          <span className="truncate font-mono opacity-70">
                            · {session.session_id}
                          </span>
                        </span>
                      </span>
                    </button>
                    <button
                      onClick={() => renameSession(session)}
                      className="flex-none rounded-lg p-2 text-text-muted transition-colors hover:bg-surface-1 hover:text-text-primary"
                      aria-label={`重命名 ${session.title}`}
                    >
                      <Pencil size={15} />
                    </button>
                    <button
                      onClick={() => deleteSession(session)}
                      className="flex-none rounded-lg p-2 text-text-muted transition-colors hover:bg-red-50 hover:text-status-error"
                      aria-label={`删除 ${session.title}`}
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                ))}
              </div>
              {sessions.length === 0 && (
                <div className="flex h-56 flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border text-center">
                  <MessageSquare size={28} className="text-text-muted opacity-40" />
                  <div className="text-sm text-text-muted">这个工作区还没有会话</div>
                  <div className="text-xs text-text-muted opacity-70">
                    用上方的「新建会话」开始第一轮对话
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </section>
    </main>
  );
}
