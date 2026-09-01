import { useState } from 'react';
import {
  CheckCircle,
  ChevronDown,
  ChevronUp,
  FilePen,
  FileText,
  Loader2,
  Search,
  Terminal,
  Wrench,
  XCircle,
} from 'lucide-react';
import type { ToolCall } from '../../types';

interface ToolCallCardProps {
  toolCall?: ToolCall;
}

function getToolIcon(toolName: string) {
  switch (toolName) {
    case 'bash':
      return <Terminal className="h-3.5 w-3.5" />;
    case 'read_file':
      return <FileText className="h-3.5 w-3.5" />;
    case 'write_file':
    case 'edit_file':
      return <FilePen className="h-3.5 w-3.5" />;
    case 'glob':
    case 'grep':
      return <Search className="h-3.5 w-3.5" />;
    default:
      return <Wrench className="h-3.5 w-3.5" />;
  }
}

export default function ToolCallCard({ toolCall }: ToolCallCardProps) {
  const [expanded, setExpanded] = useState(false);

  if (!toolCall) return null;

  const getStatusIcon = () => {
    switch (toolCall.status) {
      case 'pending':
        return <Loader2 className="h-3.5 w-3.5 animate-spin text-status-pending" />;
      case 'success':
        return <CheckCircle className="h-3.5 w-3.5 text-status-success" />;
      case 'error':
        return <XCircle className="h-3.5 w-3.5 text-status-error" />;
    }
  };

  const getKeyArg = () => {
    switch (toolCall.tool_name) {
      case 'read_file':
      case 'write_file':
      case 'edit_file':
        return toolCall.args?.path;
      case 'bash':
        return toolCall.args?.command;
      case 'glob':
      case 'grep':
        return toolCall.args?.pattern;
      default:
        return null;
    }
  };

  const keyArg = getKeyArg();

  return (
    <div className={'overflow-hidden rounded-xl border bg-surface-1 transition-colors ' + (toolCall.status === 'error' ? 'border-status-error/40' : 'border-border')}>
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-center gap-2 px-2.5 py-2 text-left transition-colors hover:bg-surface-2"
        aria-expanded={expanded}
      >
        <span className="flex-none">{getStatusIcon()}</span>
        <span className="flex flex-none items-center gap-1.5 rounded-md bg-surface-3 px-1.5 py-0.5 text-text-secondary">
          {getToolIcon(toolCall.tool_name)}
          <span className="font-mono text-[11px] font-medium">{toolCall.tool_name}</span>
        </span>
        {keyArg && <span className="min-w-0 flex-1 truncate font-mono text-xs text-text-muted" title={String(keyArg)}>{String(keyArg)}</span>}
        {!keyArg && <span className="flex-1" />}
        <span className="flex-none text-text-muted">{expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}</span>
      </button>

      {expanded && (
        <div className="space-y-2 border-t border-border px-2.5 py-2">
          <div>
            <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-text-muted">参数</div>
            <pre className="max-h-48 overflow-auto rounded-lg bg-surface-3 p-2 text-xs leading-relaxed">{JSON.stringify(toolCall.args, null, 2)}</pre>
          </div>
          {toolCall.result && (
            <div>
              <div className={'mb-1 text-[11px] font-medium uppercase tracking-wide ' + (toolCall.status === 'error' ? 'text-status-error' : 'text-text-muted')}>
                {toolCall.status === 'error' ? '错误信息' : '返回'}
              </div>
              <pre className="max-h-60 overflow-auto rounded-lg bg-surface-3 p-2 text-xs leading-relaxed">{toolCall.result}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
