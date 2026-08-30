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
      lanes: [
        { lane: 'feature-x', leaf_id: 'm1', seq: 1, timestamp: 1, created_from: null, description: '' },
      ],
      entries: [
        {
          id: 'm1',
          parent: null,
          lane: 'feature-x',
          seq: 1,
          role: 'user',
          content: 'hello',
          full_content: 'hello',
          tool_names: [],
          is_error: false,
          timestamp: Date.now() / 1000,
          tokens: 1,
        },
      ],
      messages: [
        {
          message_id: 'live-1',
          role: 'assistant',
          content: 'streaming reply',
          timestamp: Date.now(),
          is_streaming: true,
        },
      ],
      toolCalls: new Map(),
    } as any);

    const user = userEvent.setup();
    render(<ConversationPanel sendMessage={sendMessage} />);

    await user.type(screen.getByRole('textbox'), 'new message');
    await user.keyboard('{Enter}');

    expect(sendMessage).toHaveBeenCalledWith('new message', 'feature-x');
    expect(screen.getByText('hello')).toBeInTheDocument();
    expect(screen.getByText('streaming reply')).toBeInTheDocument();
  });
});
