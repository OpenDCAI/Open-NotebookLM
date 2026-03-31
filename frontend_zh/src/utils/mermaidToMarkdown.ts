/**
 * Convert Mermaid mindmap syntax to Markdown headings format.
 * Used as fallback for legacy .mmd files.
 *
 * Input example:
 *   mindmap
 *     root((Central Topic))
 *       Topic 1
 *         Sub 1.1
 *       Topic 2
 *
 * Output:
 *   # Central Topic
 *   ## Topic 1
 *   ### Sub 1.1
 *   ## Topic 2
 */

function stripShapeDecorators(text: string): string {
  return text
    .replace(/^\(\((.+?)\)\)$/, '$1')
    .replace(/^\((.+?)\)$/, '$1')
    .replace(/^\[(.+?)\]$/, '$1')
    .replace(/^\{\{(.+?)\}\}$/, '$1')
    .replace(/^\)(.+?)\($/, '$1')
    .replace(/^>(.+?)\]$/, '$1');
}

export function mermaidToMarkdown(mermaidCode: string): string {
  const lines = mermaidCode.split('\n');
  const result: string[] = [];
  let baseIndent = -1;
  let indentUnit = 2;

  for (const line of lines) {
    const trimmed = line.trimEnd();
    if (!trimmed || trimmed.trim() === 'mindmap') continue;

    const indent = line.length - line.trimStart().length;
    let text = trimmed.trim();

    // Handle root line
    if (text.startsWith('root')) {
      text = text.replace(/^root\s*/, '').trim();
      text = stripShapeDecorators(text);
      baseIndent = indent;
      result.push(`# ${text}`);
      continue;
    }

    // Detect indent unit from first non-root indented line
    if (baseIndent >= 0 && indent > baseIndent && indentUnit === 2) {
      indentUnit = indent - baseIndent;
    }

    text = stripShapeDecorators(text);

    const depth = Math.max(1, Math.floor((indent - baseIndent) / indentUnit) + 1);
    const hashes = '#'.repeat(Math.min(depth, 6));
    result.push(`${hashes} ${text}`);
  }

  return result.join('\n');
}

/**
 * Detect if the input is Mermaid mindmap syntax (vs already Markdown).
 */
export function isMermaidMindmap(code: string): boolean {
  const trimmed = code.trimStart();
  return trimmed.startsWith('mindmap');
}

/**
 * Convert Markdown headings to Mermaid mindmap syntax.
 *
 * Input:
 *   # Central Topic
 *   ## Topic 1
 *   ### Sub 1.1
 *
 * Output:
 *   mindmap
 *     root((Central Topic))
 *       Topic 1
 *         Sub 1.1
 */
let _nodeIdCounter = 0;

function needsEscape(text: string): boolean {
  return /[()[\]{}<>"'/\\,;:!?]/.test(text);
}

export function markdownToMermaid(markdown: string): string {
  _nodeIdCounter = 0;
  const lines = markdown.split('\n');
  const result: string[] = ['mindmap'];

  for (const line of lines) {
    const match = line.match(/^(#{1,6})\s+(.+)/);
    if (!match) continue;

    const depth = match[1].length;
    const text = match[2].trim();
    const indent = '  '.repeat(depth);

    if (depth === 1) {
      // Root node: use round shape
      if (needsEscape(text)) {
        result.push(`${indent}root["${text}"]`);
      } else {
        result.push(`${indent}root(${text})`);
      }
    } else if (needsEscape(text)) {
      // Nodes with special chars: use id["text"] syntax
      const id = `n${++_nodeIdCounter}`;
      result.push(`${indent}${id}["${text}"]`);
    } else {
      result.push(`${indent}${text}`);
    }
  }

  return result.join('\n');
}
