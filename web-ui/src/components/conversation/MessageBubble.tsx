import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Message } from '../../types';

interface MessageBubbleProps {
  message: Message;
}

export default function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === 'user';

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[80%] rounded-md p-3 ${
          isUser
            ? 'bg-accent text-white'
            : 'bg-surface-2 text-text-primary'
        }`}
      >
        <div className="text-sm break-words">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
              ul: ({ children }) => <ul className="mb-2 ml-4 list-disc">{children}</ul>,
              ol: ({ children }) => <ol className="mb-2 ml-4 list-decimal">{children}</ol>,
              li: ({ children }) => <li className="mb-1">{children}</li>,
              code: ({ children }) => (
                <code
                  className={`rounded px-1 py-0.5 font-mono text-xs ${
                    isUser ? 'bg-white/15' : 'bg-surface-3'
                  }`}
                >
                  {children}
                </code>
              ),
              pre: ({ children }) => (
                <pre
                  className={`mb-2 overflow-x-auto rounded p-2 font-mono text-xs ${
                    isUser ? 'bg-white/15' : 'bg-surface-3'
                  }`}
                >
                  {children}
                </pre>
              ),
              a: ({ children, href }) => (
                <a
                  href={href}
                  target="_blank"
                  rel="noreferrer"
                  className="underline underline-offset-2"
                >
                  {children}
                </a>
              ),
            }}
          >
            {message.content}
          </ReactMarkdown>
          {message.is_streaming && (
            <span className="inline-block w-2 h-4 ml-1 bg-current animate-pulse">▊</span>
          )}
        </div>

        <div className="flex items-center gap-2 mt-2 text-xs opacity-70">
          <span>
            {new Date(message.timestamp).toLocaleTimeString('zh-CN', {
              hour: '2-digit',
              minute: '2-digit',
              second: '2-digit',
            })}
          </span>
        </div>
      </div>
    </div>
  );
}
