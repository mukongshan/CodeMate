import { useMemo, useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock3,
  FileText,
  Loader2,
  ListChecks,
  XCircle,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useStore } from '../../store';
import type { SubAgent } from '../../types';

const ACTIVE_STATUSES = new Set<SubAgent['status']>(['pending', 'running']);

const STATUS_LABELS: Record<SubAgent['status'], string> = {
  pending: '排队中',
  running: '运行中',
  completed: '已完成',
  partial: '部分完成',
  error: '失败',
  cancelled: '已取消',
  timeout: '已超时',
};

function StatusIcon({ status }: { status: SubAgent['status'] }) {
  if (status === 'pending' || status === 'running') {
    return <Loader2 className="h-4 w-4 animate-spin text-status-pending" />;
  }
  if (status === 'completed') {
    return <CheckCircle2 className="h-4 w-4 text-status-success" />;
  }
  if (status === 'partial') {
    return <AlertCircle className="h-4 w-4 text-status-warning" />;
  }
  return <XCircle className="h-4 w-4 text-status-error" />;
}

function formatDuration(duration?: number) {
  if (duration === undefined) return '—';
  if (duration < 1) return `${Math.round(duration * 1000)} ms`;
  return `${duration.toFixed(1)} s`;
}

function SubagentCard({ agent }: { agent: SubAgent }) {
  const [expanded, setExpanded] = useState(false);
  const details = agent.details;

  return (
    <div className="overflow-hidden rounded-md border border-border bg-surface-1">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-center gap-2.5 p-2.5 text-left hover:bg-surface-2"
        aria-expanded={expanded}
      >
        <div className="mt-0.5 shrink-0">
          <StatusIcon status={agent.status} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-text-primary">
              子Agent调查
            </span>
            <span className="rounded bg-surface-3 px-1.5 py-0.5 font-mono text-[11px] text-text-muted">
              {agent.subagent_id}
            </span>
            <span className="text-xs text-text-secondary">
              {STATUS_LABELS[agent.status]}
            </span>
          </div>
          <div className="mt-1 truncate text-sm text-text-secondary" title={agent.task}>
            {agent.task}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-text-muted">
            <span>步骤 {agent.step}/{agent.max_steps}</span>
            {agent.tool_name && <span>当前工具: {agent.tool_name}</span>}
            {agent.message && <span className="truncate">{agent.message}</span>}
          </div>
        </div>
        <div className="shrink-0 pt-0.5 text-text-muted">
          {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </div>
      </button>

      {expanded && (
        <div className="space-y-3 border-t border-border px-3 py-3">
          {agent.content && (
            <div className="text-sm text-text-primary">
              <div className="mb-1 flex items-center gap-1.5 text-xs font-medium text-text-muted">
                <ListChecks className="h-3.5 w-3.5" />
                最终结果
              </div>
              <div className="max-h-72 overflow-y-auto rounded bg-surface-2 p-2.5 leading-6">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                    ul: ({ children }) => <ul className="mb-2 ml-4 list-disc">{children}</ul>,
                    ol: ({ children }) => <ol className="mb-2 ml-4 list-decimal">{children}</ol>,
                    code: ({ children }) => (
                      <code className="rounded bg-surface-3 px-1 py-0.5 font-mono text-xs">
                        {children}
                      </code>
                    ),
                    pre: ({ children }) => (
                      <pre className="mb-2 overflow-x-auto rounded bg-surface-3 p-2 font-mono text-xs">
                        {children}
                      </pre>
                    ),
                  }}
                >
                  {agent.content}
                </ReactMarkdown>
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 gap-2 text-xs text-text-secondary sm:grid-cols-4">
            <div className="rounded bg-surface-2 p-2">
              <div className="flex items-center gap-1 text-text-muted"><ListChecks className="h-3.5 w-3.5" />工具调用</div>
              <div className="mt-1 font-medium">{details?.tool_calls ?? agent.step}</div>
            </div>
            <div className="rounded bg-surface-2 p-2">
              <div className="flex items-center gap-1 text-text-muted"><Clock3 className="h-3.5 w-3.5" />耗时</div>
              <div className="mt-1 font-medium">{formatDuration(details?.duration)}</div>
            </div>
            <div className="rounded bg-surface-2 p-2">
              <div className="flex items-center gap-1 text-text-muted"><FileText className="h-3.5 w-3.5" />访问文件</div>
              <div className="mt-1 font-medium">{details?.files_touched?.length ?? 0}</div>
            </div>
            <div className="rounded bg-surface-2 p-2">
              <div className="text-text-muted">Token</div>
              <div className="mt-1 font-medium">{details?.total_tokens ?? '—'}</div>
            </div>
          </div>

          {details?.files_touched && details.files_touched.length > 0 && (
            <div>
              <div className="mb-1 text-xs font-medium text-text-muted">访问路径</div>
              <div className="max-h-24 overflow-y-auto rounded bg-surface-2 p-2 font-mono text-xs text-text-secondary">
                {details.files_touched.map((path, index) => <div key={`${path}-${index}`} className="truncate" title={path}>{path}</div>)}
              </div>
            </div>
          )}

          {details?.summary_over_limit && (
            <div className="text-xs text-status-warning">
              结果超过 2000 字建议长度，已保留完整内容。
            </div>
          )}
          {details?.error && (
            <div className="whitespace-pre-wrap text-xs text-status-error">{details.error}</div>
          )}
        </div>
      )}
    </div>
  );
}

export default function SubagentPanel() {
  const { subagents } = useStore();
  const [expanded, setExpanded] = useState(false);
  const agents = useMemo(() => Array.from(subagents.values()), [subagents]);
  const activeCount = agents.filter((agent) => ACTIVE_STATUSES.has(agent.status)).length;

  if (agents.length === 0) return null;

  return (
    <section className="rounded-lg border border-accent/30 bg-accent/5 p-3" aria-label="子Agent运行面板">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-center justify-between text-left"
        aria-expanded={expanded}
      >
        <div>
          <h2 className="text-sm font-semibold text-text-primary">子Agent运行面板</h2>
          <p className="mt-0.5 text-xs text-text-muted">
            {activeCount > 0 ? `${activeCount} 个子Agent正在执行` : `${agents.length} 个子Agent已完成`}
          </p>
        </div>
        <div className="flex items-center gap-2 text-text-muted">
          <span className="rounded-full bg-surface-1 px-2 py-1 text-xs text-text-secondary">
            {agents.length}
          </span>
          {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </div>
      </button>
      {expanded && (
        <div className="mt-2 space-y-1.5">
          {agents.map((agent) => <SubagentCard key={agent.subagent_id} agent={agent} />)}
        </div>
      )}
    </section>
  );
}
