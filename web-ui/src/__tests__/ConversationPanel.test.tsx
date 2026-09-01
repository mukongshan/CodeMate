import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import ConversationPanel from '../components/conversation/ConversationPanel';
import { useStore } from '../store';

describe('ConversationPanel', () => {
  it('sends messages using the current lane and renders history', async () => {
    const sendMessage = vi.fn();
    const interruptRun = vi.fn(() => true);
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
      runtimeError: {
        title: 'Agent 运行失败',
        message: 'LLM API unavailable',
        code: 'LLM_API_ERROR',
        retryable: true,
        suggestions: ['检查 API Key'],
        source: 'agent',
      },
    } as any);

    const user = userEvent.setup();
    render(<ConversationPanel sendMessage={sendMessage} interruptRun={interruptRun} />);

    await user.type(screen.getByRole('textbox'), 'new message');
    await user.keyboard('{Enter}');

    expect(sendMessage).toHaveBeenCalledWith('new message', 'feature-x');
    expect(screen.getByText('hello')).toBeInTheDocument();
    expect(screen.getByText('new message')).toBeInTheDocument();
    expect(screen.getByText('streaming reply')).toBeInTheDocument();
    expect(screen.getByText('Agent 运行失败')).toBeInTheDocument();
    expect(screen.getByText('LLM API unavailable')).toBeInTheDocument();
    expect(screen.getByText('错误码: LLM_API_ERROR')).toBeInTheDocument();
  });

  it('shows an interrupt button while the agent is running', async () => {
    const interruptRun = vi.fn(() => true);
    useStore.setState({
      currentLane: 'main',
      isRunning: true,
      lanes: [],
      entries: [],
      messages: [],
      toolCalls: new Map(),
      runtimeError: null,
    } as any);

    const user = userEvent.setup();
    render(<ConversationPanel sendMessage={vi.fn()} interruptRun={interruptRun} />);

    await user.click(screen.getByRole('button', { name: '中断' }));

    expect(interruptRun).toHaveBeenCalledOnce();
    expect(screen.getByRole('button', { name: '中断中...' })).toBeDisabled();
  });

  it('shows memory usage and tool wait activity while running', () => {
    useStore.setState({
      currentLane: 'main',
      isRunning: true,
      agentState: 'executing_tool',
      memoryBudget: {
        used_tokens: 7200,
        max_tokens: 8000,
        reserve_tokens: 2000,
        threshold_tokens: 6400,
        remaining_tokens: 800,
        utilization_ratio: 0.9,
      },
      lanes: [],
      entries: [],
      messages: [],
      toolCalls: new Map([
        ['tool-1', { call_id: 'tool-1', tool_name: 'read_file', args: {}, status: 'pending', lane: 'main' }],
      ]),
    } as any);

    render(<ConversationPanel sendMessage={vi.fn()} interruptRun={vi.fn(() => true)} />);

    expect(screen.getByText('7,200 / 8,000 tokens')).toBeInTheDocument();
    expect(screen.getByText('正在等待工具结果')).toBeInTheDocument();
    expect(screen.getByLabelText('Agent 正在运行')).toBeInTheDocument();
  });

  it('triggers manual memory compaction while idle', async () => {
    const compactSession = vi.fn(async () => true);
    useStore.setState({
      currentLane: 'main',
      isRunning: false,
      memoryBudget: {
        used_tokens: 6500,
        max_tokens: 8000,
        reserve_tokens: 2000,
        threshold_tokens: 6400,
        remaining_tokens: 1500,
        utilization_ratio: 0.8125,
      },
      lanes: [],
      entries: [],
      messages: [],
      toolCalls: new Map(),
    } as any);

    const user = userEvent.setup();
    render(
      <ConversationPanel
        sendMessage={vi.fn()}
        interruptRun={vi.fn(() => true)}
        compactSession={compactSession}
      />
    );

    await user.click(screen.getByRole('button', { name: '压缩记忆' }));

    expect(compactSession).toHaveBeenCalledWith('main');
  });

  it('does not render live messages from another lane', () => {
    useStore.setState({
      currentLane: 'feature-x',
      lanes: [],
      entries: [],
      messages: [
        {
          message_id: 'feature-live',
          role: 'assistant',
          content: '当前 Lane 的回复',
          timestamp: Date.now(),
          lane: 'feature-x',
        },
        {
          message_id: 'main-live',
          role: 'assistant',
          content: '主 Lane 的回复',
          timestamp: Date.now(),
          lane: 'main',
        },
      ],
    } as any);

    render(<ConversationPanel sendMessage={vi.fn()} interruptRun={vi.fn(() => true)} />);

    expect(screen.getByText('当前 Lane 的回复')).toBeInTheDocument();
    expect(screen.queryByText('主 Lane 的回复')).not.toBeInTheDocument();
  });
});
