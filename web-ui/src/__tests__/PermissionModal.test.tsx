import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import PermissionModal from '../components/modals/PermissionModal';
import { useStore } from '../store';

describe('PermissionModal', () => {
  it('sends responses and clears the request', async () => {
    const sendPermissionResponse = vi.fn();
    useStore.setState({
      ...useStore.getState(),
      permissionRequest: {
        request_id: 'perm-1',
        tool_name: 'bash',
        args: { command: 'dir' },
        risk_level: 'high',
        warning: 'danger',
      },
    });

    const user = userEvent.setup();
    render(<PermissionModal sendPermissionResponse={sendPermissionResponse} />);

    await user.click(screen.getByRole('button', { name: '本次允许' }));
    expect(sendPermissionResponse).toHaveBeenCalledWith('perm-1', 'allow_once');
    expect(useStore.getState().permissionRequest).toBeNull();
  });
});
