import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import SubagentPanel from '../components/conversation/SubagentPanel';
import { useStore } from '../store';

describe('SubagentPanel', () => {
  it('keeps the panel compact and expands details on demand', async () => {
    useStore.setState({
      subagents: new Map([
        [
          'sub-1',
          {
            subagent_id: 'sub-1',
            task: '调查 Lane 管理实现',
            max_steps: 8,
            step: 3,
            tool_name: 'grep',
            status: 'running',
            message: '正在调用 grep',
          },
        ],
      ]),
    });

    const user = userEvent.setup();
    render(<SubagentPanel />);

    expect(screen.getByRole('heading', { name: '子Agent运行面板' })).toBeInTheDocument();
    const panelToggle = screen.getByRole('button', { name: /子Agent运行面板/ });
    expect(panelToggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('button', { name: /调查 Lane 管理实现/ })).not.toBeInTheDocument();

    await user.click(panelToggle);
    expect(screen.getByText('运行中')).toBeInTheDocument();
    expect(screen.getByText('步骤 3/8')).toBeInTheDocument();
    expect(screen.getByText('调查 Lane 管理实现')).toBeInTheDocument();
    const cardToggle = screen.getByRole('button', { name: /调查 Lane 管理实现/ });
    expect(cardToggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('最终结果')).not.toBeInTheDocument();

    act(() => {
      useStore.setState({
        subagents: new Map([
          [
            'sub-1',
            {
              subagent_id: 'sub-1',
              task: '调查 Lane 管理实现',
              max_steps: 8,
              step: 8,
              status: 'completed',
              content: '已完成调查，结果保留完整。',
              details: {
                tool_calls: 8,
                files_touched: ['backend/src/storage/lane_manager.py'],
                duration: 1.2,
                total_tokens: 120,
              },
            },
          ],
        ]),
      });
    });

    expect(screen.getByText('已完成')).toBeInTheDocument();
    await user.click(cardToggle);
    expect(screen.getByText('最终结果')).toBeInTheDocument();
    expect(screen.getByText('已完成调查，结果保留完整。')).toBeInTheDocument();
    expect(screen.getByText('backend/src/storage/lane_manager.py')).toBeInTheDocument();
  });
});
