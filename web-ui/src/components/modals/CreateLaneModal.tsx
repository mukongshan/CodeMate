import { useState } from 'react';
import { useStore } from '../../store';
import type { LaneNameSuggestion } from '../../types';
import { X } from 'lucide-react';

interface CreateLaneModalProps {
  onClose: () => void;
}

export default function CreateLaneModal({ onClose }: CreateLaneModalProps) {
  const { sessionId, lanes, currentLane, setSession, addToast } = useStore();
  const [name, setName] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [description, setDescription] = useState('');
  const [nameSource, setNameSource] = useState<'manual' | 'auto' | 'fallback'>('manual');
  const [suggestions, setSuggestions] = useState<LaneNameSuggestion[]>([]);
  const [suggesting, setSuggesting] = useState(false);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);
  const currentLanePointer = lanes.find(l => l.lane === currentLane);
  const gitState = currentLanePointer?.git;

  const validateName = (value: string): string | null => {
    if (!value) {
      return '分支名称不能为空';
    }
    if (value.length > 64) {
      return '分支名称不能超过 64 个字符';
    }
    if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value)) {
      return '仅限小写字母、数字，并使用单个连字符分隔';
    }
    if (value === 'main') {
      return 'main 是保留名称';
    }
    if (lanes.some(l => l.lane === value)) {
      return '分支名称已存在';
    }
    return null;
  };

  const handleSuggest = async () => {
    if (!sessionId) return;
    setSuggesting(true);
    try {
      const res = await fetch(`/api/sessions/${sessionId}/lanes/suggestions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ intent: description }),
      });
      const data = await res.json();
      if (res.ok) {
        setSuggestions(data.suggestions || []);
        if (!data.suggestions?.length) {
          addToast({ type: 'info', message: '暂时没有可用的命名建议' });
        }
      } else {
        addToast({ type: 'warning', message: data.detail || '暂时无法生成建议' });
      }
    } catch (requestError) {
      console.error('Failed to suggest lane names:', requestError);
      addToast({ type: 'warning', message: '暂时无法生成建议，可手动输入' });
    } finally {
      setSuggesting(false);
    }
  };

  const applySuggestion = (suggestion: LaneNameSuggestion) => {
    setName(suggestion.name);
    setDisplayName(suggestion.display_name);
    setDescription(suggestion.description);
    setNameSource(suggestion.source === 'fallback' ? 'fallback' : 'auto');
    setError('');
  };

  const handleNameChange = (value: string) => {
    setName(value);
    setNameSource('manual');
    const err = validateName(value);
    setError(err || '');
  };

  const handleCreate = async () => {
    const err = validateName(name);
    if (err) {
      setError(err);
      return;
    }

    setCreating(true);
    try {
      const fromId = currentLanePointer?.leaf_id;

      const res = await fetch(`/api/sessions/${sessionId}/lanes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          from_id: fromId,
          ...(displayName ? { display_name: displayName } : {}),
          ...(description ? { description } : {}),
          ...(nameSource !== 'manual' ? { name_source: nameSource } : {}),
        }),
      });

      if (res.ok) {
        const snapshot = await fetch(`/api/sessions/${sessionId}`);
        const snapshotData = await snapshot.json();
        if (snapshot.ok) {
          setSession(sessionId!, snapshotData);
        }
        addToast({ type: 'success', message: `已创建分支 ${name}` });
        onClose();
      } else {
        const data = await res.json();
        setError(data.error?.message || '创建失败');
      }
    } catch (error) {
      console.error('Failed to create lane:', error);
      setError('创建失败');
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-50">
      <div className="bg-surface-2 rounded-lg shadow-pop w-full max-w-md mx-4">
        {/* 头部 */}
        <div className="flex items-center justify-between p-4 border-b border-border">
          <h3 className="text-lg font-semibold">创建新分支</h3>
          <button
            onClick={onClose}
            className="p-1 hover:bg-surface-3 rounded transition-colors"
          >
            <X className="w-5 h-5 text-text-muted" />
          </button>
        </div>

        {/* 内容 */}
        <div className="p-4 space-y-4">
          <div>
            <label className="block text-sm font-medium mb-2">分支名称</label>
            <input
              aria-label="分支名称"
              type="text"
              value={name}
              onChange={(e) => handleNameChange(e.target.value)}
              placeholder="例如：cache-v1"
              className="w-full px-3 py-2 border border-border rounded-md focus:outline-none focus:ring-2 focus:ring-accent"
              autoFocus
            />
            {error ? (
              <div className="mt-1 text-xs text-status-error">{error}</div>
            ) : (
              <div className="mt-1 text-xs text-status-success">
                ✓ 仅限小写字母、数字、连字符
              </div>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium mb-2" htmlFor="lane-display-name">
              展示名称（可选）
            </label>
            <input
              id="lane-display-name"
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="例如：缓存优化方案"
              maxLength={80}
              className="w-full px-3 py-2 border border-border rounded-md focus:outline-none focus:ring-2 focus:ring-accent"
            />
          </div>

          <div>
            <div className="mb-2 flex items-center justify-between gap-2">
              <label className="block text-sm font-medium" htmlFor="lane-description">
                方案意图（可选）
              </label>
              <button
                type="button"
                onClick={handleSuggest}
                disabled={suggesting}
                className="rounded-md border border-accent px-2.5 py-1 text-xs text-accent transition-colors hover:bg-accent/10 disabled:opacity-50"
              >
                {suggesting ? '生成中...' : '智能建议'}
              </button>
            </div>
            <textarea
              id="lane-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="描述这个 Lane 要验证的方案，智能建议会参考它"
              maxLength={240}
              rows={3}
              className="w-full resize-none px-3 py-2 border border-border rounded-md focus:outline-none focus:ring-2 focus:ring-accent"
            />
            {suggestions.length > 0 && (
              <div className="mt-2 space-y-1.5">
                <div className="text-xs text-text-muted">选择一个候选后仍可继续编辑：</div>
                {suggestions.map((suggestion) => (
                  <button
                    type="button"
                    key={suggestion.name}
                    onClick={() => applySuggestion(suggestion)}
                    className="block w-full rounded-md border border-border bg-surface-1 px-3 py-2 text-left transition-colors hover:bg-surface-3"
                  >
                    <div className="flex items-center justify-between gap-2 text-sm">
                      <span className="font-medium">{suggestion.display_name}</span>
                      <span className="font-mono text-xs text-text-muted">{suggestion.name}</span>
                    </div>
                    {suggestion.description && (
                      <div className="mt-1 truncate text-xs text-text-secondary">{suggestion.description}</div>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">从哪里分支</label>
            <div className="text-sm text-text-secondary">
              当前位置 ({currentLane})
            </div>
          </div>

          {gitState?.enabled ? (
            <div className="rounded-md border border-border bg-surface-1 p-3 text-sm">
              <div className="font-medium">代码基线</div>
              <div className="mt-1 font-mono text-xs text-text-secondary">
                {gitState.short_head || '尚无检查点'}
              </div>
              <div className="mt-2 text-xs text-text-muted">
                创建前会保存当前安全修改，并为新 Lane 创建独立 Worktree。
              </div>
              {(gitState.changed_files?.length || 0) > 0 && (
                <div className="mt-2 text-xs text-status-warning">
                  待保存文件：{gitState.changed_files?.length}
                </div>
              )}
            </div>
          ) : (
            <div className="rounded-md border border-border bg-surface-1 p-3 text-xs text-text-muted">
              当前工作区未启用 Git，分支仅保存对话历史。
            </div>
          )}
        </div>

        {/* 按钮 */}
        <div className="flex gap-2 p-4 border-t border-border">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 border border-border rounded-md hover:bg-surface-3 transition-colors"
          >
            取消
          </button>
          <button
            onClick={handleCreate}
            disabled={!!error || creating || !name}
            className="flex-1 px-4 py-2 bg-accent text-white rounded-md hover:opacity-90 transition-opacity disabled:opacity-50"
          >
            {creating ? '创建中...' : '创建分支'}
          </button>
        </div>
      </div>
    </div>
  );
}
