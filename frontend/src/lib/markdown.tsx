/**
 * A small Markdown renderer for the agent's answers.
 *
 * Claude writes its answers in Markdown: paragraphs, bullet and numbered
 * lists, **bold** and `code`. This file renders only that much, and it
 * builds React elements, never an HTML string. So text from the model, or
 * from a CSV file that the model quotes, always appears as text: `<script>`
 * shows up as those characters and can never run.
 */

import type { ReactNode } from "react";

/** One item of a list, with the bullets indented under it. */
interface ListItem {
  text: string;
  sub: string[];
}

type Block =
  | { kind: "paragraph"; lines: string[] }
  | { kind: "bullets"; items: ListItem[] }
  | { kind: "numbers"; items: ListItem[]; start: number };

const BULLET = /^(\s*)[-*•]\s+(.*)$/;
// At most 9 digits, so that the number always fits.
const NUMBERED = /^(\s*)(\d{1,9})[.)]\s+(.*)$/;
const HEADING = /^#{1,6}\s+(.*)$/;
// **bold** or `code`. The capture group keeps the matches in split()'s result.
const INLINE = /(\*\*[^*]+\*\*|`[^`]+`)/;

/** One line of the answer, without its marker. */
interface Line {
  kind: Block["kind"];
  text: string;
  /** The number the model wrote before a numbered line. */
  number: number;
  /** How many spaces come before the marker of a list line (a tab counts as 4). */
  indent: number;
}

/** The width of the spaces before a marker. */
function widthOf(spaces = ""): number {
  return spaces.replaceAll("\t", "    ").length;
}

/** Which kind of block a line belongs to, and its text without the marker. */
function classify(line: string): Line {
  const bullet = BULLET.exec(line);
  if (bullet) {
    return { kind: "bullets", text: bullet[2] ?? "", number: 0, indent: widthOf(bullet[1]) };
  }
  const numbered = NUMBERED.exec(line);
  if (numbered) {
    const number = Number(numbered[2]);
    return { kind: "numbers", text: numbered[3] ?? "", number, indent: widthOf(numbered[1]) };
  }
  const text = (HEADING.exec(line)?.[1] ?? line).trim();
  return { kind: "paragraph", text, number: 0, indent: 0 };
}

/** A new block that starts with this line. */
function newBlock(line: Line): Block {
  const item: ListItem = { text: line.text, sub: [] };
  switch (line.kind) {
    case "paragraph":
      return { kind: "paragraph", lines: [line.text] };
    case "bullets":
      return { kind: "bullets", items: [item] };
    case "numbers":
      // A list keeps its numbers, even when blank lines split it into blocks.
      return { kind: "numbers", items: [item], start: line.number };
  }
}

/**
 * Add the line to the block, if it belongs there. Returns false if it doesn't.
 * A `nested` line is a bullet indented further than the items of the list.
 */
function addTo(block: Block, line: Line, nested: boolean): boolean {
  if (block.kind === "paragraph") {
    if (line.kind === "paragraph") {
      block.lines.push(line.text);
    }
    return line.kind === "paragraph";
  }
  // A bullet indented further than the list's items belongs to the item above it.
  const item = block.items.at(-1);
  if (nested && item !== undefined) {
    item.sub.push(line.text);
    return true;
  }
  if (line.kind === block.kind) {
    block.items.push({ text: line.text, sub: [] });
  }
  return line.kind === block.kind;
}

/** Group lines into blocks: a blank line, or a change of kind, starts a new block. */
export function toBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  let open = false; // false right after a blank line
  let indent = 0; // how far the items of the last block are indented
  for (const raw of text.split(/\r?\n/)) {
    if (raw.trim() === "") {
      open = false;
      continue;
    }
    const line = classify(raw);
    const last = blocks.at(-1);
    // Two more spaces than the list's items put a bullet under the item above.
    const nested = line.kind === "bullets" && line.indent >= indent + 2;
    if (!open || last === undefined || !addTo(last, line, nested)) {
      blocks.push(newBlock(line));
      indent = line.indent;
    } else if (!nested) {
      // An item further left than the block's first line: the list's items are there.
      indent = Math.min(indent, line.indent);
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

function renderItems(items: ListItem[]): ReactNode[] {
  return items.map((item, i) => (
    <li key={i}>
      {renderInline(item.text)}
      {item.sub.length > 0 && (
        <ul>
          {item.sub.map((text, j) => (
            <li key={j}>{renderInline(text)}</li>
          ))}
        </ul>
      )}
    </li>
  ));
}

function renderBlock(block: Block, key: number): ReactNode {
  switch (block.kind) {
    case "paragraph":
      return <p key={key}>{renderInline(block.lines.join(" "))}</p>;
    case "bullets":
      return <ul key={key}>{renderItems(block.items)}</ul>;
    case "numbers":
      return (
        <ol key={key} start={block.start}>
          {renderItems(block.items)}
        </ol>
      );
  }
}

/** The agent's answer, as paragraphs and lists. */
export function Markdown({ text }: { text: string }) {
  return <>{toBlocks(text).map(renderBlock)}</>;
}
