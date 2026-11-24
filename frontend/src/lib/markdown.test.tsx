import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Markdown, renderInline, toBlocks } from "@/lib/markdown";

describe("toBlocks", () => {
  it("groups lines into paragraphs and lists", () => {
    const text =
      "# Result\nWest sold most.\nBy far.\n\n- one\n* two\n\n1. first\n2) second\n\nEnd.";
    expect(toBlocks(text)).toEqual([
      { kind: "paragraph", lines: ["Result", "West sold most.", "By far."] },
      { kind: "bullets", items: ["one", "two"] },
      { kind: "numbers", items: ["first", "second"] },
      { kind: "paragraph", lines: ["End."] },
    ]);
  });

  it("starts a new block when the kind of line changes", () => {
    expect(toBlocks("Intro:\n- a\n- b\nAfter.")).toEqual([
      { kind: "paragraph", lines: ["Intro:"] },
      { kind: "bullets", items: ["a", "b"] },
      { kind: "paragraph", lines: ["After."] },
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

  it("shows HTML from the model as text, never as HTML", () => {
    const attack = '<img src=x onerror="alert(1)"> <script>alert(2)</script>';
    const { container } = render(<Markdown text={attack} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toBe(attack);
  });
});
