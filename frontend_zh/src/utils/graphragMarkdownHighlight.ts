/**
 * Inject a <mark> around the first occurrence of `snippet` in a Markdown string,
 * then let react-markdown + rehype-raw render it as an inline highlight.
 *
 * Data flow: context-refine → cleaned_text + supporting_snippets（或 chunk-snippet 单句）
 *   → NotebookView passes (fullMarkdown, snippet) here
 *   → injected HTML → ReactMarkdown renders the highlight.
 *
 * Search strategy (in order, stops at first hit):
 *   1. Exact verbatim indexOf
 *   2. Strip inline markdown formatting chars (* _ ` ~) and retry
 *   3. Whitespace-normalized: collapse all whitespace to single space, then retry
 *
 * This handles the common mismatch where chunk text comes from MinerU content_list
 * (plain text) but the displayed content is MinerU Markdown (**bold**, _italic_, etc.).
 */

const DEFAULT_MARK_CLASS =
  'bg-amber-200/90 rounded px-0.5 ring-1 ring-amber-300/60';

/** Rotate styles so multiple refs are visually distinct in the sidebar. */
const ALT_MARK_CLASSES = [
  'bg-amber-200/90 rounded px-0.5 ring-1 ring-amber-300/60',
  'bg-sky-200/90 rounded px-0.5 ring-1 ring-sky-300/60',
  'bg-emerald-200/85 rounded px-0.5 ring-1 ring-emerald-300/55',
  'bg-violet-200/85 rounded px-0.5 ring-1 ring-violet-300/55',
];

function markOpenTag(className: string): string {
  const cls = className || DEFAULT_MARK_CLASS;
  return `<mark class="${cls}" data-graphrag-hl="1">`;
}

function htmlEsc(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function wrapRange(full: string, start: number, end: number, markClass: string): string {
  return (
    full.slice(0, start) +
    markOpenTag(markClass) +
    htmlEsc(full.slice(start, end)) +
    '</mark>' +
    full.slice(end)
  );
}

/**
 * Build a stripped version of `md` (inline format chars removed)
 * plus a map from stripped-index → original-index.
 */
function stripMdChars(md: string): { text: string; map: number[] } {
  const map: number[] = [];
  let text = '';
  let i = 0;
  while (i < md.length) {
    const c = md[i];
    if (c === '*' || c === '_' || c === '`') { i++; continue; }
    if (c === '~' && md[i + 1] === '~') { i += 2; continue; }
    // skip HTML tags (e.g. pre-existing <mark>)
    if (c === '<') {
      const end = md.indexOf('>', i);
      if (end >= 0) { i = end + 1; continue; }
    }
    map.push(i);
    text += c;
    i++;
  }
  return { text, map };
}

/**
 * Map a position in the whitespace-normalised version of `s` back to the
 * corresponding position in `s` itself (before normalisation).
 */
function normPosToOrig(s: string, normPos: number): number {
  let norm = 0;
  let orig = 0;
  while (orig < s.length && norm < normPos) {
    if (/\s/.test(s[orig])) {
      // consume entire whitespace run (= one ' ' in normalised)
      while (orig < s.length && /\s/.test(s[orig])) orig++;
      norm++;
    } else {
      orig++;
      norm++;
    }
  }
  return orig;
}

export type InjectHighlightOptions = {
  /** CSS classes for the &lt;mark&gt; (default amber). */
  markClass?: string;
  /** Pick a palette slot 0..3 for multi-source distinction. */
  colorIndex?: number;
};

/** Locate [start, end) in *full* for *snippet* using the same 3-pass strategy as injection. */
export function findGraphragHighlightRange(
  full: string,
  snippet: string,
): { start: number; end: number } | null {
  const sn = snippet.trim();
  if (!full || !sn) return null;

  const i1 = full.indexOf(sn);
  if (i1 >= 0) return { start: i1, end: i1 + sn.length };

  const { text: stripped, map } = stripMdChars(full);
  const i2 = stripped.indexOf(sn);
  if (i2 >= 0 && i2 + sn.length - 1 < map.length) {
    return { start: map[i2], end: map[i2 + sn.length - 1] + 1 };
  }

  const normSn = sn.replace(/\s+/g, ' ');
  const normStripped = stripped.replace(/\s+/g, ' ');
  const i3 = normStripped.indexOf(normSn);
  if (i3 < 0) return null;

  const stripStart = normPosToOrig(stripped, i3);
  const stripEnd = normPosToOrig(stripped, i3 + normSn.length);

  if (stripStart >= map.length) return null;
  const origStart = map[stripStart];
  const origEnd = stripEnd < map.length ? map[stripEnd] : map[map.length - 1] + 1;
  return { start: origStart, end: origEnd };
}

function markClassForOptions(options?: InjectHighlightOptions, slot = 0): string {
  let markClass = options?.markClass || '';
  if (!markClass && options?.colorIndex != null) {
    const i =
      (Math.max(0, Math.floor(options.colorIndex)) + slot) % ALT_MARK_CLASSES.length;
    markClass = ALT_MARK_CLASSES[i]!;
  }
  if (!markClass) markClass = DEFAULT_MARK_CLASS;
  return markClass;
}

export function injectGraphragHighlightInMarkdown(
  full: string,
  snippet: string,
  options?: InjectHighlightOptions,
): string {
  const sn = snippet.trim();
  if (!full || !sn) return full;
  const markClass = markClassForOptions(options, 0);
  const r = findGraphragHighlightRange(full, snippet);
  if (!r) return full;
  return wrapRange(full, r.start, r.end, markClass);
}

export type InjectMultipleHighlightsOptions = InjectHighlightOptions & {
  /** First palette slot when using colorIndex rotation (default 0). */
  baseColorIndex?: number;
};

/** Wrap multiple non-overlapping snippets (rightmost first) so indices stay valid on the original *full*. */
export function injectMultipleGraphragHighlightsInMarkdown(
  full: string,
  snippets: string[],
  options?: InjectMultipleHighlightsOptions,
): string {
  if (!full || !snippets.length) return full;
  const base = options?.baseColorIndex ?? options?.colorIndex ?? 0;
  const ranges: { start: number; end: number; slot: number }[] = [];
  let k = 0;
  for (const raw of snippets) {
    const r = findGraphragHighlightRange(full, raw);
    if (!r) continue;
    ranges.push({ ...r, slot: k++ });
  }
  ranges.sort((a, b) => a.start - b.start);
  const merged: typeof ranges = [];
  for (const r of ranges) {
    const prev = merged[merged.length - 1];
    if (prev && r.start < prev.end) continue;
    merged.push(r);
  }
  merged.sort((a, b) => b.start - a.start);
  let out = full;
  for (const r of merged) {
    const mc = markClassForOptions(
      options?.markClass
        ? { markClass: options.markClass }
        : { colorIndex: base + r.slot },
      0,
    );
    out = wrapRange(out, r.start, r.end, mc);
  }
  return out;
}
