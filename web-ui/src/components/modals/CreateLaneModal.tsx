import { useState } from 'react';
import { useStore } from '../../store';
import { X } from 'lucide-react';

interface CreateLaneModalProps {
  onClose: () => void;
}

export default function CreateLaneModal({ onClose }: CreateLaneModalProps) {
  const { sessionId, lanes, currentLane, setSession, addToast } = useStore();
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);

  const validateName = (value: string): string | null => {
    if (!value) {
      return '分支名称不能为空';
    }
    if (!/^[a-z0-9-]+$/.test(value)) {
      return '仅限小写字母、数字、连字符';
    }
    if (value === 'main') {
      return 'main 是保留名称';
    }
    if (lanes.some(l => l.lane === value)) {
      return '分支名称已存在';
    }
    return null;
  };

  const handleNameChange = (value: string) => {
    setName(value);
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
      const currentLanePointer = lanes.find(l => l.lane === currentLane);
      const fromId = currentLanePointer?.leaf_id;

      const res = await fetch(`/api/sessions/${sessionId}/lanes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          from_id: fromId,
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
            <label className="block text-sm font-medium mb-2">从哪里分支</label>
            <div className="text-sm text-text-secondary">
              当前位置 ({currentLane})
            </div>
          </div>
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
