import { useStore } from '../../store';
import { AlertTriangle } from 'lucide-react';

interface PermissionModalProps {
  sendPermissionResponse: (requestId: string, action: string) => void;
}

export default function PermissionModal({ sendPermissionResponse }: PermissionModalProps) {
  const { permissionRequest, setPermissionRequest } = useStore();

  if (!permissionRequest) return null;

  const handleResponse = (action: 'allow_once' | 'allow_always' | 'deny') => {
    sendPermissionResponse(permissionRequest.request_id, action);
    setPermissionRequest(null);
  };

  const getRiskColor = () => {
    switch (permissionRequest.risk_level) {
      case 'low':
        return 'text-accent';
      case 'medium':
        return 'text-status-warning';
      case 'high':
        return 'text-status-error';
    }
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-50">
      <div className="bg-surface-2 rounded-lg shadow-pop w-full max-w-md mx-4 animate-[fadeIn_0.15s_ease-out]">
        {/* 头部 */}
        <div className="flex items-center gap-3 p-4 border-b border-border">
          <AlertTriangle className={`w-6 h-6 ${getRiskColor()}`} />
          <h3 className="text-lg font-semibold">需要确认</h3>
        </div>

        {/* 内容 */}
        <div className="p-4 space-y-3">
          <div className="text-sm">
            Agent 请求执行 <span className="font-mono font-semibold">{permissionRequest.tool_name}</span>
          </div>

          {/* 关键参数 */}
          {permissionRequest.args && Object.keys(permissionRequest.args).length > 0 && (
            <div className="bg-surface-3 p-3 rounded font-mono text-sm">
              {permissionRequest.tool_name === 'bash' && permissionRequest.args.command ? (
                <div>{permissionRequest.args.command}</div>
              ) : (
                <pre className="whitespace-pre-wrap">
                  {JSON.stringify(permissionRequest.args, null, 2)}
                </pre>
              )}
            </div>
          )}

          {/* 警告信息 */}
          {permissionRequest.warning && (
            <div className={`flex items-start gap-2 p-3 rounded ${
              permissionRequest.risk_level === 'high' ? 'bg-red-50' : 'bg-yellow-50'
            }`}>
              <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5 text-status-warning" />
              <div className="text-sm">{permissionRequest.warning}</div>
            </div>
          )}
        </div>

        {/* 按钮 */}
        <div className="flex gap-2 p-4 border-t border-border">
          <button
            onClick={() => handleResponse('deny')}
            className="flex-1 px-4 py-2 border border-border rounded-md hover:bg-surface-3 transition-colors"
          >
            拒绝
          </button>
          <button
            onClick={() => handleResponse('allow_once')}
            className="flex-1 px-4 py-2 bg-accent text-white rounded-md hover:opacity-90 transition-opacity"
          >
            本次允许
          </button>
          <button
            onClick={() => handleResponse('allow_always')}
            className="flex-1 px-4 py-2 bg-accent text-white rounded-md hover:opacity-90 transition-opacity"
          >
            总是允许
          </button>
        </div>
      </div>
    </div>
  );
}
