/**
 * GraphRAG text_units / sources often embed lineage markers. Strip them for human-readable UI.
 */
const RE_CHUNK_LINE = /^\s*\[chunk:[a-f0-9]+\]\s*$/gim;
const RE_CHUNK_INLINE = /\[chunk:[a-f0-9]+\]/gi;
const RE_DATA = /\s*\[Data:[^\]]+\]/gi;

export function stripGraphragContextNoise(raw: string): string {
  if (!raw) return '';
  let t = raw.replace(RE_DATA, '');
  t = t.replace(RE_CHUNK_INLINE, '');
  t = t.replace(RE_CHUNK_LINE, '');
  return t.replace(/\n{3,}/g, '\n\n').trim();
}

/** First hex chunk id embedded in text, or empty. */
export function extractChunkIdFromText(raw: string): string {
  const m = /\[chunk:([a-f0-9]+)\]/i.exec(raw);
  return m ? m[1].toLowerCase() : '';
}
