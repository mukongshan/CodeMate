import { useEffect, useMemo, useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  File,
  FileCode2,
  Folder,
  FolderOpen,
  Loader2,
  RefreshCw,
  X,
} from 'lucide-react';
import { useStore } from '../../store';
import type {
  WorkspaceDirectoryPayload,
  WorkspaceFileEntry,
  WorkspaceFilePayload,
} from '../../types';

interface TreeEntry {
  entry: WorkspaceFileEntry;
  depth: number;
}

function errorMessage(data: any, fallback: string): string {
  return data?.detail || data?.error?.message || fallback;
}

function formatSize(size: number | null): string {
  if (size === null) return '';
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function fileIcon(name: string) {
  const extension = name.split('.').pop()?.toLowerCase();
  const codeExtensions = new Set([
    'c', 'cc', 'cpp', 'css', 'go', 'h', 'hpp', 'html', 'java', 'js', 'json',
    'jsx', 'md', 'py', 'rs', 'sh', 'sql', 'ts', 'tsx', 'vue', 'yaml', 'yml',
  ]);
  return codeExtensions.has(extension || '') ? (
    <FileCode2 className="h-4 w-4 shrink-0 text-accent" />
  ) : (
    <File className="h-4 w-4 shrink-0 text-text-muted" />
  );
}

export default function WorkspaceFileViewer() {
  const { sessionId, currentLane, workspace, setShowWorkspaceFiles } = useStore();
  const [directories, setDirectories] = useState<Record<string, WorkspaceFileEntry[]>>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set(['']));
  const [selectedPath, setSelectedPath] = useState('');
  const [file, setFile] = useState<WorkspaceFilePayload | null>(null);
  const [loadingDirectories, setLoadingDirectories] = useState<Set<string>>(new Set());
  const [loadingFile, setLoadingFile] = useState(false);
  const [error, setError] = useState('');
  const [directoryWarnings, setDirectoryWarnings] = useState<Record<string, boolean>>({});

  const loadDirectory = async (path: string, signal?: AbortSignal) => {
    if (!sessionId) return;
    setLoadingDirectories((current) => new Set(current).add(path));
    setError('');
    try {
      const params = new URLSearchParams();
      if (path) params.set('path', path);
      const query = params.toString();
      const response = await fetch(
        `/api/sessions/${sessionId}/workspace/files${query ? `?${query}` : ''}`,
        { signal },
      );
      const data = (await response.json()) as WorkspaceDirectoryPayload | { detail?: string };
      if (!response.ok) throw new Error(errorMessage(data, '读取目录失败'));
      const directory = data as WorkspaceDirectoryPayload;
      setDirectories((current) => ({ ...current, [directory.path]: directory.entries }));
      setDirectoryWarnings((current) => ({ ...current, [directory.path]: directory.truncated }));
    } catch (loadError) {
      if ((loadError as Error).name !== 'AbortError') {
        setError(loadError instanceof Error ? loadError.message : '读取目录失败');
      }
    } finally {
      if (!signal?.aborted) {
        setLoadingDirectories((current) => {
          const next = new Set(current);
          next.delete(path);
          return next;
        });
      }
    }
  };

  const loadFile = async (entry: WorkspaceFileEntry) => {
    if (!sessionId) return;
    setSelectedPath(entry.path);
    setFile(null);
    setLoadingFile(true);
    setError('');
    try {
      const params = new URLSearchParams({ path: entry.path });
      const response = await fetch(`/api/sessions/${sessionId}/workspace/file?${params}`);
      const data = (await response.json()) as WorkspaceFilePayload | { detail?: string };
      if (!response.ok) throw new Error(errorMessage(data, '读取文件失败'));
      setFile(data as WorkspaceFilePayload);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '读取文件失败');
    } finally {
      setLoadingFile(false);
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    setDirectories({});
    setExpanded(new Set(['']));
    setSelectedPath('');
    setFile(null);
    void loadDirectory('', controller.signal);
    return () => controller.abort();
  }, [sessionId, currentLane]);

  const toggleDirectory = (entry: WorkspaceFileEntry) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(entry.path)) next.delete(entry.path);
      else next.add(entry.path);
      return next;
    });
    if (!directories[entry.path]) void loadDirectory(entry.path);
  };

  const visibleEntries = useMemo<TreeEntry[]>(() => {
    const result: TreeEntry[] = [];
    const append = (path: string, depth: number) => {
      for (const entry of directories[path] || []) {
        result.push({ entry, depth });
        if (entry.kind === 'directory' && expanded.has(entry.path)) {
          append(entry.path, depth + 1);
        }
      }
    };
    append('', 0);
    return result;
  }, [directories, expanded]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4">
      <div className="flex h-[min(80vh,760px)] w-full max-w-6xl flex-col overflow-hidden rounded-md border border-border bg-surface-1 shadow-pop">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 font-medium">
              <FolderOpen className="h-4 w-4 text-accent" />
              工作区文件
              <span className="rounded bg-surface-3 px-1.5 py-0.5 text-xs text-text-secondary">{currentLane}</span>
            </div>
            <div className="mt-1 truncate font-mono text-[11px] text-text-muted" title={workspace}>
              {workspace || '当前工作区'}
            </div>
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => void loadDirectory('')}
              className="rounded p-1.5 text-text-muted hover:bg-surface-2"
              title="刷新文件树"
            >
              <RefreshCw className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => setShowWorkspaceFiles(false)}
              className="rounded p-1.5 text-text-muted hover:bg-surface-2"
              title="关闭"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="flex min-h-0 flex-1">
          <div className="w-[min(38%,360px)] shrink-0 overflow-auto border-r border-border bg-surface-2 p-2">
            {loadingDirectories.has('') && !directories[''] ? (
              <div className="flex items-center justify-center gap-2 p-6 text-sm text-text-muted">
                <Loader2 className="h-4 w-4 animate-spin" />读取文件树
              </div>
            ) : visibleEntries.length === 0 ? (
              <div className="p-6 text-center text-sm text-text-muted">工作区为空</div>
            ) : (
              <div className="space-y-0.5">
                {visibleEntries.map(({ entry, depth }) => {
                  const isExpanded = expanded.has(entry.path);
                  const isLoading = loadingDirectories.has(entry.path);
                  return (
                    <button
                      key={entry.path}
                      type="button"
                      onClick={() => entry.kind === 'directory' ? toggleDirectory(entry) : void loadFile(entry)}
                      className={`flex w-full items-center gap-1 rounded px-2 py-1.5 text-left text-sm hover:bg-surface-3 ${selectedPath === entry.path ? 'bg-blue-50 text-accent' : ''}`}
                      style={{ paddingLeft: `${8 + depth * 16}px` }}
                      title={entry.path}
                    >
                      {entry.kind === 'directory' ? (
                        isLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : isExpanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />
                      ) : <span className="w-3.5" />}
                      {entry.kind === 'directory' ? (isExpanded ? <FolderOpen className="h-4 w-4 shrink-0 text-status-warning" /> : <Folder className="h-4 w-4 shrink-0 text-status-warning" />) : fileIcon(entry.name)}
                      <span className="min-w-0 flex-1 truncate">{entry.name}</span>
                      {entry.kind === 'file' && <span className="shrink-0 text-[10px] text-text-muted">{formatSize(entry.size)}</span>}
                    </button>
                  );
                })}
              </div>
            )}
            {directoryWarnings[''] && <div className="px-2 py-2 text-[11px] text-text-muted">根目录文件较多，仅显示前 500 项。</div>}
          </div>

          <div className="min-w-0 flex-1 overflow-auto bg-[#0d1117]">
            {error ? (
              <div className="m-4 rounded border border-red-300 bg-red-950/30 p-3 text-sm text-red-200">{error}</div>
            ) : loadingFile ? (
              <div className="flex h-full items-center justify-center gap-2 text-slate-400"><Loader2 className="h-4 w-4 animate-spin" />读取文件</div>
            ) : file ? (
              <>
                <div className="sticky top-0 flex items-center justify-between border-b border-slate-700 bg-[#161b22] px-4 py-2 text-xs text-slate-300">
                  <span className="truncate font-mono">{file.path}</span>
                  <span className="ml-4 shrink-0">{file.binary ? '二进制文件' : `${file.lines ?? 0} 行 · ${file.encoding || '文本'}`}</span>
                </div>
                {file.binary ? (
                  <div className="p-6 text-sm text-slate-400">该文件是二进制文件，暂不支持在浏览器中预览。</div>
                ) : (
                  <pre className="min-h-full whitespace-pre p-4 font-mono text-xs leading-5 text-slate-200">{file.content}</pre>
                )}
              </>
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-slate-400">从左侧选择文件查看内容</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
