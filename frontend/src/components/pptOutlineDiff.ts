type OutlineLike = {
  id?: string;
  pageNum?: number;
  title?: string;
  summary?: string;
  bullets?: string[];
  layout_description?: string;
  key_points?: string[];
  asset_ref?: string | null;
};

type OutlineDirectiveLike = {
  id?: string;
  scope?: string;
  type?: string;
  label?: string;
  instruction?: string;
  action?: string;
  value?: string;
  page_num?: number | null;
};

export type PptOutlineDiffKind = 'added' | 'removed' | 'modified';
export type PptOutlineDiffField = 'title' | 'layout' | 'points' | 'asset' | 'position';

export type PptOutlineDiffEntry = {
  key: string;
  kind: PptOutlineDiffKind;
  pageNum: number;
  title: string;
  previousPageNum?: number;
  previousTitle?: string;
  beforeLayout?: string;
  afterLayout?: string;
  beforePoints?: string[];
  afterPoints?: string[];
  beforeAssetRef?: string;
  afterAssetRef?: string;
  changedFields: PptOutlineDiffField[];
  detailLines: string[];
};

export type PptOutlineDiffResult = {
  addedCount: number;
  removedCount: number;
  modifiedCount: number;
  totalCount: number;
  entries: PptOutlineDiffEntry[];
};

export type PptDirectiveDiffKind = 'added' | 'removed';

export type PptDirectiveDiffEntry = {
  key: string;
  kind: PptDirectiveDiffKind;
  label: string;
  type: string;
  pageNum?: number;
};

export type PptDirectiveDiffResult = {
  addedCount: number;
  removedCount: number;
  totalCount: number;
  entries: PptDirectiveDiffEntry[];
};

type NormalizedOutlineItem = {
  id: string;
  pageNum: number;
  title: string;
  layoutDescription: string;
  keyPoints: string[];
  assetRef: string;
  index: number;
};

function normalizeText(value: unknown): string {
  return String(value || '').trim();
}

function normalizeDirective(item: OutlineDirectiveLike, index: number) {
  return {
    id: normalizeText(item.id) || `directive_${index}`,
    scope: normalizeText(item.scope) || 'global',
    type: normalizeText(item.type) || 'custom',
    label: normalizeText(item.label || item.instruction),
    action: normalizeText(item.action) || 'set',
    pageNum: Number(item.page_num) || undefined,
  };
}

function normalizeKeyPoints(item: OutlineLike): string[] {
  const raw = Array.isArray(item.key_points) && item.key_points.length > 0 ? item.key_points : item.bullets;
  if (!Array.isArray(raw)) return [];
  return raw.map((entry) => normalizeText(entry)).filter(Boolean);
}

function normalizeOutlineItem(item: OutlineLike, index: number): NormalizedOutlineItem {
  return {
    id: normalizeText(item.id) || `__index_${index}`,
    pageNum: Number(item.pageNum) || index + 1,
    title: normalizeText(item.title) || `页面 ${index + 1}`,
    layoutDescription: normalizeText(item.layout_description || item.summary),
    keyPoints: normalizeKeyPoints(item),
    assetRef: normalizeText(item.asset_ref),
    index,
  };
}

function areUniqueIds(items: NormalizedOutlineItem[]): boolean {
  const ids = items.map((item) => item.id).filter(Boolean);
  return ids.length > 0 && new Set(ids).size === ids.length;
}

function buildPointsDiff(beforePoints: string[], afterPoints: string[]): string {
  if (beforePoints.length !== afterPoints.length) {
    return `要点数量：${beforePoints.length} -> ${afterPoints.length}`;
  }
  return '要点内容已调整';
}

function formatValueChange(label: string, beforeValue: string, afterValue: string): string {
  const beforeText = beforeValue || '空';
  const afterText = afterValue || '空';
  return `${label}：${beforeText} -> ${afterText}`;
}

function buildPointDetailLines(beforePoints: string[], afterPoints: string[]): string[] {
  const beforeSet = new Set(beforePoints);
  const afterSet = new Set(afterPoints);
  const removed = beforePoints.filter((point) => !afterSet.has(point));
  const added = afterPoints.filter((point) => !beforeSet.has(point));
  const lines: string[] = [];
  if (removed.length > 0) {
    lines.push(`移除要点：${removed.join('、')}`);
  }
  if (added.length > 0) {
    lines.push(`新增要点：${added.join('、')}`);
  }
  if (lines.length > 0) return lines;
  if (beforePoints.length !== afterPoints.length) {
    return [buildPointsDiff(beforePoints, afterPoints)];
  }
  return beforePoints.map((point, index) => formatValueChange(`要点 ${index + 1}`, point, afterPoints[index] || ''));
}

function buildModifiedEntry(beforeItem: NormalizedOutlineItem, afterItem: NormalizedOutlineItem): PptOutlineDiffEntry | null {
  const changedFields: PptOutlineDiffField[] = [];
  const detailLines: string[] = [];

  if (beforeItem.title !== afterItem.title) {
    changedFields.push('title');
    detailLines.push(formatValueChange('标题', beforeItem.title, afterItem.title));
  }
  if (beforeItem.layoutDescription !== afterItem.layoutDescription) {
    changedFields.push('layout');
    detailLines.push(formatValueChange('布局', beforeItem.layoutDescription, afterItem.layoutDescription));
  }
  if (JSON.stringify(beforeItem.keyPoints) !== JSON.stringify(afterItem.keyPoints)) {
    changedFields.push('points');
    detailLines.push(...buildPointDetailLines(beforeItem.keyPoints, afterItem.keyPoints));
  }
  if (beforeItem.assetRef !== afterItem.assetRef) {
    changedFields.push('asset');
    detailLines.push(formatValueChange('素材引用', beforeItem.assetRef, afterItem.assetRef));
  }
  if (beforeItem.pageNum !== afterItem.pageNum || beforeItem.index !== afterItem.index) {
    changedFields.push('position');
    detailLines.push(`位置：第 ${beforeItem.pageNum} 页 -> 第 ${afterItem.pageNum} 页`);
  }

  if (changedFields.length === 0) return null;

  return {
    key: `modified_${afterItem.id}_${afterItem.pageNum}`,
    kind: 'modified',
    pageNum: afterItem.pageNum,
    title: afterItem.title,
    previousPageNum: beforeItem.pageNum,
    previousTitle: beforeItem.title,
    beforeLayout: beforeItem.layoutDescription,
    afterLayout: afterItem.layoutDescription,
    beforePoints: beforeItem.keyPoints,
    afterPoints: afterItem.keyPoints,
    beforeAssetRef: beforeItem.assetRef,
    afterAssetRef: afterItem.assetRef,
    changedFields,
    detailLines,
  };
}

function buildAddedEntry(item: NormalizedOutlineItem): PptOutlineDiffEntry {
  return {
    key: `added_${item.id}_${item.pageNum}`,
    kind: 'added',
    pageNum: item.pageNum,
    title: item.title,
    afterLayout: item.layoutDescription,
    afterPoints: item.keyPoints,
    afterAssetRef: item.assetRef,
    changedFields: [],
    detailLines: ['新增页面'],
  };
}

function buildRemovedEntry(item: NormalizedOutlineItem): PptOutlineDiffEntry {
  return {
    key: `removed_${item.id}_${item.pageNum}`,
    kind: 'removed',
    pageNum: item.pageNum,
    title: item.title,
    previousPageNum: item.pageNum,
    previousTitle: item.title,
    beforeLayout: item.layoutDescription,
    beforePoints: item.keyPoints,
    beforeAssetRef: item.assetRef,
    changedFields: [],
    detailLines: ['该页面将从正式大纲中移除'],
  };
}

function buildFallbackDiff(
  confirmed: NormalizedOutlineItem[],
  draft: NormalizedOutlineItem[],
): PptOutlineDiffEntry[] {
  const entries: PptOutlineDiffEntry[] = [];
  const maxLength = Math.max(confirmed.length, draft.length);
  for (let index = 0; index < maxLength; index += 1) {
    const beforeItem = confirmed[index];
    const afterItem = draft[index];
    if (!beforeItem && afterItem) {
      entries.push(buildAddedEntry(afterItem));
      continue;
    }
    if (beforeItem && !afterItem) {
      entries.push(buildRemovedEntry(beforeItem));
      continue;
    }
    if (beforeItem && afterItem) {
      const modified = buildModifiedEntry(beforeItem, afterItem);
      if (modified) entries.push(modified);
    }
  }
  return entries;
}

export function diffPptOutline(confirmedOutline: OutlineLike[], draftOutline: OutlineLike[]): PptOutlineDiffResult {
  const confirmed = (confirmedOutline || []).map(normalizeOutlineItem);
  const draft = (draftOutline || []).map(normalizeOutlineItem);

  let entries: PptOutlineDiffEntry[] = [];
  const canUseIdMatch = areUniqueIds(confirmed) && areUniqueIds(draft);

  if (canUseIdMatch) {
    const confirmedById = new Map(confirmed.map((item) => [item.id, item]));
    const draftById = new Map(draft.map((item) => [item.id, item]));

    draft.forEach((draftItem) => {
      const beforeItem = confirmedById.get(draftItem.id);
      if (!beforeItem) {
        entries.push(buildAddedEntry(draftItem));
        return;
      }
      const modified = buildModifiedEntry(beforeItem, draftItem);
      if (modified) entries.push(modified);
    });

    confirmed.forEach((confirmedItem) => {
      if (!draftById.has(confirmedItem.id)) {
        entries.push(buildRemovedEntry(confirmedItem));
      }
    });
  } else {
    entries = buildFallbackDiff(confirmed, draft);
  }

  entries.sort((left, right) => {
    if (left.pageNum !== right.pageNum) return left.pageNum - right.pageNum;
    const rank = { modified: 0, added: 1, removed: 2 };
    return rank[left.kind] - rank[right.kind];
  });

  const addedCount = entries.filter((entry) => entry.kind === 'added').length;
  const removedCount = entries.filter((entry) => entry.kind === 'removed').length;
  const modifiedCount = entries.filter((entry) => entry.kind === 'modified').length;

  return {
    addedCount,
    removedCount,
    modifiedCount,
    totalCount: entries.length,
    entries,
  };
}

export function diffPptGlobalDirectives(
  confirmedDirectives: OutlineDirectiveLike[],
  draftDirectives: OutlineDirectiveLike[],
): PptDirectiveDiffResult {
  const before = (confirmedDirectives || []).map(normalizeDirective).filter((item) => item.label);
  const after = (draftDirectives || []).map(normalizeDirective).filter((item) => item.label);
  const beforeMap = new Map(before.map((item) => [`${item.scope}:${item.type}:${item.label}`, item]));
  const afterMap = new Map(after.map((item) => [`${item.scope}:${item.type}:${item.label}`, item]));
  const entries: PptDirectiveDiffEntry[] = [];

  after.forEach((item) => {
    const key = `${item.scope}:${item.type}:${item.label}`;
    if (!beforeMap.has(key)) {
      entries.push({
        key: `directive_added_${item.id}`,
        kind: 'added',
        label: item.label,
        type: item.type,
        pageNum: item.pageNum,
      });
    }
  });

  before.forEach((item) => {
    const key = `${item.scope}:${item.type}:${item.label}`;
    if (!afterMap.has(key)) {
      entries.push({
        key: `directive_removed_${item.id}`,
        kind: 'removed',
        label: item.label,
        type: item.type,
        pageNum: item.pageNum,
      });
    }
  });

  return {
    addedCount: entries.filter((item) => item.kind === 'added').length,
    removedCount: entries.filter((item) => item.kind === 'removed').length,
    totalCount: entries.length,
    entries,
  };
}

export function formatPptOutlineDiffCountLabel(kind: PptOutlineDiffKind, count: number): string {
  if (kind === 'added') return `新增 ${count} 页`;
  if (kind === 'removed') return `删除 ${count} 页`;
  return `修改 ${count} 页`;
}

export function getPptOutlineDiffKindLabel(kind: PptOutlineDiffKind): string {
  if (kind === 'added') return '新增';
  if (kind === 'removed') return '删除';
  return '修改';
}

export function getPptDirectiveDiffKindLabel(kind: PptDirectiveDiffKind): string {
  return kind === 'added' ? '新增规则' : '移除规则';
}
