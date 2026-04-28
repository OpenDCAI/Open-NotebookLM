function stripShapeDecorators(text: string): string {
  return text
    .replace(/^\(\((.+?)\)\)$/, "$1")
    .replace(/^\((.+?)\)$/, "$1")
    .replace(/^\[(.+?)\]$/, "$1")
    .replace(/^\{\{(.+?)\}\}$/, "$1")
    .replace(/^\)(.+?)\($/, "$1")
    .replace(/^>(.+?)\]$/, "$1");
}

export function mermaidToMarkdown(mermaidCode: string): string {
  const lines = mermaidCode.split("\n");
  const result: string[] = [];
  const indentStack: number[] = [];

  for (const line of lines) {
    const trimmed = line.trimEnd();
    if (!trimmed || trimmed.trim() === "mindmap") continue;

    const indent = line.length - line.trimStart().length;
    let text = trimmed.trim();

    if (text.startsWith("root")) {
      text = text.replace(/^root\s*/, "").trim();
      text = stripShapeDecorators(text);
      indentStack.length = 0;
      indentStack.push(indent);
      result.push(`# ${text}`);
      continue;
    }

    text = stripShapeDecorators(text);

    while (indentStack.length > 1 && indent <= indentStack[indentStack.length - 1]) {
      indentStack.pop();
    }

    if (indent > indentStack[indentStack.length - 1]) {
      indentStack.push(indent);
    }

    const depth = Math.min(indentStack.length, 6);
    result.push(`${"#".repeat(depth)} ${text}`);
  }

  return result.join("\n");
}

export function isMermaidMindmap(code: string): boolean {
  return code.trimStart().startsWith("mindmap");
}

let nodeIdCounter = 0;

function needsEscape(text: string): boolean {
  return /[()[\]{}<>"'/\\,;:!?]/.test(text);
}

export function markdownToMermaid(markdown: string): string {
  nodeIdCounter = 0;
  const lines = markdown.split("\n");
  const result: string[] = ["mindmap"];

  for (const line of lines) {
    const match = line.match(/^(#{1,6})\s+(.+)/);
    if (!match) continue;

    const depth = match[1].length;
    const text = match[2].trim();
    const indent = "  ".repeat(depth);

    if (depth === 1) {
      if (needsEscape(text)) {
        result.push(`${indent}root["${text}"]`);
      } else {
        result.push(`${indent}root(${text})`);
      }
      continue;
    }

    if (needsEscape(text)) {
      const id = `n${++nodeIdCounter}`;
      result.push(`${indent}${id}["${text}"]`);
    } else {
      result.push(`${indent}${text}`);
    }
  }

  return result.join("\n");
}
