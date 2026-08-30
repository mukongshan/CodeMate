import { useEffect, useState } from 'react';
import { ChevronRight, Folder, FolderOpen, HardDrive, X } from 'lucide-react';
import { useStore } from '../store';

interface Session {
  session_id: string;
  updated_at: number;
  loaded: boolean;
  workspace?: string;
}

interface DirectoryEntry {
  name: string;
  path: string;
}

export default function SessionPicker() {
  const { setSession } = useStore();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');
  const [workspace, setWorkspace] = useState(
    () => localStorage.getItem('codemate:last-workspace') || './workspace'
  );
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerLoading, setPickerLoading] = useState(false);
  const [pickerError, setPickerError] = useState('');
  const [pickerRoots, setPickerRoots] = useState<DirectoryEntry[]>([]);
  const [pickerChildren, setPickerChildren] = useState<DirectoryEntry[]>([]);
  const [pickerPath, setPickerPath] = useState('');
  const [pickerParent, setPickerParent] = useState<string | null>(null);

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

  const loadRoots = async () => {
    const res = await fetch('/api/filesystem/roots');
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || `Failed to load roots: HTTP ${res.status}`);
    }
    setPickerRoots(data.roots || []);
  };

  const loadDirectory = async (path: string) => {
    setPickerLoading(true);
    setPickerError('');
    try {
      const res = await fetch(`/api/filesystem/children?path=${encodeURIComponent(path)}`);
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || `Failed to load directory: HTTP ${res.status}`);
      }
      setPickerPath(data.path || path);
      setPickerParent(data.parent || null);
      setPickerChildren(data.children || []);
    } catch (error) {
      setPickerError(error instanceof Error ? error.message : 'Failed to load directory');
    } finally {
      setPickerLoading(false);
    }
  };

  const openDirectoryPicker = async () => {
    setPickerOpen(true);
    setPickerLoading(true);
    setPickerError('');
    try {
      await loadRoots();
      const trimmedWorkspace = workspace.trim();
      if (trimmedWorkspace) {
        await loadDirectory(trimmedWorkspace);
      } else {
        setPickerPath('');
        setPickerParent(null);
        setPickerChildren([]);
      }
    } catch (error) {
      setPickerError(error instanceof Error ? error.message : 'Failed to load directories');
    } finally {
      setPickerLoading(false);
    }
  };

  const usePickedDirectory = () => {
    if (!pickerPath) return;
    setWorkspace(pickerPath);
    setPickerOpen(false);
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
      <div className="flex items-center justify-center h-screen">
        <div className="text-text-secondary">加载中...</div>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center h-screen bg-surface-1">
      <div className="w-full max-w-2xl p-8">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-semibold mb-2">◈ CodeMate</h1>
          <p className="text-text-secondary">选择会话或创建工作区</p>
        </div>

        <div className="mb-5 bg-surface-2 border border-border rounded-md p-4">
          <label className="block text-sm font-medium mb-2">工作区目录</label>
          <div className="flex gap-2">
            <input
              value={workspace}
              onChange={(event) => setWorkspace(event.target.value)}
              placeholder="D:/All_of_mine/大学/项目/CodeMate"
              className="min-w-0 flex-1 px-3 py-2 bg-surface-1 border border-border rounded-md text-sm font-mono focus:outline-none focus:ring-2 focus:ring-accent"
            />
            <button
              type="button"
              onClick={openDirectoryPicker}
              className="inline-flex items-center gap-1.5 px-3 py-2 bg-surface-3 hover:bg-surface-1 border border-border rounded-md text-sm transition-colors"
              title="浏览目录"
            >
              <FolderOpen className="w-4 h-4" />
              浏览
            </button>
          </div>
        </div>

        <div className="space-y-3 mb-6">
          {error && (
            <div className="p-3 bg-red-50 border border-status-error rounded-md text-sm text-status-error">
              {error}
            </div>
          )}

          {sessions.length === 0 ? (
            <div className="text-center py-12 text-text-muted">
              暂无会话，输入工作区目录后创建
            </div>
          ) : (
            sessions.map((session) => (
              <button
                key={session.session_id}
                onClick={() => loadSessionData(session.session_id)}
                className="w-full p-4 bg-surface-2 hover:bg-surface-3 rounded-md text-left transition-colors"
              >
                <div className="font-mono text-sm mb-1">{session.session_id}</div>
                {session.workspace && (
                  <div className="text-xs text-text-secondary font-mono truncate mb-1">
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
          disabled={creating}
          className="w-full py-3 bg-accent text-white rounded-md hover:opacity-90 transition-opacity disabled:opacity-50"
        >
          {creating ? '创建中...' : '+ 创建工作区'}
        </button>
      </div>

      {pickerOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4">
          <div className="w-full max-w-3xl max-h-[80vh] flex flex-col bg-surface-1 border border-border rounded-md shadow-lg">
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <div className="flex items-center gap-2 min-w-0">
                <FolderOpen className="w-4 h-4 text-accent" />
                <div className="font-medium">选择工作区目录</div>
              </div>
              <button
                type="button"
                onClick={() => setPickerOpen(false)}
                className="p-1 rounded hover:bg-surface-2"
                title="关闭"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="border-b border-border px-4 py-3">
              <div className="flex items-center gap-2 text-xs text-text-secondary">
                <span className="shrink-0">当前目录</span>
                <div className="min-w-0 flex-1 truncate rounded bg-surface-2 px-2 py-1 font-mono">
                  {pickerPath || '请选择一个根目录'}
                </div>
                <button
                  type="button"
                  onClick={() => pickerParent && loadDirectory(pickerParent)}
                  disabled={!pickerParent}
                  className="px-2 py-1 rounded border border-border bg-surface-2 hover:bg-surface-3 disabled:opacity-40"
                >
                  上一级
                </button>
              </div>
              {pickerError && (
                <div className="mt-2 text-xs text-status-error">{pickerError}</div>
              )}
            </div>

            <div className="grid min-h-0 flex-1 grid-cols-[180px_1fr]">
              <div className="border-r border-border overflow-auto p-2">
                {pickerRoots.map((root) => (
                  <button
                    key={root.path}
                    type="button"
                    onClick={() => loadDirectory(root.path)}
                    className="flex w-full items-center gap-2 rounded px-2 py-2 text-left text-sm hover:bg-surface-2"
                  >
                    <HardDrive className="w-4 h-4 text-text-secondary" />
                    <span className="truncate">{root.name}</span>
                  </button>
                ))}
              </div>

              <div className="overflow-auto p-2">
                {pickerLoading ? (
                  <div className="py-10 text-center text-sm text-text-secondary">加载中...</div>
                ) : pickerChildren.length === 0 ? (
                  <div className="py-10 text-center text-sm text-text-secondary">
                    当前目录没有可进入的子目录
                  </div>
                ) : (
                  pickerChildren.map((child) => (
                    <button
                      key={child.path}
                      type="button"
                      onClick={() => loadDirectory(child.path)}
                      className="flex w-full items-center gap-2 rounded px-2 py-2 text-left text-sm hover:bg-surface-2"
                    >
                      <Folder className="w-4 h-4 text-accent" />
                      <span className="min-w-0 flex-1 truncate">{child.name}</span>
                      <ChevronRight className="w-4 h-4 text-text-muted" />
                    </button>
                  ))
                )}
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 border-t border-border px-4 py-3">
              <button
                type="button"
                onClick={() => setPickerOpen(false)}
                className="px-3 py-2 rounded-md border border-border bg-surface-2 hover:bg-surface-3 text-sm"
              >
                取消
              </button>
              <button
                type="button"
                onClick={usePickedDirectory}
                disabled={!pickerPath}
                className="px-3 py-2 rounded-md bg-accent text-white hover:opacity-90 disabled:opacity-40 text-sm"
              >
                使用此目录
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
