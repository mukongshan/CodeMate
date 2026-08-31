import { useEffect, useMemo, useRef, useState } from 'react';
import { useStore } from '../../store';
import { AlertTriangle, Send, Square, X } from 'lucide-react';
import MessageBubble from './MessageBubble';
import ToolCallCard from './ToolCallCard';
import SubagentPanel from './SubagentPanel';
import { getLaneConversation } from '../../utils/history';

interface ConversationPanelProps {
  sendMessage: (content: string, lane?: string) => void;
  interruptRun: () => boolean;
}

export default function ConversationPanel({ sendMessage, interruptRun }: ConversationPanelProps) {
  const {
    entries,
    lanes,
    messages,
    currentLane,
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
    if (messages.length === 0) return historyMessages;
    const historyIds = new Set(historyMessages.map((message) => message.message_id));
    const liveMessages = messages.filter(
      (message) =>
        (message.lane === undefined || message.lane === currentLane) &&
        !historyIds.has(message.message_id)
    );
    return [...historyMessages, ...liveMessages];
  }, [currentLane, historyMessages, messages]);

  // 自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [displayMessages.length, messages.at(-1)?.content]);

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

        {displayMessages.length === 0 && (
          <div className="h-full flex items-center justify-center text-sm text-text-muted">
            当前分支暂无对话
          </div>
        )}

        {displayMessages.map((message) => (
          <div key={message.message_id}>
            <MessageBubble message={message} />

            {/* 工具调用卡片 */}
            {message.tool_calls?.map((call) => (
              <div key={call.call_id} className="mt-2">
                <ToolCallCard toolCall={toolCalls.get(call.call_id)} />
              </div>
            ))}
          </div>
        ))}

        <SubagentPanel />

        <div ref={messagesEndRef} />
      </div>

      {/* 输入区 */}
      <div className="border-t border-border bg-surface-2 p-4">
        <form onSubmit={handleSubmit} className="flex flex-col gap-2">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={isRunning ? 'Agent 正在执行...' : '输入消息...'}
            disabled={isRunning}
            className="w-full px-3 py-2 bg-surface-1 border border-border rounded-md resize-none focus:outline-none focus:ring-2 focus:ring-accent disabled:opacity-50"
            rows={1}
            style={{ maxHeight: '150px' }}
          />

          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1 text-xs text-text-muted">
              <div className="w-2 h-2 rounded-full bg-lane-blue" />
              <span>{currentLane}</span>
            </div>

            {isRunning ? (
              <button
                type="button"
                onClick={() => {
                  if (interruptRun()) setInterrupting(true);
                }}
                disabled={interrupting}
                className="flex items-center gap-1.5 rounded-md border border-status-error bg-red-50 px-4 py-2 text-status-error transition-colors hover:bg-red-100 disabled:opacity-50"
              >
                <Square className="h-3.5 w-3.5 fill-current" />
                <span className="text-sm">{interrupting ? '中断中...' : '中断'}</span>
              </button>
            ) : (
              <button
                type="submit"
                disabled={!input.trim()}
                className="flex items-center gap-1.5 px-4 py-2 bg-accent text-white rounded-md hover:opacity-90 transition-opacity disabled:opacity-50"
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
