import { useState } from 'react';
import {
  CheckCheck,
  ChevronDown,
  ChevronUp,
  FileCode2,
  GitCompareArrows,
  Minus,
  Plus,
  Undo2,
  X,
} from 'lucide-react';
import { useStore } from '../../store';
import type { FileReview } from '../../types';

import UnifiedDiffViewer from '../common/UnifiedDiffViewer';
import ConfirmDialog from '../common/ConfirmDialog';

interface FileReviewCardProps {
  review: FileReview;
  busy: boolean;
  onAccept: (reviewId: string) => void;
  onReject: (reviewId: string) => void;
}

function FileReviewCard({ review, busy, onAccept, onReject }: FileReviewCardProps) {
  const [expanded, setExpanded] = useState(false);
  const { file_change: change } = review;
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
          <UnifiedDiffViewer
            diff={change.diff}
            binary={change.binary}
            truncated={change.truncated}
            emptyMessage="文件已写入，但没有可显示的文本差异。"
          />
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="text-xs text-text-muted">确认后，这张审查卡片会从当前视图移除。</span>
            <div className="flex shrink-0 items-center gap-2">
              <button
                type="button"
                onClick={() => onReject(review.review_id)}
                disabled={busy}
                className="inline-flex items-center gap-1.5 rounded-lg border border-rose-200 bg-rose-50 px-3 py-1.5 text-xs font-medium text-rose-700 shadow-sm transition-colors hover:bg-rose-100 disabled:opacity-50"
              >
                <Undo2 className="h-3.5 w-3.5" />
                拒绝并回滚
              </button>
              <button
                type="button"
                onClick={() => onAccept(review.review_id)}
                disabled={busy}
                className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white shadow-sm transition-colors hover:bg-accent/90 disabled:opacity-50"
              >
                <CheckCheck className="h-3.5 w-3.5" />
                接受变更
              </button>
            </div>
          </div>
        </div>
      )}
    </article>
  );
}

export default function FileReviewPanel() {
  const { sessionId, fileReviews, currentLane, acceptFileReview, acceptFileReviews, addToast } = useStore();
  const [expanded, setExpanded] = useState(false);
  const [busyReviewId, setBusyReviewId] = useState<string | null>(null);
  const [bulkAction, setBulkAction] = useState<'accept' | 'reject' | null>(null);
  const [confirmRejectAll, setConfirmRejectAll] = useState(false);
  const reviews = Array.from(fileReviews.values()).filter(
    (review) => review.lane === undefined || review.lane === currentLane
  );

  if (reviews.length === 0) return null;

  const reviewIds = reviews.map((review) => review.review_id);

  const runReviewAction = async (reviewId: string, action: 'accept' | 'reject') => {
    if (!sessionId) {
      addToast({ type: 'warning', message: '当前会话尚未连接，无法处理文件审查' });
      return;
    }
    setBusyReviewId(reviewId);
    try {
      const response = await fetch(
        `/api/sessions/${encodeURIComponent(sessionId)}/file-reviews/${encodeURIComponent(reviewId)}/${action}`,
        { method: 'POST' },
      );
      const data = await response.json();
      if (!response.ok) throw new Error(data?.detail || (action === 'reject' ? '拒绝文件修改失败' : '接受文件修改失败'));
      acceptFileReview(reviewId);
      addToast({ type: 'success', message: action === 'reject' ? '文件修改已拒绝并回滚' : '文件修改已接受' });
    } catch (actionError) {
      addToast({ type: 'warning', message: actionError instanceof Error ? actionError.message : '文件审查处理失败' });
    } finally {
      setBusyReviewId(null);
    }
  };

  const performBulkAction = async (action: 'accept' | 'reject') => {
    if (!sessionId) {
      addToast({ type: 'warning', message: '当前会话尚未连接，无法处理文件审查' });
      return;
    }
    setBulkAction(action);
    try {
      const response = await fetch(
        `/api/sessions/${encodeURIComponent(sessionId)}/file-reviews/${action === 'reject' ? 'reject-all' : 'accept-all'}`,
        { method: 'POST' },
      );
      const data = await response.json();
      if (!response.ok) throw new Error(data?.detail || (action === 'reject' ? '批量拒绝文件修改失败' : '批量接受文件修改失败'));
      acceptFileReviews(data.review_ids || reviewIds);
      addToast({ type: 'success', message: action === 'reject' ? '全部文件修改已拒绝并回滚' : '全部文件修改已接受' });
    } catch (actionError) {
      addToast({ type: 'warning', message: actionError instanceof Error ? actionError.message : '批量文件审查处理失败' });
    } finally {
      setBulkAction(null);
    }
  };

  const runBulkAction = (action: 'accept' | 'reject') => {
    if (action === 'reject') {
      setConfirmRejectAll(true);
      return;
    }
    void performBulkAction(action);
  };

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
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={(event) => { event.stopPropagation(); void runBulkAction('reject'); }}
              disabled={bulkAction !== null || busyReviewId !== null}
              className="inline-flex items-center gap-1 rounded-md border border-rose-200 bg-rose-50 px-2 py-1 text-xs font-medium text-rose-700 hover:bg-rose-100 disabled:opacity-50"
            >
              <X className="h-3 w-3" />全部拒绝
            </button>
            <button
              type="button"
              onClick={(event) => { event.stopPropagation(); void runBulkAction('accept'); }}
              disabled={bulkAction !== null || busyReviewId !== null}
              className="inline-flex items-center gap-1 rounded-md bg-accent px-2 py-1 text-xs font-medium text-white hover:bg-accent/90 disabled:opacity-50"
            >
              <CheckCheck className="h-3 w-3" />全部接受
            </button>
          </div>
          <span className="rounded-full bg-surface-1 px-2 py-1 text-xs text-text-secondary">{reviews.length}</span>
          {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </div>
      </button>
      {expanded && (
        <div className="mt-2 space-y-1.5">
          {reviews.map((review) => (
            <FileReviewCard
              key={review.review_id}
              review={review}
              busy={busyReviewId === review.review_id || bulkAction !== null}
              onAccept={(reviewId) => void runReviewAction(reviewId, 'accept')}
              onReject={(reviewId) => void runReviewAction(reviewId, 'reject')}
            />
          ))}
        </div>
      )}
      <ConfirmDialog open={confirmRejectAll} title="拒绝全部文件修改" message={`确定拒绝并回滚当前 ${reviews.length} 个文件修改吗？`} confirmLabel="全部拒绝" danger onCancel={() => setConfirmRejectAll(false)} onConfirm={() => { setConfirmRejectAll(false); void performBulkAction('reject'); }} />
    </section>
  );
}
