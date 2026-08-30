import { useEffect, useState } from 'react';
import { Plus, ShieldCheck, Trash2, X } from 'lucide-react';
import { useStore } from '../../store';

interface PermissionGateModalProps {
  onClose: () => void;
}

export default function PermissionGateModal({ onClose }: PermissionGateModalProps) {
  const { sessionId, commandAllowlist, setCommandAllowlist } = useStore();
  const [commands, setCommands] = useState(commandAllowlist);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    setCommands(commandAllowlist);
  }, [commandAllowlist]);

  const addCommand = () => {
    const command = draft.trim().replace(/\s+/g, ' ').toLowerCase();
    if (!command || commands.includes(command)) return;
    setCommands([...commands, command]);
    setDraft('');
  };

  const save = async () => {
    if (!sessionId) return;
    setSaving(true);
    setError('');
    try {
      const response = await fetch(`/api/sessions/${sessionId}/permissions/gate`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command_allowlist: commands }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || `保存失败: HTTP ${response.status}`);
      }
      setCommandAllowlist(data.command_allowlist || []);
      onClose();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4">
      <div className="w-full max-w-lg rounded-md border border-border bg-surface-1 shadow-pop">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="flex items-center gap-2 font-medium">
            <ShieldCheck className="h-4 w-4 text-accent" />
            命令工具门禁
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

        <div className="space-y-4 p-4">
          <form
            className="flex gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              addCommand();
            }}
          >
            <input
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="例如 git status 或 pytest"
              className="min-w-0 flex-1 rounded-md border border-border bg-surface-2 px-3 py-2 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-accent"
            />
            <button
              type="submit"
              className="inline-flex items-center gap-1 rounded-md border border-border px-3 py-2 text-sm hover:bg-surface-2"
            >
              <Plus className="h-4 w-4" />
              添加
            </button>
          </form>

          <div className="max-h-64 space-y-1 overflow-auto">
            {commands.length === 0 ? (
              <div className="py-8 text-center text-sm text-text-muted">
                当前没有白名单命令
              </div>
            ) : (
              commands.map((command) => (
                <div
                  key={command}
                  className="flex items-center gap-2 rounded border border-border bg-surface-2 px-3 py-2"
                >
                  <code className="min-w-0 flex-1 truncate text-sm">{command}</code>
                  <button
                    type="button"
                    onClick={() => setCommands(commands.filter((item) => item !== command))}
                    className="rounded p-1 text-text-muted hover:bg-surface-3 hover:text-status-error"
                    title={`移除 ${command}`}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              ))
            )}
          </div>

          {error && <div className="text-sm text-status-error">{error}</div>}
        </div>

        <div className="flex justify-end gap-2 border-t border-border px-4 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-border px-3 py-2 text-sm hover:bg-surface-2"
          >
            取消
          </button>
          <button
            type="button"
            onClick={save}
            disabled={saving}
            className="rounded-md bg-accent px-3 py-2 text-sm text-white hover:opacity-90 disabled:opacity-50"
          >
            {saving ? '保存中...' : '保存'}
          </button>
        </div>
      </div>
    </div>
  );
}
