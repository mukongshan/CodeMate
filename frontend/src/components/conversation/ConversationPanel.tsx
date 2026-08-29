import { useState, useRef, useEffect } from 'react';
import { useStore } from '../../store';
import { Send } from 'lucide-react';
import MessageBubble from './MessageBubble';
import ToolCallCard from './ToolCallCard';

interface ConversationPanelProps {
  sendMessage: (content: string, lane?: string) => void;
}

export default function ConversationPanel({ sendMessage }: ConversationPanelProps) {
  const { messages, currentLane, isRunning, toolCalls, subagents } = useStore();
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // 自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // 自动调整 textarea 高度
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`;
    }
  }, [input]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isRunning) return;

    sendMessage(input.trim(), currentLane);
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
        {messages.map((message) => (
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

            <button
              type="submit"
              disabled={!input.trim() || isRunning}
              className="flex items-center gap-1.5 px-4 py-2 bg-accent text-white rounded-md hover:opacity-90 transition-opacity disabled:opacity-50"
            >
              <span className="text-sm">发送</span>
              <Send className="w-4 h-4" />
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
