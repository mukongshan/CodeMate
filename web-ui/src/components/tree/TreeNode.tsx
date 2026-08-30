import { memo } from 'react';
import { Handle, Position } from 'reactflow';
import { Bot, Hammer, User } from 'lucide-react';
import type { Entry } from '../../types';

export interface ConversationRound {
  id: string;
  lane: string;
  seq: number;
  depth: number;
  timestamp: number;
  user: Entry;
  assistants: Entry[];
  tools: Entry[];
  entryIds: string[];
}

interface TreeNodeProps {
  data: {
    round: ConversationRound;
    isHighlighted: boolean;
    laneColor: string;
  };
}

export default memo(function TreeNode({ data }: TreeNodeProps) {
  const { round, isHighlighted, laneColor } = data;
  const assistant = round.assistants.at(-1);
  const borderColor = isHighlighted ? laneColor : 'rgba(11, 11, 11, 0.12)';

  return (
    <div
      className="relative overflow-hidden rounded-md bg-surface-2 shadow-sm transition-shadow hover:shadow-card"
      style={{
        width: '204px',
        height: '86px',
        border: `1px solid ${borderColor}`,
      }}
    >
      <div
        className="absolute left-0 top-0 h-full w-1"
        style={{ backgroundColor: laneColor, opacity: isHighlighted ? 1 : 0.45 }}
      />

      <Handle
        type="target"
        position={Position.Top}
        className="!h-2 !w-2 !border-0"
        style={{ backgroundColor: laneColor }}
      />

      <div className="flex h-full flex-col gap-1 px-2.5 py-2 pl-3">
        <div className="flex items-center gap-1.5 text-[11px] leading-4 text-text-muted">
          <span className="font-medium text-text-secondary">{round.lane}</span>
          <span>·</span>
          <span>{new Date(round.timestamp * 1000).toLocaleTimeString('zh-CN', {
            hour: '2-digit',
            minute: '2-digit',
          })}</span>
          {round.tools.length > 0 && (
            <span className="ml-auto inline-flex items-center gap-1 rounded bg-surface-3 px-1.5 py-0.5 text-[10px] leading-3">
              <Hammer className="h-3 w-3" />
              {round.tools.length}
            </span>
          )}
        </div>

        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-[11px] leading-4 text-text-secondary">
            <User className="h-3.5 w-3.5 shrink-0" strokeWidth={2.2} />
            <span className="truncate">{round.user.content || '(empty)'}</span>
          </div>
          <div className="mt-0.5 flex items-center gap-1.5 text-xs leading-4 text-text-primary">
            <Bot className="h-3.5 w-3.5 shrink-0 text-text-secondary" strokeWidth={2.2} />
            <span className="truncate">{assistant?.content || '等待 Agent 回复'}</span>
          </div>
        </div>
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        className="!h-2 !w-2 !border-0"
        style={{ backgroundColor: laneColor }}
      />
    </div>
  );
});
