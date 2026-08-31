import { useEffect, useMemo, useState } from 'react';
import { Archive, Check, GitBranch, History, RotateCcw, Save, Trash2, X } from 'lucide-react';
import { useStore } from '../../store';
import type { CodeCheckpoint, LaneGitState, LanePointer } from '../../types';

interface LaneCodeManagerModalProps {
  onClose: () => void;
}

function errorMessage(data: any, fallback: string): string {
  return data?.error?.message || fallback;
}

export default function LaneCodeManagerModal({ onClose }: LaneCodeManagerModalProps) {
  const { sessionId, lanes, currentLane, setSession, addToast } = useStore();
  const [allLanes, setAllLanes] = useState<LanePointer[]>(lanes);
  const [selectedLane, setSelectedLane] = useState(currentLane);
  const [gitState, setGitState] = useState<LaneGitState | null>(null);
  const [checkpoints, setCheckpoints] = useState<CodeCheckpoint[]>([]);
  const [selectedPaths, setSelectedPaths] = useState<string[]>([]);
  const [allowBlocked, setAllowBlocked] = useState(false);
  const [selectedCheckpoint, setSelectedCheckpoint] = useState('');
  const [discardChanges, setDiscardChanges] = useState(false);
  const [targetBranch, setTargetBranch] = useState('');
  const [publishMode, setPublishMode] = useState<'branch' | 'squash'>('branch');
  const [baseBranch, setBaseBranch] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  const selectedLanePointer = allLanes.find((lane) => lane.lane === selectedLane);
  const changedFiles = gitState?.changed_files || [];
  const blockedPaths = useMemo(
    () => new Set((gitState?.blocked_files || []).map((file) => file.path)),
    [gitState]
  );

  const syncSession = async () => {
    if (!sessionId) return;
    const response = await fetch(`/api/sessions/${sessionId}`);
    if (response.ok) setSession(sessionId, await response.json());
  };

  const loadLaneData = async (lane: string) => {
    if (!sessionId) return;
    const [statusResponse, checkpointResponse] = await Promise.all([
      fetch(`/api/sessions/${sessionId}/lanes/${lane}/status`),
      fetch(`/api/sessions/${sessionId}/lanes/${lane}/checkpoints`),
    ]);
    const statusData = await statusResponse.json();
    const checkpointData = await checkpointResponse.json();
    if (!statusResponse.ok) throw new Error(errorMessage(statusData, '读取代码状态失败'));
    if (!checkpointResponse.ok) throw new Error(errorMessage(checkpointData, '读取检查点失败'));
    const nextGitState = statusData.git || null;
    setGitState(nextGitState);
    setCheckpoints(checkpointData.checkpoints || []);
    setSelectedPaths(statusData.git?.changed_files || []);
    setSelectedCheckpoint(checkpointData.checkpoints?.[checkpointData.checkpoints.length - 1]?.checkpoint_id || '');
    setTargetBranch(nextGitState?.published_branch || `${lane}-result`);
    setPublishMode(nextGitState?.published_mode === 'squash' ? 'squash' : 'branch');
    setBaseBranch(nextGitState?.published_base_branch || '');
  };

  const loadLanes = async () => {
    if (!sessionId) return;
    const response = await fetch(`/api/sessions/${sessionId}/lanes?include_archived=true`);
    const data = await response.json();
    if (!response.ok) throw new Error(errorMessage(data, '读取 Lane 列表失败'));
    setAllLanes(data.lanes || []);
  };

  useEffect(() => {
    void (async () => {
      try {
        await loadLanes();
        await loadLaneData(selectedLane);
      } catch (loadError) {
        setMessage(loadError instanceof Error ? loadError.message : '读取代码状态失败');
      }
    })();
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId || !allLanes.some((lane) => lane.lane === selectedLane)) return;
    void loadLaneData(selectedLane).catch((loadError) => {
      setMessage(loadError instanceof Error ? loadError.message : '读取代码状态失败');
    });
  }, [selectedLane]);

  const request = async (url: string, options?: RequestInit) => {
    const response = await fetch(url, options);
    const data = await response.json();
    if (!response.ok) throw new Error(errorMessage(data, '操作失败'));
    return data;
  };

  const runAction = async (action: () => Promise<void>, success: string | (() => string)) => {
    setBusy(true);
    setMessage('');
    try {
      await action();
      await syncSession();
      await loadLanes();
      await loadLaneData(selectedLane);
      addToast({ type: 'success', message: typeof success === 'function' ? success() : success });
    } catch (actionError) {
      setMessage(actionError instanceof Error ? actionError.message : '操作失败');
    } finally {
      setBusy(false);
    }
  };

  const checkpoint = () => runAction(
    async () => {
      await request(`/api/sessions/${sessionId}/lanes/${selectedLane}/checkpoint`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ paths: selectedPaths, allow_blocked: allowBlocked }),
      });
    },
    '代码检查点已保存'
  );

  const restore = () => runAction(
    async () => {
      if (!selectedCheckpoint) throw new Error('请先选择检查点');
      if (discardChanges && !window.confirm('恢复将放弃当前未保存修改，是否继续？')) return;
      await request(`/api/sessions/${sessionId}/lanes/${selectedLane}/restore`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ checkpoint_id: selectedCheckpoint, discard_changes: discardChanges }),
      });
    },
    '已恢复代码检查点'
  );

  const discard = () => runAction(
    async () => {
      if (!window.confirm('将永久放弃当前工作区的未保存修改，是否继续？')) return;
      await request(`/api/sessions/${sessionId}/lanes/${selectedLane}/discard`, { method: 'POST' });
    },
    '未保存代码修改已放弃'
  );

  const publish = () => {
    let successMessage = 'Lane 已发布为普通 Git 分支';
    return runAction(
      async () => {
      if (!targetBranch.trim()) throw new Error('请输入发布目标分支名');
      const result = await request(`/api/sessions/${sessionId}/lanes/${selectedLane}/publish`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_branch: targetBranch, mode: publishMode, base_branch: baseBranch || null }),
      });
      successMessage = result.action === 'updated'
        ? '已更新发布分支'
        : result.action === 'unchanged'
          ? '发布分支已经是最新状态'
          : 'Lane 已发布为普通 Git 分支';
      },
      () => successMessage
    );
  };

  const archiveOrRestore = () => runAction(
    async () => {
      const endpoint = selectedLanePointer?.archived ? 'restore-lane' : 'archive';
      await request(`/api/sessions/${sessionId}/lanes/${selectedLane}/${endpoint}`, { method: 'POST' });
    },
    selectedLanePointer?.archived ? 'Lane 已恢复' : 'Lane 已归档'
  );

  const updatingPublishedBranch = Boolean(
    gitState?.published_branch && gitState.published_branch === targetBranch.trim()
  );
  const publishedBranchIsCurrent = Boolean(
    updatingPublishedBranch &&
    gitState?.published_lane_head &&
    gitState.published_lane_head === gitState.head_commit
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-lg bg-surface-2 shadow-pop">
        <div className="flex items-center justify-between border-b border-border p-4">
          <div>
            <h3 className="text-lg font-semibold">代码管理</h3>
            <p className="text-xs text-text-muted">检查点、恢复、发布与 Lane 生命周期</p>
          </div>
          <button onClick={onClose} className="rounded p-1 hover:bg-surface-3" aria-label="关闭代码管理">
            <X className="h-5 w-5 text-text-muted" />
          </button>
        </div>

        <div className="grid min-h-0 flex-1 gap-4 overflow-auto p-4 lg:grid-cols-[220px_1fr]">
          <div className="space-y-2">
            <div className="text-xs font-semibold text-text-muted">Lane</div>
            {allLanes.map((lane) => (
              <button
                key={lane.lane}
                onClick={() => setSelectedLane(lane.lane)}
                className={`flex w-full items-center gap-2 rounded-md border px-3 py-2 text-left text-sm ${selectedLane === lane.lane ? 'border-accent bg-blue-50' : 'border-border hover:bg-surface-3'}`}
              >
                <GitBranch className="h-4 w-4" />
                <span className="flex-1 truncate">{lane.lane}</span>
                {lane.archived && <span className="text-[10px] text-text-muted">归档</span>}
              </button>
            ))}
          </div>

          <div className="min-w-0 space-y-4">
            {gitState?.enabled ? (
              <>
                <div className="rounded-md border border-border bg-surface-1 p-3 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="font-medium">当前状态</span>
                    <span className={gitState.sync_state === 'clean' ? 'text-status-success' : 'text-status-warning'}>{gitState.sync_state}</span>
                  </div>
                  <div className="mt-2 font-mono text-xs text-text-muted">{gitState.managed_branch}</div>
                  <div className="mt-1 text-xs text-text-muted">Code Head: {gitState.short_head || '无'}</div>
                </div>

                <section className="rounded-md border border-border p-3">
                  <div className="mb-2 flex items-center justify-between">
                    <h4 className="flex items-center gap-2 font-medium"><Save className="h-4 w-4" />保存检查点</h4>
                    <button onClick={checkpoint} disabled={busy || selectedLanePointer?.archived} className="rounded bg-accent px-3 py-1.5 text-xs text-white disabled:opacity-50">保存</button>
                  </div>
                  {changedFiles.length ? changedFiles.map((path) => (
                    <label key={path} className="flex items-center gap-2 py-1 text-xs">
                      <input type="checkbox" checked={selectedPaths.includes(path)} onChange={(event) => setSelectedPaths((current) => event.target.checked ? [...current, path] : current.filter((item) => item !== path))} />
                      <span className="flex-1 font-mono">{path}</span>
                      {blockedPaths.has(path) && <span className="text-status-warning">需确认</span>}
                    </label>
                  )) : <div className="text-xs text-text-muted">当前没有未保存修改。</div>}
                  {blockedPaths.size > 0 && <label className="mt-2 flex items-center gap-2 text-xs text-status-warning"><input type="checkbox" checked={allowBlocked} onChange={(event) => setAllowBlocked(event.target.checked)} />我确认要提交已标记风险的文件</label>}
                </section>

                <section className="rounded-md border border-border p-3">
                  <h4 className="mb-2 flex items-center gap-2 font-medium"><History className="h-4 w-4" />检查点历史</h4>
                  <div className="flex gap-2">
                    <select value={selectedCheckpoint} onChange={(event) => setSelectedCheckpoint(event.target.value)} className="min-w-0 flex-1 rounded border border-border bg-surface-1 px-2 py-1.5 text-xs">
                      <option value="">选择检查点</option>
                      {checkpoints.slice().reverse().map((item) => <option key={item.checkpoint_id} value={item.checkpoint_id}>{item.commit_sha.slice(0, 8)} · {item.reason} · {new Date(item.created_at * 1000).toLocaleString()}</option>)}
                    </select>
                    <button onClick={restore} disabled={busy || !selectedCheckpoint || selectedLanePointer?.archived} className="flex items-center gap-1 rounded border border-border px-2 py-1 text-xs disabled:opacity-50"><RotateCcw className="h-3 w-3" />恢复</button>
                  </div>
                  <label className="mt-2 flex items-center gap-2 text-xs text-status-warning"><input type="checkbox" checked={discardChanges} onChange={(event) => setDiscardChanges(event.target.checked)} />恢复前放弃当前未保存修改</label>
                </section>

                <section className="rounded-md border border-border p-3">
                  <h4 className="mb-2 flex items-center gap-2 font-medium"><GitBranch className="h-4 w-4" />发布到用户 Git</h4>
                  <div className="grid gap-2 sm:grid-cols-2">
                    <input value={targetBranch} onChange={(event) => setTargetBranch(event.target.value)} placeholder="例如 feature/login" className="rounded border border-border bg-surface-1 px-2 py-1.5 text-xs" />
                    <select value={publishMode} disabled={updatingPublishedBranch} onChange={(event) => setPublishMode(event.target.value as 'branch' | 'squash')} className="rounded border border-border bg-surface-1 px-2 py-1.5 text-xs disabled:cursor-not-allowed disabled:opacity-60"><option value="branch">保留检查点历史</option><option value="squash">压缩为一个正式提交</option></select>
                  </div>
                  {publishMode === 'squash' && <input value={baseBranch} disabled={updatingPublishedBranch} onChange={(event) => setBaseBranch(event.target.value)} placeholder="基线分支（默认当前用户分支）" className="mt-2 w-full rounded border border-border bg-surface-1 px-2 py-1.5 text-xs disabled:cursor-not-allowed disabled:opacity-60" />}
                  <button onClick={publish} disabled={busy || selectedLanePointer?.archived || publishedBranchIsCurrent} className="mt-2 rounded bg-accent px-3 py-1.5 text-xs text-white disabled:opacity-50">{publishedBranchIsCurrent ? '发布分支已是最新' : updatingPublishedBranch ? '更新已发布分支' : '发布普通分支'}</button>
                  {gitState.published_branch && (
                    <div className="mt-2 space-y-1 text-xs text-status-success">
                      <div>已发布：{gitState.published_branch}</div>
                      <div className="text-text-muted">
                        {gitState.published_mode === 'squash' ? '增量压缩提交' : '保留检查点历史'}
                        {gitState.publication_count ? ` · 已发布 ${gitState.publication_count} 次` : ''}
                      </div>
                      {!publishedBranchIsCurrent && updatingPublishedBranch && <div className="text-status-warning">Lane 有新的检查点，可以继续更新该分支。</div>}
                    </div>
                  )}
                </section>

                <div className="flex items-center justify-between rounded-md border border-border p-3">
                  <button onClick={archiveOrRestore} disabled={busy || selectedLane === 'main' || selectedLane === currentLane} className="flex items-center gap-1 rounded border border-border px-3 py-1.5 text-xs disabled:opacity-50"><Archive className="h-3 w-3" />{selectedLanePointer?.archived ? '恢复 Lane' : '归档 Lane'}</button>
                  <button onClick={discard} disabled={busy || !changedFiles.length || selectedLanePointer?.archived} className="flex items-center gap-1 rounded border border-red-200 px-3 py-1.5 text-xs text-status-error disabled:opacity-50"><Trash2 className="h-3 w-3" />放弃未保存修改</button>
                </div>
              </>
            ) : <div className="rounded-md border border-border bg-surface-1 p-4 text-sm text-text-muted">当前工作区未绑定 Git，仅支持对话 Lane。</div>}
            {message && <div className="rounded-md border border-status-warning bg-amber-50 p-3 text-xs text-status-warning">{message}</div>}
            {!message && busy && <div className="flex items-center gap-2 text-xs text-text-muted"><Check className="h-3 w-3 animate-pulse" />正在处理代码状态...</div>}
          </div>
        </div>
      </div>
    </div>
  );
}
