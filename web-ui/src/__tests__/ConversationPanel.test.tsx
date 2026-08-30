import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import ConversationPanel from '../components/conversation/ConversationPanel';
import { useStore } from '../store';

describe('ConversationPanel', () => {
  it('sends messages using the current lane and renders history', async () => {
    const sendMessage = vi.fn();
    useStore.setState({
      currentLane: 'feature-x',
      isRunning: false,
      messages: [
        { message_id: 'm1', role: 'user', content: 'hello', timestamp: Date.now() },
      ],
      toolCalls: new Map(),
    } as any);

    const user = userEvent.setup();
    render(<ConversationPanel sendMessage={sendMessage} />);

    await user.type(screen.getByRole('textbox'), 'new message');
    await user.keyboard('{Enter}');

    expect(sendMessage).toHaveBeenCalledWith('new message', 'feature-x');
    expect(screen.getByText('hello')).toBeInTheDocument();
  });
});
