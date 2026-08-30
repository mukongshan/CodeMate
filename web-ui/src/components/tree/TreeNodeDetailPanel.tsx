import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Bot, Hammer, User, X } from 'lucide-react';
import type { ContentBlock, Entry } from '../../types';
import { entryToMarkdown } from '../../utils/history';
import type { ConversationRound } from './TreeNode';

interface TreeNodeDetailPanelProps {
  round: ConversationRound;
  onClose: () => void;
}

interface ToolDetail {
  id: string;
  name: string;
  args?: Record<string, any>;
  result?: string;
  isError?: boolean;
}

export default function TreeNodeDetailPanel({
  round,
  onClose,
}: TreeNodeDetailPanelProps) {
  const tools = collectToolDetails(round);

  return (
    <div className="absolute right-3 top-3 z-20 flex max-h-[calc(100%-24px)] w-[380px] flex-col rounded-md border border-border bg-surface-1 shadow-lg">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <div className="min-w-0">
          <div className="text-sm font-medium">对话轮次详情</div>
          <div className="truncate text-[11px] font-mono text-text-muted">
            {round.id}
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded p-1 hover:bg-surface-2"
          title="关闭"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-auto p-3">
        <div className="mb-2 flex items-center gap-2 text-[11px] text-text-muted">
          <span>{round.lane}</span>
          <span>·</span>
          <span>{new Date(round.timestamp * 1000).toLocaleString('zh-CN')}</span>
          <span>·</span>
          <span>第 {round.depth + 1} 轮</span>
        </div>

        <MessageSection
          icon={<User className="h-3.5 w-3.5" />}
          title="用户消息"
          content={entryToMarkdown(round.user) || round.user.content || '(empty)'}
        />

        {round.assistants.map((assistant, index) => (
          <MessageSection
            key={assistant.id}
            icon={<Bot className="h-3.5 w-3.5" />}
            title={round.assistants.length > 1 ? `Agent 回复 ${index + 1}` : 'Agent 回复'}
            content={entryToMarkdown(assistant) || assistant.content || '(empty)'}
          />
        ))}

        {tools.length > 0 && (
          <div className="mt-3">
            <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-text-secondary">
              <Hammer className="h-3.5 w-3.5" />
              工具调用
            </div>
            <div className="space-y-2">
              {tools.map((tool, index) => (
                <details
                  key={`${tool.id}-${index}`}
                  className="rounded-md border border-border bg-surface-2"
                >
                  <summary className="cursor-pointer px-3 py-2 text-xs font-medium">
                    <span className={tool.isError ? 'text-status-error' : ''}>
                      {tool.name}
                    </span>
                  </summary>
                  <div className="border-t border-border p-3">
                    {tool.args && (
                      <>
                        <div className="mb-1 text-[11px] text-text-muted">参数</div>
                        <pre className="mb-3 max-h-32 overflow-auto rounded bg-surface-1 p-2 text-[11px]">
                          {JSON.stringify(tool.args, null, 2)}
                        </pre>
                      </>
                    )}
                    {tool.result && (
                      <>
                        <div className="mb-1 text-[11px] text-text-muted">结果</div>
                        <pre className="max-h-44 overflow-auto whitespace-pre-wrap rounded bg-surface-1 p-2 text-[11px]">
                          {tool.result}
                        </pre>
                      </>
                    )}
                  </div>
                </details>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function MessageSection({
  icon,
  title,
  content,
}: {
  icon: React.ReactNode;
  title: string;
  content: string;
}) {
  return (
    <div className="mb-3 rounded-md border border-border bg-surface-2 px-3 py-2">
      <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-text-secondary">
        {icon}
        {title}
      </div>
      <div className="prose prose-sm max-w-none text-sm text-text-primary">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
      </div>
    </div>
  );
}

function collectToolDetails(round: ConversationRound): ToolDetail[] {
  const toolUses = round.assistants.flatMap((entry) =>
    getBlocks(entry).filter((block) => block.kind === 'tool_use')
  );
  const toolResults = round.tools.flatMap((entry) =>
    getBlocks(entry).filter((block) => block.kind === 'tool_result')
  );
  const resultsById = new Map(
    toolResults.map((block) => [block.tool_call_id || '', block])
  );

  const details: ToolDetail[] = toolUses.map((block) => {
    const result = resultsById.get(block.id || '');
    return {
      id: block.id || block.name || 'tool',
      name: block.name || 'tool',
      args: block.arguments,
      result: result?.content,
      isError: result?.is_error,
    };
  });

  for (const block of toolResults) {
    if (!details.some((tool) => tool.id === block.tool_call_id)) {
      details.push({
        id: block.tool_call_id || 'tool-result',
        name: block.tool_call_id || 'tool result',
        result: block.content,
        isError: block.is_error,
      });
    }
  }

  return details;
}

function getBlocks(entry: Entry): ContentBlock[] {
  return Array.isArray(entry.full_content) ? entry.full_content : [];
}
