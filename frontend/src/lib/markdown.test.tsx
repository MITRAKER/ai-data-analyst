import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Markdown, renderInline, toBlocks } from "@/lib/markdown";

/** A list item without bullets under it. */
function item(text: string, sub: string[] = []) {
  return { text, sub };
}

describe("toBlocks", () => {
  it("groups lines into paragraphs and lists", () => {
    const text =
      "# Result\nWest sold most.\nBy far.\n\n- one\n* two\n\n1. first\n2) second\n\nEnd.";
    expect(toBlocks(text)).toEqual([
      { kind: "paragraph", lines: ["Result", "West sold most.", "By far."] },
      { kind: "bullets", items: [item("one"), item("two")] },
      { kind: "numbers", items: [item("first"), item("second")], start: 1 },
      { kind: "paragraph", lines: ["End."] },
    ]);
  });

  it("starts a new block when the kind of line changes", () => {
    expect(toBlocks("Intro:\n- a\n- b\nAfter.")).toEqual([
      { kind: "paragraph", lines: ["Intro:"] },
      { kind: "bullets", items: [item("a"), item("b")] },
      { kind: "paragraph", lines: ["After."] },
    ]);
  });

  it("keeps the numbers of a list that blank lines split", () => {
    expect(toBlocks("1. West\n\n2. East\n\n3. North")).toEqual([
      { kind: "numbers", items: [item("West")], start: 1 },
      { kind: "numbers", items: [item("East")], start: 2 },
      { kind: "numbers", items: [item("North")], start: 3 },
    ]);
  });

  it("puts indented bullets under the list item above them", () => {
    const text = "1. **West**\n   - strongest in Q4\n   - online grew\n2. **East**\n  * steady";
    expect(toBlocks(text)).toEqual([
      {
        kind: "numbers",
        items: [item("**West**", ["strongest in Q4", "online grew"]), item("**East**", ["steady"])],
        start: 1,
      },
    ]);
    // After a paragraph, an indented bullet starts a list of its own.
    expect(toBlocks("Notes:\n  - one")).toEqual([
      { kind: "paragraph", lines: ["Notes:"] },
      { kind: "bullets", items: [item("one")] },
    ]);
  });

  it("compares the indent with the list's own items, not with the margin", () => {
    // A whole list indented by two spaces: its items stay side by side.
    expect(toBlocks("Notes:\n  - one\n  - two")).toEqual([
      { kind: "paragraph", lines: ["Notes:"] },
      { kind: "bullets", items: [item("one"), item("two")] },
    ]);
    expect(toBlocks("  - a\n    - a1\n  - b")).toEqual([
      { kind: "bullets", items: [item("a", ["a1"]), item("b")] },
    ]);
    // After a blank line, an indented list starts again from its own items.
    expect(toBlocks("1. a\n\n   - x\n   - y")).toEqual([
      { kind: "numbers", items: [item("a")], start: 1 },
      { kind: "bullets", items: [item("x"), item("y")] },
    ]);
    // A tab counts as four spaces.
    expect(toBlocks("- a\n\t- a1")).toEqual([{ kind: "bullets", items: [item("a", ["a1"])] }]);
    // A numbered list indented as a whole counts from its own items too.
    expect(toBlocks("   1. a\n   - note")).toEqual([
      { kind: "numbers", items: [item("a")], start: 1 },
      { kind: "bullets", items: [item("note")] },
    ]);
    // One space more is not enough to nest.
    expect(toBlocks("- a\n - b")).toEqual([{ kind: "bullets", items: [item("a"), item("b")] }]);
  });

  it("finds the list's items further left than the block's first line", () => {
    // After a blank line, the block starts with sub-bullets; the next item is further left.
    expect(toBlocks("- West\n\n  - Online\n  - Retail\n- East\n  - Online")).toEqual([
      { kind: "bullets", items: [item("West")] },
      { kind: "bullets", items: [item("Online"), item("Retail"), item("East", ["Online"])] },
    ]);
  });

  it("returns nothing for empty text", () => {
    expect(toBlocks("\n  \n")).toEqual([]);
  });
});

describe("renderInline", () => {
  it("turns **bold** and `code` into elements", () => {
    render(<p>{renderInline("**West** sold `$572k`, see ** and `")}</p>);
    expect(screen.getByText("West").tagName).toBe("STRONG");
    expect(screen.getByText("$572k").tagName).toBe("CODE");
  });
});

describe("Markdown", () => {
  it("renders paragraphs and lists", () => {
    const { container } = render(<Markdown text={"Top: **West**.\n\n- East\n- North\n\n1. a"} />);
    expect(container.querySelectorAll("p")).toHaveLength(1);
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    expect(container.querySelector("ol li")?.textContent).toBe("a");
  });

  it("numbers each item as the model did, also with bullets in between", () => {
    const text = "Top regions:\n\n1. West\n   - strongest in Q4\n\n2. East\n\n3. North";
    const { container } = render(<Markdown text={text} />);
    const lists = [...container.querySelectorAll("ol")];
    expect(lists.map((list) => list.start)).toEqual([1, 2, 3]);
    expect(container.querySelector("ol li ul li")?.textContent).toBe("strongest in Q4");
  });

  it("shows HTML from the model as text, never as HTML", () => {
    const attack = '<img src=x onerror="alert(1)"> <script>alert(2)</script>';
    const { container } = render(<Markdown text={attack} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toBe(attack);
  });
});
