import { useState } from 'react';
import { ChevronDown, ChevronUp, Loader2, CheckCircle, XCircle } from 'lucide-react';
import type { ToolCall } from '../../types';

interface ToolCallCardProps {
  toolCall?: ToolCall;
}

export default function ToolCallCard({ toolCall }: ToolCallCardProps) {
  const [expanded, setExpanded] = useState(false);

  if (!toolCall) return null;

  const getStatusIcon = () => {
    switch (toolCall.status) {
      case 'pending':
        return <Loader2 className="w-4 h-4 animate-spin text-status-pending" />;
      case 'success':
        return <CheckCircle className="w-4 h-4 text-status-success" />;
      case 'error':
        return <XCircle className="w-4 h-4 text-status-error" />;
    }
  };

  const getKeyArg = () => {
    // 根据工具类型提取关键参数
    switch (toolCall.tool_name) {
      case 'read_file':
      case 'write_file':
      case 'edit_file':
        return toolCall.args.path;
      case 'bash':
        return toolCall.args.command?.substring(0, 50) + (toolCall.args.command?.length > 50 ? '...' : '');
      case 'glob':
        return toolCall.args.pattern;
      case 'grep':
        return toolCall.args.pattern;
      default:
        return null;
    }
  };

  const keyArg = getKeyArg();

  // error 卡片自动展开
  const shouldExpand = expanded || toolCall.status === 'error';

  return (
    <div className="border border-border rounded-md bg-surface-2 overflow-hidden">
      {/* 头部 */}
      <div className="flex items-center justify-between p-3">
        <div className="flex items-center gap-2 flex-1 min-w-0">
          {getStatusIcon()}
          <span className="text-sm font-mono font-medium">{toolCall.tool_name}</span>
          {toolCall.status === 'success' && (
            <span className="text-xs text-status-success">成功</span>
          )}
          {toolCall.status === 'error' && (
            <span className="text-xs text-status-error">失败</span>
          )}
        </div>

        <button
          onClick={() => setExpanded(!expanded)}
          className="p-1 hover:bg-surface-3 rounded transition-colors"
        >
          {shouldExpand ? (
            <ChevronUp className="w-4 h-4 text-text-muted" />
          ) : (
            <ChevronDown className="w-4 h-4 text-text-muted" />
          )}
        </button>
      </div>

      {/* 关键参数摘要 */}
      {keyArg && (
        <div className="px-3 pb-2">
          <div className="text-sm text-text-secondary font-mono truncate">
            {keyArg}
          </div>
        </div>
      )}

      {/* 展开内容 */}
      {shouldExpand && (
        <div className="border-t border-border p-3 space-y-2">
          {/* 参数 */}
          <div>
            <div className="text-xs text-text-muted mb-1">参数</div>
            <pre className="text-xs bg-surface-3 p-2 rounded overflow-x-auto">
              {JSON.stringify(toolCall.args, null, 2)}
            </pre>
          </div>

          {/* 返回结果 */}
          {toolCall.result && (
            <div>
              <div className="text-xs text-text-muted mb-1">
                {toolCall.status === 'error' ? '错误信息' : '返回'}
              </div>
              <pre className="text-xs bg-surface-3 p-2 rounded overflow-x-auto max-h-60 overflow-y-auto">
                {toolCall.result}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
