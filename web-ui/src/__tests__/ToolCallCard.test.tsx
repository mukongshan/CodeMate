import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import ToolCallCard from '../components/conversation/ToolCallCard';

describe('ToolCallCard', () => {
  it('keeps ordinary tool details collapsed until the user opens them', async () => {
    const user = userEvent.setup();
    render(
      <ToolCallCard
        toolCall={{
          call_id: 'call-1',
          tool_name: 'edit_file',
          args: { path: 'src/app.ts' },
          status: 'success',
        }}
      />
    );

    expect(screen.queryByText('参数')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /edit_file/ }));
    expect(screen.getByText('参数')).toBeInTheDocument();
  });

  it('keeps error details collapsed until the user opens them', async () => {
    const user = userEvent.setup();
    render(
      <ToolCallCard
        toolCall={{
          call_id: 'call-2',
          tool_name: 'bash',
          args: { command: 'exit 1' },
          status: 'error',
          result: 'boom',
        }}
      />
    );

    expect(screen.queryByText('boom')).not.toBeInTheDocument();
    const toggle = screen.getByText('exit 1').closest('button') as HTMLButtonElement;
    expect(toggle).toHaveAttribute('aria-expanded', 'false');

    await user.click(toggle);

    expect(screen.getByText('boom')).toBeInTheDocument();
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
  });
});
