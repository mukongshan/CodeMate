import { memo } from 'react';
import { Handle, Position } from 'reactflow';
import { User, Bot, Wrench, UserSearch, GitBranch } from 'lucide-react';
import type { Entry } from '../../types';

interface TreeNodeProps {
  data: {
    entry: Entry;
    isHighlighted: boolean;
    laneColor: string;
  };
}

export default memo(function TreeNode({ data }: TreeNodeProps) {
  const { entry, isHighlighted, laneColor } = data;
  const toolNames = Array.isArray(entry.tool_names) ? entry.tool_names : [];

  const getRoleIcon = () => {
    switch (entry.role) {
      case 'user':
        return <User className="w-4 h-4" />;
      case 'assistant':
        return <Bot className="w-4 h-4" />;
      case 'tool':
        if (toolNames.includes('delegate_task')) {
          return <UserSearch className="w-4 h-4" />;
        }
        return <Wrench className="w-4 h-4" />;
      default:
        return null;
    }
  };

  const getTime = () => {
    const date = new Date(entry.timestamp * 1000);
    return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  };

  // 判断是否是分叉点
  const isFork = false; // TODO: 需要计算子节点数

  const borderColor = isHighlighted ? laneColor : 'rgba(11, 11, 11, 0.10)';
  const borderWidth = isFork ? '2px' : '1px';

  return (
    <div
      className="relative bg-surface-2 rounded-md shadow-card overflow-hidden"
      style={{
        border: `${borderWidth} solid ${borderColor}`,
        width: '280px',
        minHeight: '80px',
      }}
    >
      <Handle type="target" position={Position.Top} />

      <div className="p-3">
        {/* 头部：图标 + 角色 + 时间 */}
        <div className="flex items-center gap-2 mb-2">
          <div className="text-text-secondary">{getRoleIcon()}</div>
          <span className="text-xs text-text-secondary">
            {entry.role === 'user' ? 'User' : entry.role === 'assistant' ? 'Agent' : 'Tool'}
          </span>
          <span className="text-xs text-text-muted">·</span>
          <span className="text-xs text-text-muted">{getTime()}</span>

          {/* 状态点（仅 tool 节点） */}
          {entry.role === 'tool' && (
            <div className="ml-auto">
              {entry.is_error ? (
                <div className="w-2 h-2 rounded-full bg-status-error" />
              ) : (
                <div className="w-2 h-2 rounded-full bg-status-success" />
              )}
            </div>
          )}
        </div>

        {/* 内容摘要 */}
        <div className="text-sm text-text-primary mb-2 line-clamp-2">
          {entry.content}
        </div>

        {/* 工具名 */}
        {toolNames.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-2">
            {toolNames.slice(0, 1).map((name) => (
              <span
                key={name}
                className="text-xs px-2 py-0.5 bg-surface-3 rounded font-mono"
              >
                {name}
              </span>
            ))}
            {toolNames.length > 1 && (
              <span className="text-xs px-2 py-0.5 bg-surface-3 rounded">
                +{toolNames.length - 1}
              </span>
            )}
          </div>
        )}

        {/* 底部：Lane 标签 + 分叉标记 */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1">
            <div
              className="w-2 h-2 rounded-full"
              style={{ backgroundColor: laneColor }}
            />
            <span className="text-xs text-text-muted">{entry.lane}</span>
          </div>

          {isFork && (
            <GitBranch className="w-3 h-3 text-text-muted" />
          )}
        </div>
      </div>

      <Handle type="source" position={Position.Bottom} />
    </div>
  );
});
