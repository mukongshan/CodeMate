import { Message } from '../../types';

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
        <div className="text-sm whitespace-pre-wrap break-words">
          {message.content}
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
