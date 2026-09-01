import { useState } from 'react';
import { BrainCircuit, RefreshCw } from 'lucide-react';
import { useStore } from '../../store';

interface MemoryBudgetBarProps {
  compactSession: (lane?: string) => Promise<boolean>;
}

function formatTokens(value: number) {
  return value.toLocaleString('zh-CN');
}

export default function MemoryBudgetBar({ compactSession }: MemoryBudgetBarProps) {
  const { currentLane, memoryBudget, isRunning } = useStore();
  const [isCompacting, setIsCompacting] = useState(false);
  const used = Math.max(0, memoryBudget.used_tokens || 0);
  const max = Math.max(1, memoryBudget.max_tokens || 1);
  const threshold = Math.min(max, Math.max(0, memoryBudget.threshold_tokens || max));
  const percentage = Math.min(100, (used / max) * 100);
  const thresholdPercentage = Math.min(100, (threshold / max) * 100);
  const isNearLimit = used >= threshold;
  const isOverLimit = used >= max;

  const handleCompact = async () => {
    if (isRunning || isCompacting) return;
    setIsCompacting(true);
    try {
      await compactSession(currentLane);
    } finally {
      setIsCompacting(false);
    }
  };

  return (
    <div className="border-b border-border bg-surface-2/90 px-4 py-2.5">
      <div className="flex items-center gap-3">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <BrainCircuit className={`h-4 w-4 flex-none ${isOverLimit ? 'text-status-error' : isNearLimit ? 'text-status-warning' : 'text-accent'}`} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center justify-between gap-2 text-[11px]">
              <span className="font-medium text-text-secondary">当前记忆 · {currentLane}</span>
              <span className={`font-mono ${isOverLimit ? 'text-status-error' : isNearLimit ? 'text-status-warning' : 'text-text-muted'}`}>
                {formatTokens(used)} / {formatTokens(max)} tokens
              </span>
            </div>
            <div className="relative mt-1.5 h-1.5 overflow-hidden rounded-full bg-surface-3" aria-label="记忆预算使用量">
              <div
                className={`h-full rounded-full transition-all duration-500 ${isOverLimit ? 'bg-status-error' : isNearLimit ? 'bg-status-warning' : 'bg-accent'}`}
                style={{ width: `${percentage}%` }}
              />
              <div
                className="absolute inset-y-0 w-px bg-text-primary/40"
                style={{ left: `${thresholdPercentage}%` }}
                title={`自动压缩阈值 ${formatTokens(threshold)} tokens`}
              />
            </div>
          </div>
        </div>
        <button
          type="button"
          onClick={handleCompact}
          disabled={isRunning || isCompacting}
          className="flex flex-none items-center gap-1.5 rounded-lg border border-border bg-surface-1 px-2.5 py-1.5 text-xs text-text-secondary transition-colors hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-45"
          title={isRunning ? 'Agent 运行结束后才能手动压缩' : '立即压缩当前会话记忆'}
        >
          <RefreshCw className={`h-3.5 w-3.5 ${isCompacting ? 'animate-spin' : ''}`} />
          <span>{isCompacting ? '压缩中' : '压缩记忆'}</span>
        </button>
      </div>
      <div className="mt-1 flex justify-between pl-6 text-[10px] text-text-muted">
        <span>{isOverLimit ? '已超过预算，建议立即压缩' : isNearLimit ? '接近自动压缩阈值' : '自动压缩阈值'} · {formatTokens(threshold)}</span>
        <span>剩余 {formatTokens(Math.max(0, max - used))}</span>
      </div>
    </div>
  );
}
