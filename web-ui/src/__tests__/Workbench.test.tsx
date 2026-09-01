import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import ActivityBar from '../components/workbench/ActivityBar';
import { useStore } from '../store';
import { resetStore } from '../test/test-utils';

describe('Workbench activity bar', () => {
  beforeEach(() => {
    resetStore();
  });

  it('toggles the active side panel when the same tool is clicked', () => {
    render(<ActivityBar />);

    const explorer = screen.getByRole('button', { name: '资源管理器' });
    expect(explorer).toHaveAttribute('aria-pressed', 'true');
    expect(useStore.getState().activeWorkbenchView).toBe('explorer');

    fireEvent.click(explorer);

    expect(explorer).toHaveAttribute('aria-pressed', 'false');
    expect(useStore.getState().activeWorkbenchView).toBeNull();
  });

  it('opens and closes the terminal from the activity bar', () => {
    render(<ActivityBar />);

    const terminal = screen.getByRole('button', { name: '打开终端' });
    fireEvent.click(terminal);

    expect(useStore.getState().terminalOpen).toBe(true);
    expect(screen.getByRole('button', { name: '关闭终端' })).toHaveAttribute('aria-pressed', 'true');

    fireEvent.click(screen.getByRole('button', { name: '关闭终端' }));

    expect(useStore.getState().terminalOpen).toBe(false);
  });
});
