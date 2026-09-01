import { useEffect, useState } from 'react';
import { Pencil } from 'lucide-react';

interface InputDialogProps {
  open: boolean;
  title: string;
  message?: string;
  defaultValue?: string;
  placeholder?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  busy?: boolean;
  onConfirm: (value: string) => void;
  onCancel: () => void;
}

export default function InputDialog({ open, title, message, defaultValue = '', placeholder, confirmLabel = '保存', cancelLabel = '取消', busy = false, onConfirm, onCancel }: InputDialogProps) {
  const [value, setValue] = useState(defaultValue);
  useEffect(() => { if (open) setValue(defaultValue); }, [defaultValue, open]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/30 px-4" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onCancel(); }}>
      <form className="w-full max-w-md overflow-hidden rounded-lg border border-border bg-surface-2 shadow-pop animate-[fadeIn_0.15s_ease-out]" role="dialog" aria-modal="true" aria-labelledby="input-dialog-title" onSubmit={(event) => { event.preventDefault(); const nextValue = value.trim(); if (nextValue && !busy) onConfirm(nextValue); }} onMouseDown={(event) => event.stopPropagation()}>
        <div className="flex items-center gap-3 border-b border-border p-4"><Pencil className="h-5 w-5 shrink-0 text-accent" /><h3 id="input-dialog-title" className="text-base font-semibold text-text-primary">{title}</h3></div>
        <div className="space-y-3 p-4">{message && <p className="text-sm leading-6 text-text-secondary">{message}</p>}<input autoFocus value={value} onChange={(event) => setValue(event.target.value)} placeholder={placeholder} disabled={busy} className="w-full rounded-md border border-border bg-surface-1 px-3 py-2 text-sm text-text-primary outline-none transition-colors focus:border-accent disabled:opacity-50" aria-label={title} /></div>
        <div className="flex justify-end gap-2 border-t border-border p-4"><button type="button" onClick={onCancel} disabled={busy} className="rounded-md border border-border px-4 py-2 text-sm text-text-secondary transition-colors hover:bg-surface-3 disabled:cursor-not-allowed disabled:opacity-50">{cancelLabel}</button><button type="submit" disabled={busy || !value.trim()} className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-50">{busy ? '处理中…' : confirmLabel}</button></div>
      </form>
    </div>
  );
}
