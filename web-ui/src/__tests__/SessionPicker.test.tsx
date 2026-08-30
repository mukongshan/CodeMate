import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import SessionPicker from '../components/SessionPicker';
import { useStore } from '../store';

describe('SessionPicker', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('loads sessions and opens an existing snapshot', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          sessions: [
            { session_id: 'session-a', updated_at: 10, loaded: false },
          ],
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          session_id: 'session-a',
          current_lane: 'main',
          agent_state: 'idle',
          is_running: false,
          lanes: [{ lane: 'main', leaf_id: null, seq: 1, timestamp: 1, created_from: null, description: '' }],
          entries: [],
        }),
      });
    vi.stubGlobal('fetch', fetchMock as any);

    const user = userEvent.setup();
    render(<SessionPicker />);

    expect(await screen.findByText('session-a')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /session-a/i }));

    await waitFor(() => expect(useStore.getState().sessionId).toBe('session-a'));
    expect(useStore.getState().currentLane).toBe('main');
    expect(fetchMock).toHaveBeenCalledWith('/api/sessions/session-a');
  });

  it('creates a new session and loads its snapshot', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ sessions: [] }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ session_id: 'created-session' }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          session_id: 'created-session',
          current_lane: 'main',
          agent_state: 'idle',
          is_running: false,
          lanes: [{ lane: 'main', leaf_id: null, seq: 1, timestamp: 1, created_from: null, description: '' }],
          entries: [],
        }),
      });
    vi.stubGlobal('fetch', fetchMock as any);

    const user = userEvent.setup();
    render(<SessionPicker />);

    const buttons = await screen.findAllByRole('button');
    await user.click(buttons[buttons.length - 1]);

    await waitFor(() => expect(useStore.getState().sessionId).toBe('created-session'));
    expect(fetchMock).toHaveBeenCalledWith('/api/sessions', expect.objectContaining({ method: 'POST' }));
  });
});
