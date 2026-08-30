import { useState, useEffect } from 'react';
import { useStore } from '../../store';
import { X } from 'lucide-react';

export default function CompareDrawer() {
  const { sessionId, lanes, currentLane, setShowCompareDrawer } = useStore();
  const [laneA, setLaneA] = useState(currentLane);
  const [laneB, setLaneB] = useState('');
  const [compareData, setCompareData] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    // 默认选择第二个分支
    const otherLane = lanes.find(l => l.lane !== currentLane);
    if (otherLane) {
      setLaneB(otherLane.lane);
    }
  }, []);

  useEffect(() => {
    if (laneA && laneB) {
      loadComparison();
    }
  }, [laneA, laneB]);

  const loadComparison = async () => {
    setLoading(true);
    try {
      const res = await fetch(
        `/api/sessions/${sessionId}/lanes/compare?a=${laneA}&b=${laneB}`
      );
      const data = await res.json();
      setCompareData(data);
    } catch (error) {
      console.error('Failed to load comparison:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-x-0 bottom-0 top-[30%] bg-surface-2 border-t border-border z-40 flex flex-col animate-[slideUp_0.28s_ease-out]">
      {/* 头部 */}
      <div className="flex items-center justify-between p-4 border-b border-border">
        <div className="flex items-center gap-4">
          <h3 className="text-lg font-semibold">对比分支</h3>

          <div className="flex items-center gap-2">
            <select
              value={laneA}
              onChange={(e) => setLaneA(e.target.value)}
              className="px-3 py-1.5 border border-border rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-accent"
            >
              {lanes.map(lane => (
                <option key={lane.lane} value={lane.lane}>{lane.lane}</option>
              ))}
            </select>

            <span className="text-text-muted">↔</span>

            <select
              value={laneB}
              onChange={(e) => setLaneB(e.target.value)}
              className="px-3 py-1.5 border border-border rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-accent"
            >
              {lanes.map(lane => (
                <option key={lane.lane} value={lane.lane}>{lane.lane}</option>
              ))}
            </select>
          </div>
        </div>

        <button
          onClick={() => setShowCompareDrawer(false)}
          className="p-1 hover:bg-surface-3 rounded transition-colors"
        >
          <X className="w-5 h-5 text-text-muted" />
        </button>
      </div>

      {/* 内容 */}
      <div className="flex-1 overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center h-full text-text-muted">
            加载中...
          </div>
        ) : compareData?.identical ? (
          <div className="flex items-center justify-center h-full text-text-muted">
            {laneA} 和 {laneB} 目前指向同一位置，尚无差异
          </div>
        ) : compareData ? (
          <div className="flex h-full">
            {/* 左栏 */}
            <div className="flex-1 border-r border-border overflow-y-auto p-4">
              <h4 className="font-semibold mb-3">{laneA}</h4>
              {compareData.lane_a_entries?.length > 0 ? (
                <div className="space-y-3">
                  {compareData.lane_a_entries.map((entry: any) => (
                    <div key={entry.id} className="p-3 bg-surface-1 rounded-md border border-border">
                      <div className="text-sm text-text-secondary mb-1">
                        {entry.role}
                      </div>
                      <div className="text-sm">{entry.content}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-text-muted text-sm">该分支尚未产生独有内容</div>
              )}

              <div className="mt-4 p-3 bg-surface-1 rounded-md border border-border">
                <div className="text-xs text-text-muted">汇总</div>
                <div className="text-sm mt-1">
                  {compareData.lane_a_entries?.length || 0} 条消息
                </div>
              </div>
            </div>

            {/* 右栏 */}
            <div className="flex-1 overflow-y-auto p-4">
              <h4 className="font-semibold mb-3">{laneB}</h4>
              {compareData.lane_b_entries?.length > 0 ? (
                <div className="space-y-3">
                  {compareData.lane_b_entries.map((entry: any) => (
                    <div key={entry.id} className="p-3 bg-surface-1 rounded-md border border-border">
                      <div className="text-sm text-text-secondary mb-1">
                        {entry.role}
                      </div>
                      <div className="text-sm">{entry.content}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-text-muted text-sm">该分支尚未产生独有内容</div>
              )}

              <div className="mt-4 p-3 bg-surface-1 rounded-md border border-border">
                <div className="text-xs text-text-muted">汇总</div>
                <div className="text-sm mt-1">
                  {compareData.lane_b_entries?.length || 0} 条消息
                </div>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
