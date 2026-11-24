/**
 * A small Markdown renderer for the agent's answers.
 *
 * Claude writes its answers in Markdown: paragraphs, bullet lists, **bold**
 * and `code`. This file renders only that much, and it builds React elements,
 * never an HTML string. So text from the model, or from a CSV file that the
 * model quotes, always appears as text: `<script>` shows up as those
 * characters and can never run.
 */

import type { ReactNode } from "react";

type Block =
  { kind: "paragraph"; lines: string[] } | { kind: "bullets" | "numbers"; items: string[] };

const BULLET = /^\s*[-*•]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
const HEADING = /^#{1,6}\s+(.*)$/;
// **bold** or `code`. The capture group keeps the matches in split()'s result.
const INLINE = /(\*\*[^*]+\*\*|`[^`]+`)/;

/** Which kind of block a line belongs to, and its text without the marker. */
function classify(line: string): { kind: Block["kind"]; text: string } {
  const bullet = BULLET.exec(line);
  if (bullet) {
    return { kind: "bullets", text: bullet[1] ?? "" };
  }
  const numbered = NUMBERED.exec(line);
  if (numbered) {
    return { kind: "numbers", text: numbered[1] ?? "" };
  }
  return { kind: "paragraph", text: (HEADING.exec(line)?.[1] ?? line).trim() };
}

/** Group lines into blocks: a blank line, or a change of kind, starts a new block. */
export function toBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  let open = false; // false right after a blank line
  for (const line of text.split(/\r?\n/)) {
    if (line.trim() === "") {
      open = false;
      continue;
    }
    const { kind, text: content } = classify(line);
    const last = blocks.at(-1);
    if (open && last?.kind === kind) {
      if (last.kind === "paragraph") {
        last.lines.push(content);
      } else {
        last.items.push(content);
      }
    } else {
      blocks.push(kind === "paragraph" ? { kind, lines: [content] } : { kind, items: [content] });
    }
    open = true;
  }
  return blocks;
}

/** Text with **bold** and `code` turned into elements. */
export function renderInline(text: string): ReactNode[] {
  return text
    .split(INLINE)
    .filter((part) => part !== "")
    .map((part, i) => {
      if (part.length > 4 && part.startsWith("**") && part.endsWith("**")) {
        return <strong key={i}>{part.slice(2, -2)}</strong>;
      }
      if (part.length > 2 && part.startsWith("`") && part.endsWith("`")) {
        return <code key={i}>{part.slice(1, -1)}</code>;
      }
      return part;
    });
}

function renderBlock(block: Block, key: number): ReactNode {
  switch (block.kind) {
    case "paragraph":
      return <p key={key}>{renderInline(block.lines.join(" "))}</p>;
    case "bullets":
      return (
        <ul key={key}>
          {block.items.map((item, i) => (
            <li key={i}>{renderInline(item)}</li>
          ))}
        </ul>
      );
    case "numbers":
      return (
        <ol key={key}>
          {block.items.map((item, i) => (
            <li key={i}>{renderInline(item)}</li>
          ))}
        </ol>
      );
  }
}

/** The agent's answer, as paragraphs and lists. */
export function Markdown({ text }: { text: string }) {
  return <>{toBlocks(text).map(renderBlock)}</>;
}
