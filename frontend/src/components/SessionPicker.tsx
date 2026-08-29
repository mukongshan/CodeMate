import { useEffect, useState } from 'react';
import { useStore } from '../store';

interface Session {
  session_id: string;
  updated_at: number;
  loaded: boolean;
}

export default function SessionPicker() {
  const { setSession } = useStore();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    loadSessions();
  }, []);

  const loadSessions = async () => {
    try {
      const res = await fetch('http://localhost:8000/api/sessions');
      const data = await res.json();
      setSessions(data.sessions || []);
    } catch (error) {
      console.error('Failed to load sessions:', error);
    } finally {
      setLoading(false);
    }
  };

  const createSession = async () => {
    setCreating(true);
    try {
      const res = await fetch('http://localhost:8000/api/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      const data = await res.json();
      await loadSessionData(data.session_id);
    } catch (error) {
      console.error('Failed to create session:', error);
    } finally {
      setCreating(false);
    }
  };

  const loadSessionData = async (sessionId: string) => {
    try {
      const res = await fetch(`http://localhost:8000/api/sessions/${sessionId}`);
      const data = await res.json();
      setSession(sessionId, data);
    } catch (error) {
      console.error('Failed to load session data:', error);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-text-secondary">加载中...</div>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center h-screen bg-surface-1">
      <div className="w-full max-w-2xl p-8">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-semibold mb-2">◈ CodeMate</h1>
          <p className="text-text-secondary">选择会话或创建新会话</p>
        </div>

        <div className="space-y-3 mb-6">
          {sessions.length === 0 ? (
            <div className="text-center py-12 text-text-muted">
              暂无会话，点击下方创建新会话
            </div>
          ) : (
            sessions.map((session) => (
              <button
                key={session.session_id}
                onClick={() => loadSessionData(session.session_id)}
                className="w-full p-4 bg-surface-2 hover:bg-surface-3 rounded-md text-left transition-colors"
              >
                <div className="font-mono text-sm mb-1">{session.session_id}</div>
                <div className="text-xs text-text-secondary">
                  更新于 {new Date(session.updated_at * 1000).toLocaleString()}
                </div>
              </button>
            ))
          )}
        </div>

        <button
          onClick={createSession}
          disabled={creating}
          className="w-full py-3 bg-accent text-white rounded-md hover:opacity-90 transition-opacity disabled:opacity-50"
        >
          {creating ? '创建中...' : '+ 新建会话'}
        </button>
      </div>
    </div>
  );
}
