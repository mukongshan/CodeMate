import { useEffect, useState } from 'react';
import { Clock, MessageSquare, Pencil, Plus, Trash2, X } from 'lucide-react';
import { useStore } from '../../store';
import ConfirmDialog from '../common/ConfirmDialog';
import InputDialog from '../common/InputDialog';

interface SessionManagerModalProps {
  onClose: () => void;
}

interface SessionSummary {
  session_id: string;
  workspace_id: string;
  title: string;
  updated_at: number;
  loaded: boolean;
  workspace: string;
}

interface ConfirmRequest { title: string; message: string; confirmLabel?: string; danger?: boolean; onConfirm: () => void | Promise<void>; }
interface InputRequest { title: string; message?: string; defaultValue: string; onConfirm: (value: string) => void | Promise<void>; }

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

export default function SessionManagerModal({ onClose }: SessionManagerModalProps) {
  const { sessionId, workspaceId, workspace, setSession, clearSession, addToast } = useStore();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [sessionTitle, setSessionTitle] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [confirmRequest, setConfirmRequest] = useState<ConfirmRequest | null>(null);
  const [inputRequest, setInputRequest] = useState<InputRequest | null>(null);

  useEffect(() => {
    void loadSessions();
  }, [workspaceId]);

  const loadSessions = async () => {
    if (!workspaceId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError('');
    try {
      const response = await fetch(`/api/workspaces/${workspaceId}/sessions`);
      if (!response.ok) {
        throw new Error(await responseError(response, '加载会话失败'));
      }
      const payload = await response.json();
      setSessions(payload.sessions || []);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '加载会话失败');
    } finally {
      setLoading(false);
    }
  };

  const openSession = async (targetId: string) => {
    if (targetId === sessionId) {
      onClose();
      return;
    }
    setBusy(true);
    setError('');
    try {
      const response = await fetch(`/api/sessions/${targetId}`);
      if (!response.ok) {
        throw new Error(await responseError(response, '打开会话失败'));
      }
      setSession(targetId, await response.json());
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '打开会话失败');
    } finally {
      setBusy(false);
    }
  };

  const createSession = async () => {
    if (!workspaceId) return;
    setBusy(true);
    setError('');
    try {
      const response = await fetch(`/api/workspaces/${workspaceId}/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: sessionTitle.trim() || undefined }),
      });
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

  const applyRenameSession = async (session: SessionSummary, title: string) => {
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
    await loadSessions();
  };

  const renameSession = (session: SessionSummary) => {
    setInputRequest({ title: '重命名会话', message: '请输入新的会话名称。', defaultValue: session.title, onConfirm: (title) => applyRenameSession(session, title) });
  };

  const applyDeleteSession = async (session: SessionSummary) => {
    const response = await fetch(`/api/sessions/${session.session_id}`, {
      method: 'DELETE',
    });
    if (!response.ok) {
      setError(await responseError(response, '删除会话失败'));
      return;
    }
    if (session.session_id === sessionId) {
      addToast({ type: 'success', message: `已删除会话 ${session.title}` });
      clearSession();
      onClose();
      return;
    }
    await loadSessions();
  };

  const deleteSession = (session: SessionSummary) => {
    setConfirmRequest({ title: '删除会话', message: `彻底删除会话"${session.title}"及其托管 Lane 工作目录？`, confirmLabel: '彻底删除', danger: true, onConfirm: () => applyDeleteSession(session) });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4">
      <div className="flex max-h-[80vh] w-full max-w-lg flex-col rounded-md border border-border bg-surface-1 shadow-pop">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 font-medium">
              <MessageSquare className="h-4 w-4 text-accent" />
              会话管理
            </div>
            {workspace && (
              <div className="mt-0.5 truncate font-mono text-xs text-text-muted" title={workspace}>
                {workspace}
              </div>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 hover:bg-surface-2"
            title="关闭"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">
          <form
            className="flex gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              void createSession();
            }}
          >
            <input
              value={sessionTitle}
              onChange={(event) => setSessionTitle(event.target.value)}
              placeholder="会话名称（可选）"
              className="min-w-0 flex-1 rounded-md border border-border bg-surface-2 px-3 py-2 text-sm outline-none transition-colors focus:border-accent focus:ring-1 focus:ring-accent/30"
            />
            <button
              type="submit"
              disabled={busy}
              className="inline-flex flex-none items-center gap-1.5 rounded-md bg-accent px-3 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              <Plus className="h-4 w-4" />
              新建
            </button>
          </form>

          {error && <div className="text-sm text-status-error">{error}</div>}

          {loading ? (
            <div className="flex flex-1 items-center justify-center py-8 text-sm text-text-muted">
              加载中...
            </div>
          ) : (
            <div className="space-y-2">
              {sessions.map((session) => {
                const isActive = session.session_id === sessionId;
                return (
                  <div
                    key={session.session_id}
                    className={`group flex items-center gap-2 rounded-xl border p-2.5 transition-colors ${
                      isActive
                        ? 'border-accent/50 bg-accent/5'
                        : 'border-border bg-surface-2 hover:border-accent/40 hover:bg-surface-3'
                    }`}
                  >
                    <button
                      onClick={() => openSession(session.session_id)}
                      disabled={busy}
                      className="flex min-w-0 flex-1 items-center gap-3 text-left disabled:opacity-50"
                    >
                      <span className="flex-none rounded-lg bg-surface-1 p-2 text-accent">
                        <MessageSquare size={15} />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium">
                          {session.title}
                          {isActive && <span className="ml-1.5 text-xs text-status-success">· 当前</span>}
                        </span>
                        <span className="mt-0.5 flex items-center gap-1.5 text-xs text-text-muted">
                          <Clock size={11} className="flex-none" />
                          {formatRelativeTime(session.updated_at)}
                        </span>
                      </span>
                    </button>
                    <button
                      onClick={() => renameSession(session)}
                      className="flex-none rounded-lg p-2 text-text-muted transition-colors hover:bg-surface-1 hover:text-text-primary"
                      aria-label={`重命名 ${session.title}`}
                    >
                      <Pencil size={14} />
                    </button>
                    <button
                      onClick={() => deleteSession(session)}
                      className="flex-none rounded-lg p-2 text-text-muted transition-colors hover:bg-red-50 hover:text-status-error"
                      aria-label={`删除 ${session.title}`}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                );
              })}
              {sessions.length === 0 && (
                <div className="flex h-40 flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border text-center">
                  <MessageSquare size={24} className="text-text-muted opacity-40" />
                  <div className="text-sm text-text-muted">这个工作区还没有会话</div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
      <ConfirmDialog open={Boolean(confirmRequest)} title={confirmRequest?.title || ''} message={confirmRequest?.message || ''} confirmLabel={confirmRequest?.confirmLabel} danger={confirmRequest?.danger} busy={busy} onCancel={() => setConfirmRequest(null)} onConfirm={() => { const request = confirmRequest; setConfirmRequest(null); if (request) void request.onConfirm(); }} />
      <InputDialog open={Boolean(inputRequest)} title={inputRequest?.title || ''} message={inputRequest?.message} defaultValue={inputRequest?.defaultValue} busy={busy} onCancel={() => setInputRequest(null)} onConfirm={(value) => { const request = inputRequest; setInputRequest(null); if (request) void request.onConfirm(value); }} />
    </div>
  );
}
