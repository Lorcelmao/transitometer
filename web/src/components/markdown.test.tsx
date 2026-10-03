import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Markdown } from "@/components/markdown";

describe("Markdown (the definitions' subset)", () => {
  it("renders lists, emphasis and paragraphs as elements, never as raw HTML", () => {
    const { container } = render(
      <Markdown>{"Intro with **bold**.\n- one *two*\n- `code`\n\n1. first\n2. second\n\n<b>not html</b>"}</Markdown>,
    );
    expect(container.querySelectorAll("ul > li")).toHaveLength(2);
    expect(container.querySelectorAll("ol > li")).toHaveLength(2);
    expect(container.querySelector("strong")?.textContent).toBe("bold");
    expect(container.querySelector("em")?.textContent).toBe("two");
    expect(container.querySelector("code")?.textContent).toBe("code");
    expect(container.querySelector("b")).toBeNull();
    expect(container.textContent).toContain("<b>not html</b>");
  });
});
