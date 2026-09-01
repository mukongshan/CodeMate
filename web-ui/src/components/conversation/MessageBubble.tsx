import { memo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Bot, User } from 'lucide-react';
import type { Message } from '../../types';

interface MessageBubbleProps {
  message: Message;
}

function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === 'user';

  return (
    <div className={`flex gap-2.5 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
      <div
        className={`mt-0.5 flex h-7 w-7 flex-none items-center justify-center rounded-full ${
          isUser ? 'bg-accent text-white' : 'border border-border bg-surface-2 text-text-secondary'
        }`}
      >
        {isUser ? <User className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
      </div>

      <div className={`flex min-w-0 max-w-[82%] flex-col ${isUser ? 'items-end' : 'items-start'}`}>
        <div
          className={`w-fit min-w-0 rounded-2xl px-3.5 py-2.5 shadow-sm ${
            isUser
              ? 'rounded-tr-sm bg-accent text-white'
              : 'rounded-tl-sm border border-border bg-surface-2 text-text-primary'
          }`}
        >
          <div className="text-sm leading-relaxed break-words [overflow-wrap:anywhere]">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                ul: ({ children }) => (
                  <ul className="mb-2 ml-4 list-disc space-y-1 last:mb-0">{children}</ul>
                ),
                ol: ({ children }) => (
                  <ol className="mb-2 ml-4 list-decimal space-y-1 last:mb-0">{children}</ol>
                ),
                li: ({ children }) => <li>{children}</li>,
                h1: ({ children }) => (
                  <h1 className="mb-2 mt-1 text-base font-semibold first:mt-0">{children}</h1>
                ),
                h2: ({ children }) => (
                  <h2 className="mb-2 mt-1 text-sm font-semibold first:mt-0">{children}</h2>
                ),
                h3: ({ children }) => (
                  <h3 className="mb-1.5 mt-1 text-sm font-semibold first:mt-0">{children}</h3>
                ),
                blockquote: ({ children }) => (
                  <blockquote
                    className={`mb-2 border-l-2 pl-3 last:mb-0 ${
                      isUser ? 'border-white/40' : 'border-border text-text-secondary'
                    }`}
                  >
                    {children}
                  </blockquote>
                ),
                hr: () => (
                  <hr className={`my-2.5 border-t ${isUser ? 'border-white/25' : 'border-border'}`} />
                ),
                table: ({ children }) => (
                  <div
                    className={`mb-2 max-w-full overflow-x-auto rounded-lg border last:mb-0 ${
                      isUser ? 'border-white/25' : 'border-border'
                    }`}
                  >
                    <table className="w-full border-collapse text-xs">{children}</table>
                  </div>
                ),
                thead: ({ children }) => (
                  <thead className={isUser ? 'bg-white/10' : 'bg-surface-3'}>{children}</thead>
                ),
                tr: ({ children }) => (
                  <tr
                    className={`border-b last:border-b-0 ${
                      isUser ? 'border-white/20' : 'border-border'
                    }`}
                  >
                    {children}
                  </tr>
                ),
                th: ({ children }) => (
                  <th className="whitespace-nowrap px-2.5 py-1.5 text-left font-semibold">
                    {children}
                  </th>
                ),
                td: ({ children }) => (
                  <td className="px-2.5 py-1.5 align-top">{children}</td>
                ),
                code: ({ children, className }) => {
                  const isBlock = typeof className === 'string' && className.includes('language-');
                  if (isBlock) {
                    return <code className={`${className} font-mono text-xs`}>{children}</code>;
                  }
                  return (
                    <code
                      className={`rounded px-1 py-0.5 font-mono text-[0.85em] ${
                        isUser ? 'bg-white/15' : 'bg-surface-3'
                      }`}
                    >
                      {children}
                    </code>
                  );
                },
                pre: ({ children }) => (
                  <pre
                    className={`mb-2 max-w-full overflow-x-auto rounded-lg p-2.5 font-mono text-xs leading-relaxed last:mb-0 ${
                      isUser ? 'bg-white/15' : 'border border-border bg-surface-3'
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
              <span
                aria-hidden
                className="ml-0.5 inline-block h-3.5 w-1.5 translate-y-[2px] animate-pulse rounded-sm bg-current align-baseline"
              />
            )}
          </div>
        </div>

        <span className="mt-1 px-1 text-[11px] tabular-nums text-text-muted">
          {new Date(message.timestamp).toLocaleTimeString('zh-CN', {
            hour: '2-digit',
            minute: '2-digit',
          })}
        </span>
      </div>
    </div>
  );
}

export default memo(MessageBubble);
