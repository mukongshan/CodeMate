import { useEffect, useMemo, useState } from 'react';
import { FileCode2, GitCompare, Loader2, MessageSquareText, X } from 'lucide-react';
import { useStore } from '../../store';
import type { CodeDiffFile, LaneCodeComparison } from '../../types';

interface ConversationEntry {
  id: string;
  role: string;
  content: unknown;
}

interface ComparisonData {
  common_ancestor: string | null;
  lane_a_entries: ConversationEntry[];
  lane_b_entries: ConversationEntry[];
  identical: boolean;
  code?: LaneCodeComparison;
}

type CompareTab = 'code' | 'conversation';

const statusLabels: Record<string, string> = {
  A: '新增',
  M: '修改',
  D: '删除',
  R: '重命名',
  C: '复制',
  T: '类型变化',
};

function entryText(content: unknown): string {
  if (typeof content === 'string') return content;
  if (!Array.isArray(content)) return String(content ?? '');
  return content
    .map((block) => {
      if (!block || typeof block !== 'object') return String(block ?? '');
      const item = block as Record<string, unknown>;
      if (typeof item.text === 'string') return item.text;
      if (typeof item.content === 'string') return item.content;
      if (typeof item.name === 'string') return `工具：${item.name}`;
      return '';
    })
    .filter(Boolean)
    .join('\n');
}

export default function CompareDrawer() {
  const { sessionId, lanes, currentLane, setShowCompareDrawer } = useStore();
  const [laneA, setLaneA] = useState(currentLane);
  const [laneB, setLaneB] = useState('');
  const [compareData, setCompareData] = useState<ComparisonData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [activeTab, setActiveTab] = useState<CompareTab>('code');
  const [selectedFile, setSelectedFile] = useState<CodeDiffFile | null>(null);
  const [fileDiff, setFileDiff] = useState('');
  const [fileLoading, setFileLoading] = useState(false);

  useEffect(() => {
    setLaneA(currentLane);
    const otherLane = lanes.find((lane) => lane.lane !== currentLane);
    setLaneB(otherLane?.lane || '');
  }, [currentLane, lanes]);

  useEffect(() => {
    if (!sessionId || !laneA || !laneB || laneA === laneB) {
      setCompareData(null);
      return;
    }

    const controller = new AbortController();
    const loadComparison = async () => {
      setLoading(true);
      setError('');
      setSelectedFile(null);
      setFileDiff('');
      try {
        const params = new URLSearchParams({ a: laneA, b: laneB });
        const response = await fetch(
          `/api/sessions/${sessionId}/lanes/compare?${params}`,
          { signal: controller.signal }
        );
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.error?.message || `对比失败：HTTP ${response.status}`);
        }
        setCompareData(data);
        const firstFile = data.code?.enabled ? data.code.files?.[0] : null;
        if (firstFile) {
          setSelectedFile(firstFile);
          setActiveTab('code');
        } else {
          setActiveTab('conversation');
        }
      } catch (loadError) {
        if ((loadError as Error).name !== 'AbortError') {
          setError(loadError instanceof Error ? loadError.message : '分支对比失败');
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    loadComparison();
    return () => controller.abort();
  }, [sessionId, laneA, laneB]);

  useEffect(() => {
    if (!sessionId || !selectedFile || !laneA || !laneB) return;
    const controller = new AbortController();
    const loadFileDiff = async () => {
      setFileLoading(true);
      setFileDiff('');
      try {
        const params = new URLSearchParams({
          a: laneA,
          b: laneB,
          path: selectedFile.path,
        });
        const response = await fetch(
          `/api/sessions/${sessionId}/lanes/compare/file?${params}`,
          { signal: controller.signal }
        );
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.error?.message || `加载代码差异失败：HTTP ${response.status}`);
        }
        setFileDiff(data.binary ? '二进制文件无法显示文本差异。' : data.diff || '文件内容没有文本差异。');
      } catch (loadError) {
        if ((loadError as Error).name !== 'AbortError') {
          setFileDiff(loadError instanceof Error ? loadError.message : '代码差异加载失败');
        }
      } finally {
        if (!controller.signal.aborted) setFileLoading(false);
      }
    };
    loadFileDiff();
    return () => controller.abort();
  }, [sessionId, laneA, laneB, selectedFile]);

  const codeFiles = compareData?.code?.files || [];
  const codeSummary = useMemo(() => {
    return codeFiles.reduce<Record<string, number>>((summary, file) => {
      summary[file.status] = (summary[file.status] || 0) + 1;
      return summary;
    }, {});
  }, [codeFiles]);

  return (
    <div className="fixed inset-x-0 bottom-0 top-[18%] z-40 flex flex-col border-t border-border bg-surface-2 shadow-pop animate-[slideUp_0.28s_ease-out]">
      <div className="flex items-center justify-between border-b border-border p-4">
        <div className="flex min-w-0 items-center gap-4">
          <div>
            <h3 className="text-lg font-semibold">方案评审</h3>
            <div className="text-xs text-text-muted">对话路径与代码结果联合对比</div>
          </div>
          <div className="flex items-center gap-2">
            <select
              value={laneA}
              onChange={(event) => setLaneA(event.target.value)}
              className="rounded-md border border-border bg-surface-1 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-accent"
            >
              {lanes.map((lane) => <option key={lane.lane} value={lane.lane}>{lane.lane}</option>)}
            </select>
            <GitCompare className="h-4 w-4 text-text-muted" />
            <select
              value={laneB}
              onChange={(event) => setLaneB(event.target.value)}
              className="rounded-md border border-border bg-surface-1 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-accent"
            >
              {lanes.map((lane) => <option key={lane.lane} value={lane.lane}>{lane.lane}</option>)}
            </select>
          </div>
        </div>
        <button
          onClick={() => setShowCompareDrawer(false)}
          className="rounded p-1 transition-colors hover:bg-surface-3"
          aria-label="关闭方案评审"
        >
          <X className="h-5 w-5 text-text-muted" />
        </button>
      </div>

      {lanes.length < 2 ? (
        <div className="flex flex-1 items-center justify-center text-text-muted">至少创建两个 Lane 后才能比较。</div>
      ) : laneA === laneB ? (
        <div className="flex flex-1 items-center justify-center text-text-muted">请选择两个不同的 Lane。</div>
      ) : loading ? (
        <div className="flex flex-1 items-center justify-center gap-2 text-text-muted">
          <Loader2 className="h-4 w-4 animate-spin" />正在计算对话与代码差异
        </div>
      ) : error ? (
        <div className="m-6 rounded-md border border-status-error bg-red-50 p-4 text-sm text-status-error">{error}</div>
      ) : compareData ? (
        <>
          <div className="flex items-center justify-between border-b border-border px-4">
            <div className="flex">
              <button
                onClick={() => setActiveTab('code')}
                disabled={!compareData.code?.enabled}
                className={`flex items-center gap-2 border-b-2 px-4 py-3 text-sm ${activeTab === 'code' ? 'border-accent text-accent' : 'border-transparent text-text-secondary'} disabled:opacity-40`}
              >
                <FileCode2 className="h-4 w-4" />代码差异 ({codeFiles.length})
              </button>
              <button
                onClick={() => setActiveTab('conversation')}
                className={`flex items-center gap-2 border-b-2 px-4 py-3 text-sm ${activeTab === 'conversation' ? 'border-accent text-accent' : 'border-transparent text-text-secondary'}`}
              >
                <MessageSquareText className="h-4 w-4" />对话差异
              </button>
            </div>
            {compareData.code?.enabled ? (
              <div className="flex items-center gap-3 text-xs text-text-muted">
                <span>{laneA}: {compareData.code.lane_a?.short_head}</span>
                <span>{laneB}: {compareData.code.lane_b?.short_head}</span>
                {Object.entries(codeSummary).map(([status, count]) => (
                  <span key={status}>{statusLabels[status] || status} {count}</span>
                ))}
              </div>
            ) : (
              <div className="text-xs text-text-muted">{compareData.code?.reason || '当前 Session 未启用 Git'}</div>
            )}
          </div>

          <div className="min-h-0 flex-1 overflow-hidden">
            {activeTab === 'code' && compareData.code?.enabled ? (
              <div className="flex h-full">
                <div className="w-[340px] shrink-0 overflow-y-auto border-r border-border bg-surface-1 p-3">
                  {codeFiles.length === 0 ? (
                    <div className="p-4 text-sm text-text-muted">两个 Lane 的代码状态相同。</div>
                  ) : codeFiles.map((file) => (
                    <button
                      key={`${file.old_path || ''}:${file.path}`}
                      onClick={() => setSelectedFile(file)}
                      className={`mb-1 w-full rounded-md border p-3 text-left transition-colors ${selectedFile?.path === file.path ? 'border-accent bg-blue-50' : 'border-transparent hover:bg-surface-3'}`}
                    >
                      <div className="flex items-center gap-2">
                        <span className="w-8 rounded bg-surface-3 px-1.5 py-0.5 text-center font-mono text-xs">{file.status}</span>
                        <span className="truncate font-mono text-xs">{file.path}</span>
                      </div>
                      {file.old_path && <div className="mt-1 truncate pl-10 font-mono text-[11px] text-text-muted">来自 {file.old_path}</div>}
                    </button>
                  ))}
                </div>
                <div className="min-w-0 flex-1 overflow-auto bg-[#0d1117]">
                  {fileLoading ? (
                    <div className="flex h-full items-center justify-center gap-2 text-slate-400"><Loader2 className="h-4 w-4 animate-spin" />加载代码差异</div>
                  ) : selectedFile ? (
                    <pre className="min-h-full whitespace-pre p-4 font-mono text-xs leading-5 text-slate-200">{fileDiff}</pre>
                  ) : (
                    <div className="flex h-full items-center justify-center text-slate-400">选择文件查看代码差异</div>
                  )}
                </div>
              </div>
            ) : (
              <div className="flex h-full">
                <ConversationColumn lane={laneA} entries={compareData.lane_a_entries || []} />
                <ConversationColumn lane={laneB} entries={compareData.lane_b_entries || []} borderLeft />
              </div>
            )}
          </div>
        </>
      ) : null}
    </div>
  );
}

function ConversationColumn({
  lane,
  entries,
  borderLeft = false,
}: {
  lane: string;
  entries: ConversationEntry[];
  borderLeft?: boolean;
}) {
  return (
    <div className={`flex-1 overflow-y-auto p-4 ${borderLeft ? 'border-l border-border' : ''}`}>
      <div className="mb-3 flex items-center justify-between">
        <h4 className="font-semibold">{lane}</h4>
        <span className="text-xs text-text-muted">{entries.length} 条独有消息</span>
      </div>
      {entries.length > 0 ? (
        <div className="space-y-3">
          {entries.map((entry) => (
            <div key={entry.id} className="rounded-md border border-border bg-surface-1 p-3">
              <div className="mb-1 text-xs uppercase text-text-secondary">{entry.role}</div>
              <div className="whitespace-pre-wrap text-sm">{entryText(entry.content)}</div>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-sm text-text-muted">该 Lane 尚未产生独有对话。</div>
      )}
    </div>
  );
}
