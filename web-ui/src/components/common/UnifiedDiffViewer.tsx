import { FileCode2 } from 'lucide-react';

interface DiffRow {
  kind: 'context' | 'added' | 'removed' | 'hunk' | 'meta';
  text: string;
  oldLine?: number;
  newLine?: number;
}

export interface UnifiedDiffViewerProps {
  diff: string;
  binary?: boolean;
  truncated?: boolean;
  className?: string;
  emptyMessage?: string;
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

export default function UnifiedDiffViewer({
  diff,
  binary = false,
  truncated = false,
  className = 'max-h-80',
  emptyMessage = '文件内容没有文本差异。',
}: UnifiedDiffViewerProps) {
  const rows = parseDiff(diff);

  if (binary) {
    return (
      <div className="flex items-center gap-2 rounded-lg bg-surface-3 px-3 py-3 text-xs text-text-secondary">
        <FileCode2 className="h-4 w-4 text-text-muted" />
        二进制文件无法显示文本差异。
      </div>
    );
  }

  if (rows.length === 0) {
    return <div className="rounded-lg bg-surface-3 px-3 py-3 text-xs text-text-secondary">{emptyMessage}</div>;
  }

  return (
    <>
      <div className={`overflow-auto rounded-lg border border-border bg-[#f7f8fa] py-1 font-mono text-[11px] leading-5 ${className}`}>
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
      {truncated && <p className="mt-2 text-[11px] text-text-muted">diff 较长，当前展示已截断。</p>}
    </>
  );
}
