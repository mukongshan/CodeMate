import { AgentState } from '../../types';
import { Loader2, Circle, Pause, CheckCircle, XCircle } from 'lucide-react';

interface AgentStatusBadgeProps {
  state: AgentState;
}

export default function AgentStatusBadge({ state }: AgentStatusBadgeProps) {
  const getStateConfig = () => {
    switch (state) {
      case 'idle':
        return {
          icon: <Circle className="w-4 h-4" />,
          label: '空闲',
          color: 'text-text-muted',
        };
      case 'preparing':
      case 'calling_llm':
      case 'executing_tool':
        return {
          icon: <Loader2 className="w-4 h-4 animate-spin" />,
          label: '执行中',
          color: 'text-accent',
        };
      case 'waiting_permission':
        return {
          icon: <Pause className="w-4 h-4" />,
          label: '等待确认',
          color: 'text-status-warning',
        };
      case 'completed':
        return {
          icon: <CheckCircle className="w-4 h-4" />,
          label: '完成',
          color: 'text-status-success',
        };
      case 'error':
        return {
          icon: <XCircle className="w-4 h-4" />,
          label: '错误',
          color: 'text-status-error',
        };
      default:
        return {
          icon: <Circle className="w-4 h-4" />,
          label: '未知',
          color: 'text-text-muted',
        };
    }
  };

  const config = getStateConfig();

  return (
    <div className="flex items-center gap-2 px-3 py-1.5 bg-surface-1 border border-border rounded-md">
      <div className={config.color}>{config.icon}</div>
      <span className="text-sm">{config.label}</span>
    </div>
  );
}
