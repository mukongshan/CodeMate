import { useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent, type ReactNode } from 'react';
import {
  Check,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  FileCode2,
  Folder,
  FolderOpen,
  GitBranch,
  GitMerge,
  LoaderCircle,
  RefreshCw,
  Search,
  Send,
  Square,
  Trash2,
  X,
} from 'lucide-react';
import { useStore } from '../../store';
import type { EditorTab, GitStatusFile, LaneGitState, WorkbenchView, WorkspaceDirectoryPayload, WorkspaceFileEntry } from '../../types';
import TreeCanvas from '../tree/TreeCanvas';
import LaneCodeManagerModal from '../modals/LaneCodeManagerModal';
import UnifiedDiffViewer from '../common/UnifiedDiffViewer';
import ConfirmDialog from '../common/ConfirmDialog';

function getFileName(path: string) { return path.split('/').at(-1) || path; }
function makeTab(path: string): EditorTab { return { path, name: getFileName(path), content: null, originalContent: null, encoding: null, revision: null, binary: false, size: null, lines: null, loading: true, dirty: false, saving: false }; }

export function ExplorerPanel() {
  const { sessionId, currentLane, workspace, openEditorTab, updateEditorTab } = useStore();
  const [directories, setDirectories] = useState<Record<string, WorkspaceDirectoryPayload>>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set(['']));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const loadDirectory = async (path: string, force = false) => {
    if (!sessionId || (!force && directories[path])) return;
    setLoading(true); setError('');
    try {
      const response = await fetch('/api/sessions/' + sessionId + '/workspace/files?path=' + encodeURIComponent(path));
      const data = await response.json();
      if (!response.ok) throw new Error(data?.detail || '读取目录失败');
      setDirectories((current) => ({ ...current, [path]: data }));
    } catch (loadError) { setError(loadError instanceof Error ? loadError.message : '读取目录失败'); }
    finally { setLoading(false); }
  };

  useEffect(() => {
    setDirectories({}); setExpanded(new Set([''])); void loadDirectory('', true);
    const handler = () => { void loadDirectory('', true); };
    window.addEventListener('codemate:refresh-workspace', handler);
    return () => window.removeEventListener('codemate:refresh-workspace', handler);
  }, [sessionId, currentLane]);

  const openFile = async (entry: WorkspaceFileEntry) => {
    if (!sessionId) return;
    openEditorTab(makeTab(entry.path));
    try {
      const response = await fetch('/api/sessions/' + sessionId + '/workspace/file?path=' + encodeURIComponent(entry.path));
      const data = await response.json();
      if (!response.ok) throw new Error(data?.detail || '读取文件失败');
updateEditorTab(entry.path, { content: data.content, originalContent: data.content, encoding: data.encoding, revision: data.revision || null, binary: data.binary, size: data.size, lines: data.lines, loading: false, dirty: false, saving: false, error: undefined });
    } catch (loadError) { updateEditorTab(entry.path, { loading: false, error: loadError instanceof Error ? loadError.message : '读取文件失败' }); }
  };

  const toggleDirectory = async (entry: WorkspaceFileEntry) => {
    const next = new Set(expanded);
    if (next.has(entry.path)) next.delete(entry.path);
    else { next.add(entry.path); await loadDirectory(entry.path); }
    setExpanded(next);
  };

  const renderEntries = (path: string, depth: number): ReactNode[] => {
    const payload = directories[path]; if (!payload) return [];
    return payload.entries.map((entry) => {
      const directory = entry.kind === 'directory'; const isExpanded = expanded.has(entry.path);
      const Icon = directory ? (isExpanded ? FolderOpen : Folder) : FileCode2;
      return <div key={entry.path}><button type="button" onClick={() => (directory ? void toggleDirectory(entry) : void openFile(entry))} className="flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-[13px] text-text-secondary hover:bg-surface-3 hover:text-text-primary" style={{ paddingLeft: 8 + depth * 14 }} title={entry.path}>
        {directory ? (isExpanded ? <ChevronDown className="h-3.5 w-3.5 flex-none" /> : <ChevronRight className="h-3.5 w-3.5 flex-none" />) : <span className="h-3.5 w-3.5 flex-none" />}
        <Icon className={'h-4 w-4 flex-none ' + (directory ? 'text-amber-500' : 'text-accent')} /><span className="min-w-0 truncate">{entry.name}</span>
      </button>{directory && isExpanded ? renderEntries(entry.path, depth + 1) : null}</div>;
    });
  };

  const entries = useMemo(() => renderEntries('', 0), [directories, expanded]);
  return <div className="flex h-full min-h-0 flex-col"><div className="flex items-center justify-between border-b border-border px-3 py-2"><div className="min-w-0"><div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-text-muted">资源管理器</div><div className="mt-0.5 truncate font-mono text-[11px] text-text-secondary" title={workspace}>{currentLane}</div></div><button type="button" onClick={() => void loadDirectory('', true)} className="rounded p-1.5 text-text-muted hover:bg-surface-3 hover:text-text-primary" title="刷新文件树" aria-label="刷新文件树"><RefreshCw className={'h-4 w-4 ' + (loading ? 'animate-spin' : '')} /></button></div><div className="min-h-0 flex-1 overflow-y-auto px-1 py-2">{error && <div className="mx-2 mb-2 rounded border border-red-200 bg-red-50 px-2 py-1.5 text-xs text-status-error">{error}</div>}{!loading && !error && entries.length === 0 && <div className="px-3 py-4 text-xs text-text-muted">当前目录没有可展示的文件。</div>}{entries}</div></div>;
}

export function EditorArea() {
  const { sessionId, editorTabs, activeEditorPath, setActiveEditorPath, setEditorContent, updateEditorTab, closeEditorTab } = useStore();
  const [closeRequest, setCloseRequest] = useState<{ path: string; name: string } | null>(null);
  const activeTab = editorTabs.find((tab) => tab.path === activeEditorPath) || null;
  const closeEditor = (path: string) => { const tab = editorTabs.find((item) => item.path === path); if (tab?.dirty) { setCloseRequest({ path, name: tab.name }); return; } closeEditorTab(path); };
  const saveEditor = async () => {
    if (!sessionId || !activeTab || activeTab.content === null || activeTab.binary || !activeTab.dirty || activeTab.saving) return;
    updateEditorTab(activeTab.path, { saving: true, error: undefined });
    try {
      const response = await fetch('/api/sessions/' + sessionId + '/workspace/file', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: activeTab.path, content: activeTab.content, encoding: activeTab.encoding, expected_revision: activeTab.revision }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data?.detail || '保存文件失败');
      updateEditorTab(activeTab.path, { content: data.content, originalContent: data.content, encoding: data.encoding, revision: data.revision || null, size: data.size, lines: data.lines, dirty: false, saving: false, error: undefined });
      window.dispatchEvent(new Event('codemate:refresh-workspace'));
      window.dispatchEvent(new Event('codemate:refresh-source-control'));
    } catch (saveError) { updateEditorTab(activeTab.path, { saving: false, error: saveError instanceof Error ? saveError.message : '保存文件失败' }); }
  };
  useEffect(() => { const onKeyDown = (event: KeyboardEvent) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); void saveEditor(); } }; window.addEventListener('keydown', onKeyDown); return () => window.removeEventListener('keydown', onKeyDown); });
  const lines = activeTab?.content?.split(/\r?\n/) || [];
  return <section className="flex min-h-0 flex-1 flex-col bg-surface-1" aria-label="编辑器"><div className="flex min-h-10 items-end overflow-x-auto border-b border-border bg-surface-2">{editorTabs.map((tab) => <div key={tab.path} role="tab" tabIndex={0} aria-selected={tab.path === activeEditorPath} onClick={() => setActiveEditorPath(tab.path)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setActiveEditorPath(tab.path); } }} className={'group flex h-10 min-w-[150px] max-w-[240px] items-center gap-2 border-r border-border px-3 text-left text-xs ' + (tab.path === activeEditorPath ? 'border-t-2 border-t-accent bg-surface-1 text-text-primary' : 'text-text-muted hover:bg-surface-3')} title={tab.path}><FileCode2 className="h-3.5 w-3.5 flex-none text-accent" /><span className="min-w-0 flex-1 truncate">{tab.name}{tab.dirty ? ' *' : ''}</span>{tab.saving && <LoaderCircle className="h-3 w-3 animate-spin" />}<button type="button" onClick={(event) => { event.stopPropagation(); closeEditor(tab.path); }} onKeyDown={(event) => event.stopPropagation()} className="rounded p-0.5 opacity-0 hover:bg-surface-3 group-hover:opacity-100" aria-label={'关闭 ' + tab.name}><X className="h-3.5 w-3.5" /></button></div>)}</div><div className="flex min-h-9 items-center justify-between gap-3 border-b border-border px-4 py-1.5 text-[11px] text-text-muted"><span className="truncate font-mono">{activeTab?.path || '未打开文件'}</span><div className="flex flex-none items-center gap-2">{activeTab?.dirty && <span className="text-status-warning">未保存</span>}{activeTab?.saving && <span>保存中…</span>}{activeTab && <button type="button" onClick={() => void saveEditor()} disabled={!activeTab.dirty || activeTab.saving || activeTab.binary} className="rounded border border-border px-2 py-0.5 text-text-secondary disabled:opacity-40">保存</button>}{activeTab && <span className="rounded bg-blue-50 px-1.5 py-0.5 text-accent">{activeTab.binary ? '二进制' : '文本'}</span>}</div></div>{!activeTab && <div className="flex flex-1 items-center justify-center p-8 text-center"><div><FileCode2 className="mx-auto mb-3 h-10 w-10 text-text-muted" /><h2 className="text-base font-medium text-text-secondary">打开一个文件开始查看</h2><p className="mt-1 text-xs text-text-muted">从左侧资源管理器选择文件，内容会在这里显示。</p></div></div>}{activeTab && <div className="min-h-0 flex-1 overflow-auto bg-surface-1">{activeTab.loading ? <div className="flex items-center gap-2 p-4 text-text-muted"><LoaderCircle className="h-4 w-4 animate-spin" />正在读取文件…</div> : activeTab.error && !activeTab.content ? <div className="flex items-center gap-2 p-4 text-status-error"><CircleAlert className="h-4 w-4" />{activeTab.error}</div> : activeTab.binary ? <div className="p-4 text-text-muted">这是二进制文件，当前工作台暂不支持文本编辑。</div> : <div className="flex min-w-max p-3 font-mono text-[13px] leading-6"><div aria-hidden="true" className="select-none pr-5 text-right text-text-muted">{lines.map((_, index) => <div key={index}>{index + 1}</div>)}</div><textarea value={activeTab.content || ''} onChange={(event) => setEditorContent(activeTab.path, event.target.value)} spellCheck={false} className="min-h-[420px] min-w-[min(100%,720px)] flex-1 resize-none overflow-hidden bg-transparent text-text-primary outline-none" aria-label={'编辑 ' + activeTab.name} /></div>}{activeTab.error && activeTab.content && <div className="border-t border-amber-200 bg-amber-50 px-4 py-2 text-xs text-status-warning">{activeTab.error}，请确认外部修改后重试。</div>}</div>}</section>;
}

interface TerminalPanelProps {
  openTerminal: () => boolean;
  sendTerminalInput: (text: string) => boolean;
  signalTerminal: (signal?: string) => boolean;
  closeTerminal: () => void;
}

export function TerminalPanel({ openTerminal, sendTerminalInput, signalTerminal, closeTerminal }: TerminalPanelProps) {
  const { terminalHeight, setTerminalHeight, setTerminalOpen, currentLane, terminalSessionId, terminalStatus, terminalOutput, terminalError, clearTerminalOutput } = useStore();
  const [input, setInput] = useState('');
  const outputRef = useRef<HTMLPreElement>(null);
  const startResize = (event: ReactMouseEvent) => { event.preventDefault(); const startY = event.clientY; const startHeight = terminalHeight; const move = (moveEvent: MouseEvent) => setTerminalHeight(startHeight - (moveEvent.clientY - startY)); const stop = () => { document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', stop); }; document.addEventListener('mousemove', move); document.addEventListener('mouseup', stop); };
  useEffect(() => { if (terminalStatus === 'closed' && !terminalSessionId) openTerminal(); }, [openTerminal, terminalSessionId, terminalStatus]);
  const submit = () => { if (!input || terminalStatus !== 'ready') return; if (sendTerminalInput(input + '\n')) setInput(''); };
  return <section className="flex flex-none flex-col border-t border-border bg-surface-2" style={{ height: terminalHeight }} aria-label="终端面板"><div className="h-1 flex-none cursor-row-resize bg-transparent hover:bg-accent" onMouseDown={startResize} /><div className="flex h-9 flex-none items-center justify-between border-b border-border px-3"><div className="flex items-center gap-2 text-xs font-medium text-text-secondary"><TerminalIcon />终端<span className="font-mono text-[11px] text-text-muted">{currentLane}</span><span className="text-[11px] text-text-muted">{terminalStatus === 'ready' ? '已连接' : terminalStatus === 'connecting' ? '连接中…' : terminalStatus === 'error' ? '错误' : terminalStatus === 'exited' ? '已退出' : '未连接'}</span></div><div className="flex items-center gap-1"><button type="button" onClick={clearTerminalOutput} className="rounded p-1 text-text-muted hover:bg-surface-3" title="清空输出" aria-label="清空终端输出"><Trash2 className="h-3.5 w-3.5" /></button><button type="button" onClick={() => { signalTerminal('interrupt'); }} disabled={!terminalSessionId} className="rounded p-1 text-text-muted hover:bg-surface-3 disabled:opacity-40" title="中断进程" aria-label="中断终端进程"><Square className="h-3.5 w-3.5" /></button><button type="button" onClick={() => { closeTerminal(); setTerminalOpen(false); }} className="rounded p-1 text-text-muted hover:bg-surface-3" title="关闭终端" aria-label="关闭终端"><X className="h-4 w-4" /></button></div></div><pre ref={outputRef} className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap break-words bg-surface-1 p-3 font-mono text-xs leading-5 text-text-primary">{terminalError ? terminalError + '\n' : ''}{terminalOutput || (terminalStatus === 'connecting' ? '正在启动终端…' : '输入命令后回车执行')}</pre><form className="flex flex-none items-center gap-2 border-t border-border bg-surface-1 p-2" onSubmit={(event) => { event.preventDefault(); submit(); }}><span className="font-mono text-xs text-accent">&gt;</span><input value={input} onChange={(event) => setInput(event.target.value)} disabled={terminalStatus !== 'ready'} className="min-w-0 flex-1 bg-transparent font-mono text-xs text-text-primary outline-none disabled:opacity-50" placeholder={terminalStatus === 'ready' ? '输入终端命令…' : '等待终端连接…'} aria-label="终端输入" /><button type="submit" disabled={!input || terminalStatus !== 'ready'} className="rounded p-1.5 text-accent hover:bg-blue-50 disabled:opacity-40" title="发送命令" aria-label="发送终端命令"><Send className="h-4 w-4" /></button></form></section>;
}
function TerminalIcon() { return <span className="font-mono text-sm">&gt;_</span>; }

export function SourceControlPanel() {
  const { sessionId, currentLane, lanes, addToast, setShowCompareDrawer } = useStore();
  const [gitState, setGitState] = useState<LaneGitState | null>(null);
  const [gitFiles, setGitFiles] = useState<GitStatusFile[]>([]);
  const [selectedPaths, setSelectedPaths] = useState<string[]>([]);
  const [commitMessage, setCommitMessage] = useState('');
  const [diff, setDiff] = useState('');
  const [diffBinary, setDiffBinary] = useState(false);
  const [diffTruncated, setDiffTruncated] = useState(false);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [showManager, setShowManager] = useState(false);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const lane = lanes.find((item) => item.lane === currentLane);

  const refresh = async () => {
    if (!sessionId) return;
    setLoading(true);
    try {
      const [laneResponse, gitResponse] = await Promise.all([
        fetch('/api/sessions/' + sessionId + '/lanes/' + encodeURIComponent(currentLane) + '/status'),
        fetch('/api/sessions/' + sessionId + '/lanes/' + encodeURIComponent(currentLane) + '/git/status'),
      ]);
      const laneData = await laneResponse.json();
      const gitData = await gitResponse.json();
      setGitState(laneData.git || null);
      setGitFiles(gitData.files || []);
      setSelectedPaths((current) => current.filter((path) => (gitData.files || []).some((file: GitStatusFile) => file.path === path)));
    } catch (loadError) {
      setGitState(null);
      setGitFiles([]);
      addToast({ type: 'warning', message: loadError instanceof Error ? loadError.message : '读取 Git 状态失败' });
    } finally { setLoading(false); }
  };

  useEffect(() => {
    void refresh();
    const handler = () => { void refresh(); };
    window.addEventListener('codemate:refresh-source-control', handler);
    return () => window.removeEventListener('codemate:refresh-source-control', handler);
  }, [sessionId, currentLane]);

  const mutateGit = async (action: 'stage' | 'unstage') => {
    if (!sessionId || !selectedPaths.length) return;
    setBusy(true);
    try {
      const response = await fetch('/api/sessions/' + sessionId + '/lanes/' + encodeURIComponent(currentLane) + '/git/' + action, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ paths: selectedPaths }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data?.detail || 'Git 操作失败');
      setGitFiles(data.files || []);
      setSelectedPaths([]);
      addToast({ type: 'success', message: action === 'stage' ? '文件已暂存' : '已取消暂存' });
    } catch (actionError) { addToast({ type: 'warning', message: actionError instanceof Error ? actionError.message : 'Git 操作失败' }); }
    finally { setBusy(false); }
  };

  const commit = async () => {
    if (!sessionId || !commitMessage.trim()) return;
    setBusy(true);
    try {
      const response = await fetch('/api/sessions/' + sessionId + '/lanes/' + encodeURIComponent(currentLane) + '/git/commit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: commitMessage }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data?.detail || '提交失败');
      setGitFiles(data.files || []);
      setCommitMessage('');
      addToast({ type: 'success', message: 'Git 提交已创建' });
      window.dispatchEvent(new Event('codemate:refresh-workspace'));
      void refresh();
    } catch (commitError) { addToast({ type: 'warning', message: commitError instanceof Error ? commitError.message : '提交失败' }); }
    finally { setBusy(false); }
  };

  const checkpoint = async () => {
    if (!sessionId) return;
    setBusy(true);
    try {
      const response = await fetch('/api/sessions/' + sessionId + '/lanes/' + encodeURIComponent(currentLane) + '/checkpoint', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ paths: selectedPaths.length ? selectedPaths : null }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data?.detail || '保存检查点失败');
      addToast({ type: 'success', message: data.created ? 'Lane 检查点已保存' : '当前没有待保存的修改' });
      window.dispatchEvent(new Event('codemate:refresh-workspace'));
      void refresh();
    } catch (checkpointError) { addToast({ type: 'warning', message: checkpointError instanceof Error ? checkpointError.message : '保存检查点失败' }); }
    finally { setBusy(false); }
  };

  const discardChanges = async () => {
    if (!sessionId) return;
    setBusy(true);
    try {
      const response = await fetch('/api/sessions/' + sessionId + '/lanes/' + encodeURIComponent(currentLane) + '/discard', { method: 'POST' });
      const data = await response.json();
      if (!response.ok) throw new Error(data?.detail || '放弃修改失败');
      addToast({ type: 'success', message: '未保存修改已放弃' });
      window.dispatchEvent(new Event('codemate:refresh-workspace'));
      void refresh();
    } catch (discardError) { addToast({ type: 'warning', message: discardError instanceof Error ? discardError.message : '放弃修改失败' }); }
    finally { setBusy(false); }
  };

  const discard = () => setConfirmDiscard(true);

  const loadDiff = async (path: string, staged = false) => {
    if (!sessionId) return;
    const query = '?path=' + encodeURIComponent(path) + '&staged=' + staged;
    const response = await fetch('/api/sessions/' + sessionId + '/lanes/' + encodeURIComponent(currentLane) + '/git/diff' + query);
    const data = await response.json();
    if (!response.ok) {
      setDiff(data.detail || '读取 diff 失败');
      setDiffBinary(false);
      setDiffTruncated(false);
      return;
    }
    setDiff(data.diff || '');
    setDiffBinary(Boolean(data.binary));
    setDiffTruncated(Boolean(data.truncated));
  };

  return <div className="flex h-full min-h-0 flex-col overflow-y-auto"><div className="flex items-center justify-between border-b border-border px-3 py-2"><div><div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-text-muted">源代码管理</div><div className="mt-0.5 text-xs text-text-secondary">Lane 与普通 Git 工作流</div></div><button type="button" onClick={() => void refresh()} className="rounded p-1 text-text-muted hover:bg-surface-3" title="刷新 Git 状态" aria-label="刷新 Git 状态"><RefreshCw className={loading ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} /></button></div><div className="border-b border-border p-3"><button type="button" onClick={() => setShowCompareDrawer(true)} className="flex w-full items-center justify-center gap-2 rounded border border-border bg-surface-1 px-3 py-2 text-xs font-medium text-text-secondary transition-colors hover:bg-surface-3 hover:text-text-primary"><GitMerge className="h-3.5 w-3.5 text-accent" />分支对比</button></div>{!loading && !gitState?.enabled && <div className="m-3 rounded border border-border bg-surface-1 p-3 text-xs text-text-muted">当前工作区未绑定 Git，仅支持对话 Lane。</div>}{gitState?.enabled && <div className="space-y-3 p-3 text-xs"><div className="rounded border border-border bg-surface-1 p-3"><div className="flex items-center justify-between"><span className="font-medium text-text-secondary">{currentLane}</span><span className={gitState.sync_state === 'clean' ? 'text-status-success' : 'text-status-warning'}>{gitState.sync_state}</span></div><div className="mt-1 flex items-center gap-2 font-mono text-text-muted"><GitBranch className="h-3.5 w-3.5 text-accent" />{gitState.managed_branch}</div><div className="mt-1 text-text-muted">HEAD {gitState.short_head || '无'} · {gitFiles.length} 个工作树变更</div></div><div className="rounded border border-border bg-surface-1 p-3"><div className="mb-2 flex items-center justify-between"><span className="font-medium text-text-secondary">工作树文件</span><div className="flex gap-1"><button type="button" onClick={() => void mutateGit('stage')} disabled={busy || !selectedPaths.length} className="rounded border border-border px-2 py-1 disabled:opacity-40">暂存</button><button type="button" onClick={() => void mutateGit('unstage')} disabled={busy || !selectedPaths.length} className="rounded border border-border px-2 py-1 disabled:opacity-40">取消暂存</button></div></div>{gitFiles.map((file) => <div key={file.path} className="flex items-center gap-2 py-1"><input type="checkbox" checked={selectedPaths.includes(file.path)} onChange={(event) => setSelectedPaths((current) => event.target.checked ? [...current, file.path] : current.filter((path) => path !== file.path))} /><button type="button" onClick={() => void loadDiff(file.path, file.staged)} className="flex min-w-0 flex-1 items-center gap-2 text-left text-text-muted hover:text-text-primary"><span className="font-mono text-accent">{file.status}</span><span className="truncate">{file.path}</span></button></div>)}{!gitFiles.length && <div className="flex items-center gap-2 text-text-muted"><Check className="h-3.5 w-3.5 text-status-success" />工作树干净</div>}</div><div className="rounded border border-border bg-surface-1 p-3"><div className="mb-2 font-medium text-text-secondary">创建普通 Git 提交</div><input value={commitMessage} onChange={(event) => setCommitMessage(event.target.value)} className="w-full rounded border border-border bg-surface-2 px-2 py-1.5 text-xs outline-none" placeholder="提交信息" /><button type="button" onClick={() => void commit()} disabled={busy || !commitMessage.trim()} className="mt-2 rounded bg-accent px-3 py-1.5 text-xs text-white disabled:opacity-40">提交已暂存文件</button></div>{diff && <UnifiedDiffViewer diff={diff} binary={diffBinary} truncated={diffTruncated} className="max-h-48" />}{!diff && diffBinary && <UnifiedDiffViewer diff="" binary />}{!diff && !diffBinary && <div className="rounded-lg bg-surface-3 px-3 py-3 text-xs text-text-muted">选择文件查看代码差异。</div>}<div className="flex flex-wrap gap-2"><button type="button" onClick={() => void checkpoint()} disabled={busy || !gitFiles.length} className="flex items-center gap-1 rounded border border-border px-2 py-1.5"><SaveIcon />Lane 检查点</button><button type="button" onClick={() => void discard()} disabled={busy || !gitFiles.length} className="rounded border border-red-200 px-2 py-1.5 text-status-error">放弃修改</button><button type="button" onClick={() => setShowManager(true)} className="flex items-center gap-1 rounded border border-border px-2 py-1.5"><GitMerge className="h-3.5 w-3.5" />完整 Lane 管理</button></div><div className="text-[11px] text-text-muted">{lane?.description || '当前 Lane 未填写描述'}</div></div>}{showManager && <LaneCodeManagerModal onClose={() => setShowManager(false)} />}<ConfirmDialog open={confirmDiscard} title="放弃未保存修改" message="放弃当前 Lane 的未保存修改？" confirmLabel="放弃修改" danger onCancel={() => setConfirmDiscard(false)} onConfirm={() => { setConfirmDiscard(false); void discardChanges(); }} /></div>;
}

function SaveIcon() { return <span className="font-semibold">✓</span>; }

export function SearchPanel() {
  const { sessionId, openEditorTab, updateEditorTab } = useStore();
  const [query, setQuery] = useState('');
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [results, setResults] = useState<Array<{ path: string; line: number | null; preview: string; match_type: 'filename' | 'content' }>>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [error, setError] = useState('');

  const search = async () => {
    const value = query.trim();
    if (!sessionId || !value) {
      setResults([]);
      setSearched(Boolean(value));
      return;
    }
    setLoading(true);
    setError('');
    setSearched(true);
    try {
      const params = new URLSearchParams({ query: value, case_sensitive: String(caseSensitive), limit: '100' });
      const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/workspace/search?${params}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data?.detail || '搜索失败');
      setResults(data.results || []);
    } catch (searchError) {
      setResults([]);
      setError(searchError instanceof Error ? searchError.message : '搜索失败');
    } finally {
      setLoading(false);
    }
  };

  const openResult = async (path: string) => {
    if (!sessionId) return;
    openEditorTab(makeTab(path));
    try {
      const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/workspace/file?path=${encodeURIComponent(path)}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data?.detail || '读取文件失败');
      updateEditorTab(path, { content: data.content, originalContent: data.content, encoding: data.encoding, revision: data.revision || null, binary: data.binary, size: data.size, lines: data.lines, loading: false, dirty: false, saving: false, error: undefined });
    } catch (openError) {
      updateEditorTab(path, { loading: false, error: openError instanceof Error ? openError.message : '读取文件失败' });
    }
  };

  return <div className="flex h-full min-h-0 flex-col"><div className="border-b border-border px-3 py-2"><div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-text-muted">搜索</div><div className="mt-0.5 text-xs text-text-secondary">在当前 Lane 工作区查找</div></div><form className="border-b border-border p-3" onSubmit={(event) => { event.preventDefault(); void search(); }}><div className="flex items-center gap-2 rounded border border-border bg-surface-1 px-2 py-1.5"><Search className="h-4 w-4 shrink-0 text-text-muted" /><input value={query} onChange={(event) => setQuery(event.target.value)} className="min-w-0 flex-1 bg-transparent text-xs outline-none" placeholder="搜索文件名或内容" aria-label="搜索文件名或内容" /><button type="submit" disabled={loading || !query.trim()} className="rounded bg-accent px-2 py-1 text-[11px] text-white disabled:opacity-40">{loading ? '搜索中…' : '搜索'}</button></div><label className="mt-2 flex items-center gap-2 text-[11px] text-text-muted"><input type="checkbox" checked={caseSensitive} onChange={(event) => setCaseSensitive(event.target.checked)} />区分大小写</label></form><div className="min-h-0 flex-1 overflow-y-auto p-3">{error && <div className="mb-2 rounded border border-red-200 bg-red-50 p-2 text-xs text-status-error">{error}</div>}{loading && <div className="flex items-center gap-2 py-4 text-xs text-text-muted"><LoaderCircle className="h-4 w-4 animate-spin" />正在搜索当前 Lane…</div>}{!loading && searched && !error && results.length === 0 && <div className="py-4 text-xs text-text-muted">没有找到匹配的文件或内容。</div>}{!loading && !searched && <div className="rounded border border-dashed border-border p-3 text-xs text-text-muted">输入关键词后搜索文件名和文本内容。</div>}{!loading && results.length > 0 && <div className="space-y-1">{results.map((result, index) => <button key={`${result.path}:${result.line ?? 'name'}:${index}`} type="button" onClick={() => void openResult(result.path)} className="w-full rounded border border-transparent bg-surface-1 px-2.5 py-2 text-left transition-colors hover:border-border hover:bg-surface-3"><div className="flex items-center gap-2"><FileCode2 className="h-3.5 w-3.5 shrink-0 text-accent" /><span className="min-w-0 flex-1 truncate font-mono text-xs text-text-primary">{result.path}</span>{result.line !== null && <span className="shrink-0 text-[11px] text-text-muted">第 {result.line} 行</span>}</div><div className="mt-1 truncate pl-5 text-[11px] text-text-secondary">{result.match_type === 'filename' ? '文件名匹配' : result.preview}</div></button>)}</div>}</div></div>;
}

export function SidePanel({ view, onClose }: { view: WorkbenchView; onClose: () => void }) {
  const labels: Record<WorkbenchView, string> = { explorer: '资源管理器', history: '分支历史', 'source-control': '源代码管理', search: '搜索' };
  return <aside className="flex h-full min-h-0 flex-col bg-surface-2" aria-label={labels[view]}><div className="flex h-9 flex-none items-center justify-between border-b border-border px-3"><span className="text-xs font-medium text-text-secondary">{labels[view]}</span><button type="button" onClick={onClose} className="rounded p-1 text-text-muted hover:bg-surface-3" title="关闭侧边栏" aria-label="关闭侧边栏"><X className="h-4 w-4" /></button></div><div className="min-h-0 flex-1">{view === 'explorer' && <ExplorerPanel />}{view === 'history' && <TreeCanvas />}{view === 'source-control' && <SourceControlPanel />}{view === 'search' && <SearchPanel />}</div></aside>;
}
