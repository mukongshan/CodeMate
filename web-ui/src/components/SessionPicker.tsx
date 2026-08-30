import { useEffect, useState } from 'react';
import { FolderOpen } from 'lucide-react';
import { useStore } from '../store';

interface Session {
  session_id: string;
  updated_at: number;
  loaded: boolean;
  workspace?: string;
}

export default function SessionPicker() {
  const { setSession } = useStore();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [pickingDirectory, setPickingDirectory] = useState(false);
  const [error, setError] = useState('');
  const [workspace, setWorkspace] = useState(
    () => localStorage.getItem('codemate:last-workspace') || './workspace'
  );

  useEffect(() => {
    loadSessions();
  }, []);

  const loadSessions = async () => {
    try {
      const res = await fetch('/api/sessions');
      if (!res.ok) {
        throw new Error(`Failed to load sessions: HTTP ${res.status}`);
      }
      const data = await res.json();
      setSessions(data.sessions || []);
    } catch (error) {
      console.error('Failed to load sessions:', error);
      setError(error instanceof Error ? error.message : 'Failed to load sessions');
    } finally {
      setLoading(false);
    }
  };

  const createSession = async () => {
    const trimmedWorkspace = workspace.trim();
    if (!trimmedWorkspace) {
      setError('工作区目录不能为空');
      return;
    }

    setCreating(true);
    setError('');
    try {
      const res = await fetch('/api/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace: trimmedWorkspace }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error?.message || `Failed to create session: HTTP ${res.status}`);
      }
      if (!data.session_id) {
        throw new Error('Failed to create session: missing session_id');
      }
      localStorage.setItem('codemate:last-workspace', trimmedWorkspace);
      await loadSessionData(data.session_id);
    } catch (error) {
      console.error('Failed to create session:', error);
      setError(error instanceof Error ? error.message : 'Failed to create session');
    } finally {
      setCreating(false);
    }
  };

  const pickDirectory = async () => {
    setPickingDirectory(true);
    setError('');
    try {
      const params = new URLSearchParams();
      const trimmedWorkspace = workspace.trim();
      if (trimmedWorkspace) {
        params.set('initial_path', trimmedWorkspace);
      }

      const query = params.toString();
      const res = await fetch(`/api/filesystem/pick-directory${query ? `?${query}` : ''}`, {
        method: 'POST',
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || `Failed to pick directory: HTTP ${res.status}`);
      }
      if (data.path) {
        setWorkspace(data.path);
        localStorage.setItem('codemate:last-workspace', data.path);
      }
    } catch (error) {
      console.error('Failed to pick directory:', error);
      setError(error instanceof Error ? error.message : 'Failed to pick directory');
    } finally {
      setPickingDirectory(false);
    }
  };

  const loadSessionData = async (sessionId: string) => {
    try {
      const res = await fetch(`/api/sessions/${sessionId}`);
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error?.message || `Failed to load session: HTTP ${res.status}`);
      }
      setSession(sessionId, data);
    } catch (error) {
      console.error('Failed to load session data:', error);
      setError(error instanceof Error ? error.message : 'Failed to load session data');
    }
  };

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="text-text-secondary">加载中...</div>
      </div>
    );
  }

  return (
    <div className="flex h-screen items-center justify-center bg-surface-1">
      <div className="w-full max-w-2xl p-8">
        <div className="mb-8 text-center">
          <h1 className="mb-2 text-2xl font-semibold">◈ CodeMate</h1>
          <p className="text-text-secondary">选择会话或创建工作区</p>
        </div>

        <div className="mb-5 rounded-md border border-border bg-surface-2 p-4">
          <label className="mb-2 block text-sm font-medium">工作区目录</label>
          <div className="flex gap-2">
            <input
              value={workspace}
              onChange={(event) => setWorkspace(event.target.value)}
              placeholder="D:/All_of_mine/大学/项目/CodeMate"
              className="min-w-0 flex-1 rounded-md border border-border bg-surface-1 px-3 py-2 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-accent"
            />
            <button
              type="button"
              onClick={pickDirectory}
              disabled={pickingDirectory}
              className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface-3 px-3 py-2 text-sm transition-colors hover:bg-surface-1 disabled:opacity-50"
              title="打开系统目录选择器"
            >
              <FolderOpen className="h-4 w-4" />
              {pickingDirectory ? '选择中...' : '浏览'}
            </button>
          </div>
        </div>

        <div className="mb-6 space-y-3">
          {error && (
            <div className="rounded-md border border-status-error bg-red-50 p-3 text-sm text-status-error">
              {error}
            </div>
          )}

          {sessions.length === 0 ? (
            <div className="py-12 text-center text-text-muted">
              暂无会话，选择工作区目录后创建
            </div>
          ) : (
            sessions.map((session) => (
              <button
                key={session.session_id}
                onClick={() => loadSessionData(session.session_id)}
                className="w-full rounded-md bg-surface-2 p-4 text-left transition-colors hover:bg-surface-3"
              >
                <div className="mb-1 font-mono text-sm">{session.session_id}</div>
                {session.workspace && (
                  <div className="mb-1 truncate font-mono text-xs text-text-secondary">
                    {session.workspace}
                  </div>
                )}
                <div className="text-xs text-text-secondary">
                  更新于 {new Date(session.updated_at * 1000).toLocaleString()}
                </div>
              </button>
            ))
          )}
        </div>

        <button
          onClick={createSession}
          disabled={creating || pickingDirectory}
          className="w-full rounded-md bg-accent py-3 text-white transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {creating ? '创建中...' : '+ 创建工作区'}
        </button>
      </div>
    </div>
  );
}
