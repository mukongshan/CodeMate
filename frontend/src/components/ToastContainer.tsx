import { useEffect } from 'react';
import { useStore } from '../store';
import { CheckCircle, XCircle, AlertTriangle, Info, X } from 'lucide-react';

export default function ToastContainer() {
  const { toasts, removeToast } = useStore();

  useEffect(() => {
    toasts.forEach((toast) => {
      const duration = toast.duration || 3000;
      const timer = setTimeout(() => {
        removeToast(toast.id);
      }, duration);

      return () => clearTimeout(timer);
    });
  }, [toasts]);

  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm">
      {toasts.slice(-3).map((toast) => {
        const getIcon = () => {
          switch (toast.type) {
            case 'success':
              return <CheckCircle className="w-5 h-5 text-status-success" />;
            case 'error':
              return <XCircle className="w-5 h-5 text-status-error" />;
            case 'warning':
              return <AlertTriangle className="w-5 h-5 text-status-warning" />;
            case 'info':
              return <Info className="w-5 h-5 text-accent" />;
          }
        };

        return (
          <div
            key={toast.id}
            className="bg-surface-2 border border-border rounded-lg shadow-pop p-4 flex items-start gap-3 animate-[slideIn_0.2s_ease-out]"
          >
            <div className="flex-shrink-0">{getIcon()}</div>
            <div className="flex-1 min-w-0">
              {toast.title && (
                <div className="font-medium text-sm mb-1">{toast.title}</div>
              )}
              <div className="text-sm text-text-secondary">{toast.message}</div>
            </div>
            <button
              onClick={() => removeToast(toast.id)}
              className="flex-shrink-0 p-1 hover:bg-surface-3 rounded transition-colors"
            >
              <X className="w-4 h-4 text-text-muted" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
