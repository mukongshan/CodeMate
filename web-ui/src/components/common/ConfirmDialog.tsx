import { AlertTriangle, CircleHelp } from 'lucide-react';

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmDialog({ open, title, message, confirmLabel = '确认', cancelLabel = '取消', danger = false, busy = false, onConfirm, onCancel }: ConfirmDialogProps) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/30 px-4" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onCancel(); }}>
      <div className="w-full max-w-md overflow-hidden rounded-lg border border-border bg-surface-2 shadow-pop animate-[fadeIn_0.15s_ease-out]" role="dialog" aria-modal="true" aria-labelledby="confirm-dialog-title" onMouseDown={(event) => event.stopPropagation()}>
        <div className="flex items-center gap-3 border-b border-border p-4">
          {danger ? <AlertTriangle className="h-5 w-5 shrink-0 text-status-warning" /> : <CircleHelp className="h-5 w-5 shrink-0 text-accent" />}
          <h3 id="confirm-dialog-title" className="text-base font-semibold text-text-primary">{title}</h3>
        </div>
        <p className="whitespace-pre-wrap p-4 text-sm leading-6 text-text-secondary">{message}</p>
        <div className="flex justify-end gap-2 border-t border-border p-4">
          <button type="button" onClick={onCancel} disabled={busy} className="rounded-md border border-border px-4 py-2 text-sm text-text-secondary transition-colors hover:bg-surface-3 disabled:cursor-not-allowed disabled:opacity-50">{cancelLabel}</button>
          <button type="button" onClick={onConfirm} disabled={busy} className={`rounded-md px-4 py-2 text-sm font-medium text-white transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${danger ? 'bg-status-error hover:opacity-90' : 'bg-accent hover:bg-accent/90'}`}>{busy ? '处理中…' : confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}
