import { useState } from 'react';
import {
  CheckCheck,
  ChevronDown,
  ChevronUp,
  FileCode2,
  GitCompareArrows,
  Minus,
  Plus,
} from 'lucide-react';
import { useStore } from '../../store';
import type { FileChange, FileReview } from '../../types';

interface DiffRow {
  kind: 'context' | 'added' | 'removed' | 'hunk' | 'meta';
  text: string;
  oldLine?: number;
  newLine?: number;
}

function parseDiff(diff: string): DiffRow[] {
  let oldLine = 0;
  let newLine = 0;
  const rows: DiffRow[] = [];

  for (const line of diff.split(String.fromCharCode(10))) {
    if (line.startsWith('@@')) {
      const match = line.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
      if (match) {
        oldLine = Number(match[1]);
        newLine = Number(match[2]);
      }
      rows.push({ kind: 'hunk', text: line });
      continue;
    }
    if (line.startsWith('---') || line.startsWith('+++')) continue;
    if (line.startsWith('+')) {
      rows.push({ kind: 'added', text: line.slice(1), newLine: newLine++ });
      continue;
    }
    if (line.startsWith('-')) {
      rows.push({ kind: 'removed', text: line.slice(1), oldLine: oldLine++ });
      continue;
    }
    if (line.startsWith(' ')) {
      rows.push({ kind: 'context', text: line.slice(1), oldLine: oldLine++, newLine: newLine++ });
      continue;
    }
    if (line.trim()) rows.push({ kind: 'meta', text: line });
  }
  return rows;
}

function DiffViewer({ change }: { change: FileChange }) {
  const rows = parseDiff(change.diff);

  if (change.binary) {
    return (
      <div className="flex items-center gap-2 rounded-lg bg-surface-3 px-3 py-3 text-xs text-text-secondary">
        <FileCode2 className="h-4 w-4 text-text-muted" />
        二进制文件已修改，暂不展示文本 diff。
      </div>
    );
  }

  if (rows.length === 0) {
    return <div className="rounded-lg bg-surface-3 px-3 py-3 text-xs text-text-secondary">文件已写入，但没有可显示的文本差异。</div>;
  }

  return (
    <>
      <div className="max-h-80 overflow-auto rounded-lg border border-border bg-[#f7f8fa] py-1 font-mono text-[11px] leading-5">
        {rows.map((row, index) => {
          const rowClass = row.kind === 'added'
            ? 'flex min-w-max bg-emerald-50 text-emerald-950 shadow-[inset_3px_0_0_#22c55e]'
            : row.kind === 'removed'
              ? 'flex min-w-max bg-rose-50 text-rose-950 shadow-[inset_3px_0_0_#f43f5e]'
              : row.kind === 'hunk'
                ? 'min-w-max bg-accent/8 px-3 py-1 text-accent'
                : row.kind === 'meta'
                  ? 'min-w-max px-3 py-1 text-text-muted'
                  : 'flex min-w-max text-text-secondary';
          return (
            <div key={row.kind + '-' + index} className={rowClass}>
              {row.kind !== 'hunk' && row.kind !== 'meta' && (
                <>
                  <span className="w-11 flex-none select-none border-r border-black/5 px-2 text-right text-text-muted/70">{row.oldLine ?? ''}</span>
                  <span className="w-11 flex-none select-none border-r border-black/5 px-2 text-right text-text-muted/70">{row.newLine ?? ''}</span>
                  <span className="w-6 flex-none select-none px-2 text-center font-semibold opacity-70">{row.kind === 'added' ? '+' : row.kind === 'removed' ? '-' : ' '}</span>
                  <span className="whitespace-pre px-2">{row.text || ' '}</span>
                </>
              )}
              {row.kind === 'hunk' || row.kind === 'meta' ? row.text : null}
            </div>
          );
        })}
      </div>
      {change.truncated && <p className="mt-2 text-[11px] text-text-muted">diff 较长，当前展示已截断。</p>}
    </>
  );
}

function FileReviewCard({ review }: { review: FileReview }) {
  const [expanded, setExpanded] = useState(false);
  const { file_change: change } = review;
  const { acceptFileReview } = useStore();

  return (
    <article className="overflow-hidden rounded-md border border-border bg-surface-1 shadow-sm">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-center gap-2.5 p-2.5 text-left transition-colors hover:bg-surface-2"
        aria-expanded={expanded}
        aria-label={expanded ? '收起文件变更审查 ' + change.path : '展开文件变更审查 ' + change.path}
      >
        <FileCode2 className="h-4 w-4 shrink-0 text-accent" />
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-text-primary">{change.path}</span>
            <span className="rounded bg-surface-3 px-1.5 py-0.5 text-[11px] text-text-muted">{review.tool_name}</span>
          </span>
          <span className="mt-1 block text-xs text-text-secondary">等待你查看这次文件修改</span>
        </span>
        <span className="flex shrink-0 items-center gap-2 font-mono text-[11px]">
          <span className="inline-flex items-center gap-0.5 text-emerald-700"><Plus className="h-3 w-3" />{change.added_lines}</span>
          <span className="inline-flex items-center gap-0.5 text-rose-700"><Minus className="h-3 w-3" />{change.removed_lines}</span>
        </span>
        {expanded ? <ChevronUp className="h-4 w-4 shrink-0 text-text-muted" /> : <ChevronDown className="h-4 w-4 shrink-0 text-text-muted" />}
      </button>

      {expanded && (
        <div className="space-y-3 border-t border-border px-3 py-3">
          <DiffViewer change={change} />
          <div className="flex items-center justify-between gap-3">
            <span className="text-xs text-text-muted">确认后，这张审查卡片会从当前视图移除。</span>
            <button
              type="button"
              onClick={() => acceptFileReview(review.review_id)}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white shadow-sm transition-colors hover:bg-accent/90 focus:outline-none focus:ring-2 focus:ring-accent/30"
            >
              <CheckCheck className="h-3.5 w-3.5" />
              接受变更
            </button>
          </div>
        </div>
      )}
    </article>
  );
}

export default function FileReviewPanel() {
  const { fileReviews, currentLane } = useStore();
  const [expanded, setExpanded] = useState(false);
  const reviews = Array.from(fileReviews.values()).filter(
    (review) => review.lane === undefined || review.lane === currentLane
  );

  if (reviews.length === 0) return null;

  return (
    <section className="rounded-lg border border-accent/30 bg-accent/5 p-3" aria-label="文件变更审查面板">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-center justify-between text-left"
        aria-expanded={expanded}
        aria-label="文件变更审查面板"
      >
        <div className="flex items-start gap-2.5">
          <span className="mt-0.5 flex h-7 w-7 items-center justify-center rounded-lg bg-accent/10 text-accent">
            <GitCompareArrows className="h-4 w-4" />
          </span>
          <div>
            <h2 className="text-sm font-semibold text-text-primary">文件变更审查</h2>
            <p className="mt-0.5 text-xs text-text-muted">{reviews.length} 个文件等待确认</p>
          </div>
        </div>
        <div className="flex items-center gap-2 text-text-muted">
          <span className="rounded-full bg-surface-1 px-2 py-1 text-xs text-text-secondary">{reviews.length}</span>
          {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </div>
      </button>
      {expanded && (
        <div className="mt-2 space-y-1.5">
          {reviews.map((review) => <FileReviewCard key={review.review_id} review={review} />)}
        </div>
      )}
    </section>
  );
}
