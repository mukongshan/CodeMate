import { useEffect, useMemo, useRef, useState } from 'react';
import { useStore } from '../../store';
import { AlertTriangle, MessageSquare, Send, Square, X } from 'lucide-react';
import MessageBubble from './MessageBubble';
import ToolCallCard from './ToolCallCard';
import SubagentPanel from './SubagentPanel';
import FileReviewPanel from './FileReviewPanel';
import MemoryBudgetBar from './MemoryBudgetBar';
import { getLaneConversation } from '../../utils/history';

interface ConversationPanelProps {
  sendMessage: (content: string, lane?: string) => void;
  interruptRun: () => boolean;
  compactSession?: (lane?: string) => Promise<boolean>;
}

export default function ConversationPanel({ sendMessage, interruptRun, compactSession }: ConversationPanelProps) {
  const compact = compactSession || (async () => false);
  const {
    entries,
    lanes,
    messages,
    currentLane,
    agentState,
    isRunning,
    toolCalls,
    runtimeError,
    addMessage,
    clearRuntimeError,
  } = useStore();
  const [input, setInput] = useState('');
  const [interrupting, setInterrupting] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const historyMessages = useMemo(
    () => getLaneConversation(entries, lanes, currentLane),
    [entries, lanes, currentLane]
  );
  const displayMessages = useMemo(() => {
    const historyIds = new Set(historyMessages.map((message) => message.message_id));
    const liveMessages = messages.filter(
      (message) =>
        (message.lane === undefined || message.lane === currentLane) &&
        !historyIds.has(message.message_id)
    );
    // 同一条用户消息可能同时以本地乐观 id 和后端 entry id 存在，按内容去重
    const historyUserContent = new Set(
      historyMessages.filter((m) => m.role === 'user').map((m) => m.content.trim())
    );
    const merged = [
      ...historyMessages,
      ...liveMessages.filter(
        (message) => message.role !== 'user' || !historyUserContent.has(message.content.trim())
      ),
    ];
    // 时间戳排序保证「用户提问在上、AI 回复在下」，同一毫秒时用户优先
    return merged
      .map((message, index) => ({ message, index }))
      .sort((a, b) => {
        const byTime = a.message.timestamp - b.message.timestamp;
        if (byTime !== 0) return byTime;
        if (a.message.role !== b.message.role) return a.message.role === 'user' ? -1 : 1;
        return a.index - b.index;
      })
      .map((item) => item.message);
  }, [currentLane, historyMessages, messages]);

  // 自动滚动到底部：流式输出期间用 auto，避免 smooth 动画和高频 delta 叠加导致抖动
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: isRunning ? 'auto' : 'smooth' });
  }, [displayMessages.length, messages.at(-1)?.content, isRunning]);

  // 自动调整 textarea 高度
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`;
    }
  }, [input]);

  useEffect(() => {
    if (!isRunning) {
      setInterrupting(false);
    }
  }, [isRunning]);

  const pendingToolCount = Array.from(toolCalls.values()).filter(
    (call) => call.lane === currentLane && call.status === 'pending'
  ).length;
  const activityLabel = agentState === 'waiting_permission'
    ? '等待你的确认'
    : agentState === 'executing_tool'
      ? pendingToolCount > 0 ? '正在等待工具结果' : '正在执行工具'
      : agentState === 'calling_llm'
        ? 'Agent 正在思考'
        : agentState === 'preparing'
          ? '正在整理上下文'
          : '正在处理任务';

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const content = input.trim();
    if (!content || isRunning) return;

    addMessage({
      message_id: `local-user-${Date.now()}`,
      role: 'user',
      content,
      timestamp: Date.now(),
      lane: currentLane,
    });
    sendMessage(content, currentLane);
    setInput('');
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  return (
    <div className="h-full flex flex-col bg-surface-1">
      <MemoryBudgetBar compactSession={compact} />

      {/* 消息列表 */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {runtimeError && (
          <div className="rounded-md border border-status-error bg-red-50 p-3 text-sm text-status-error">
            <div className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
              <div className="min-w-0 flex-1">
                <div className="font-medium">{runtimeError.title}</div>
                <div className="mt-1 whitespace-pre-wrap break-words text-red-700">
                  {runtimeError.message}
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-red-700">
                  {runtimeError.code && <span>错误码: {runtimeError.code}</span>}
                  {runtimeError.retryable && <span>可重试</span>}
                </div>
                {runtimeError.suggestions && runtimeError.suggestions.length > 0 && (
                  <ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-red-700">
                    {runtimeError.suggestions.map((suggestion) => (
                      <li key={suggestion}>{suggestion}</li>
                    ))}
                  </ul>
                )}
              </div>
              <button
                type="button"
                onClick={clearRuntimeError}
                className="rounded p-1 hover:bg-red-100"
                title="关闭错误提示"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}

        {displayMessages.length === 0 && !runtimeError && (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
            <MessageSquare className="h-8 w-8 text-text-muted opacity-40" />
            <div className="text-sm text-text-muted">当前分支暂无对话</div>
            <div className="text-xs text-text-muted opacity-70">
              在下方输入需求，Agent 会在 <span className="font-mono">{currentLane}</span> 分支上执行
            </div>
          </div>
        )}

        {displayMessages.map((message) => (
          <div key={message.message_id} className="space-y-2">
            {/* 纯工具调用轮次的载体消息没有正文，不渲染空气泡 */}
            {(message.content.trim().length > 0 || message.is_streaming) && (
              <MessageBubble message={message} />
            )}

            {/* 工具调用卡片 */}
            {message.tool_calls && message.tool_calls.length > 0 && (
              <div className="space-y-2 pl-9">
                {message.tool_calls.map((call) => (
                  <ToolCallCard key={call.call_id} toolCall={toolCalls.get(call.call_id)} />
                ))}
              </div>
            )}
          </div>
        ))}

        <FileReviewPanel />
        <SubagentPanel />

        {isRunning && (
          <div className="mx-1 flex items-center gap-3 rounded-xl border border-accent/20 bg-accent/5 px-4 py-3 text-sm text-text-secondary shadow-sm">
            <div className="relative flex h-6 w-6 flex-none items-center justify-center rounded-full bg-accent/10">
              <span className="absolute h-3 w-3 rounded-full bg-accent/20 animate-ping" />
              <span className="relative h-2 w-2 rounded-full bg-accent" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="font-medium text-text-primary">{activityLabel}</div>
              <div className="mt-0.5 flex items-center gap-1 text-xs text-text-muted">
                <span>请稍候</span>
                <span className="flex gap-0.5" aria-label="Agent 正在运行">
                  <span className="animate-bounce">·</span>
                  <span className="animate-bounce [animation-delay:120ms]">·</span>
                  <span className="animate-bounce [animation-delay:240ms]">·</span>
                </span>
              </div>
            </div>
            {pendingToolCount > 0 && (
              <span className="rounded-full bg-surface-3 px-2 py-1 font-mono text-[10px] text-text-muted">
                {pendingToolCount} 个工具
              </span>
            )}
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* 输入区 */}
      <div className="border-t border-border bg-surface-2 p-3">
        <form
          onSubmit={handleSubmit}
          className="flex flex-col gap-2 rounded-xl border border-border bg-surface-1 p-2.5 shadow-sm focus-within:border-accent focus-within:ring-1 focus-within:ring-accent/30"
        >
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={isRunning ? 'Agent 正在执行...' : '输入需求，Enter 发送 / Shift+Enter 换行'}
            disabled={isRunning}
            className="w-full resize-none bg-transparent px-1 text-sm leading-relaxed placeholder:text-text-muted focus:outline-none disabled:opacity-50"
            rows={1}
            style={{ maxHeight: '150px' }}
          />

          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-1.5 rounded-full bg-surface-3 px-2 py-0.5 text-xs text-text-secondary">
              <div className="h-1.5 w-1.5 rounded-full bg-lane-blue" />
              <span className="font-mono">{currentLane}</span>
            </div>

            {isRunning ? (
              <button
                type="button"
                onClick={() => {
                  if (interruptRun()) setInterrupting(true);
                }}
                disabled={interrupting}
                className="flex items-center gap-1.5 rounded-lg border border-status-error bg-red-50 px-3.5 py-1.5 text-status-error transition-colors hover:bg-red-100 disabled:opacity-50"
              >
                <Square className="h-3.5 w-3.5 fill-current" />
                <span className="text-sm">{interrupting ? '中断中...' : '中断'}</span>
              </button>
            ) : (
              <button
                type="submit"
                disabled={!input.trim()}
                className="flex items-center gap-1.5 rounded-lg bg-accent px-3.5 py-1.5 text-white shadow-sm transition-opacity hover:opacity-90 disabled:opacity-40"
              >
                <span className="text-sm">发送</span>
                <Send className="w-4 h-4" />
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
