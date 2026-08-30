import type { ContentBlock, Entry, LanePointer, Message } from '../types';

export function getLanePath(
  entries: Entry[],
  lanes: LanePointer[],
  currentLane: string
): Entry[] {
  const lane = lanes.find((item) => item.lane === currentLane);
  if (!lane?.leaf_id) return [];

  const byId = new Map(entries.map((entry) => [entry.id, entry]));
  const path: Entry[] = [];
  const seen = new Set<string>();
  let currentId: string | null = lane.leaf_id;

  while (currentId && !seen.has(currentId)) {
    const entry = byId.get(currentId);
    if (!entry) break;
    seen.add(currentId);
    path.push(entry);
    currentId = entry.parent;
  }

  return path.reverse();
}

export function entryToMarkdown(entry: Entry): string {
  const fullContent = entry.full_content ?? entry.content;

  if (typeof fullContent === 'string') {
    return fullContent;
  }

  if (!Array.isArray(fullContent)) {
    return entry.content || '';
  }

  return fullContent
    .map((block) => blockToMarkdown(block))
    .filter(Boolean)
    .join('\n\n');
}

export function getLaneConversation(
  entries: Entry[],
  lanes: LanePointer[],
  currentLane: string
): Message[] {
  return getLanePath(entries, lanes, currentLane)
    .filter((entry) => entry.role === 'user' || entry.role === 'assistant')
    .map((entry) => ({
      message_id: entry.id,
      role: entry.role as 'user' | 'assistant',
      content: entryToMarkdown(entry),
      timestamp: entry.timestamp * 1000,
    }))
    .filter((message) => message.content.trim().length > 0);
}

function blockToMarkdown(block: ContentBlock): string {
  if (block.kind === 'text') {
    return block.text || '';
  }
  return '';
}
