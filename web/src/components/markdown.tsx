/**
 * Renders the small Markdown subset the shared metric definitions use (from the Python views):
 * paragraphs, "- " and "1. " lists, **bold**, *italic* and `code`. Content is our own, but it is
 * rendered as React elements (no raw HTML), so nothing in it can inject markup.
 */
import { Fragment, type ReactNode } from "react";

function inline(text: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={i}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("*") && part.endsWith("*") && part.length > 2) return <em key={i}>{part.slice(1, -1)}</em>;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={i}>{part.slice(1, -1)}</code>;
    return <Fragment key={i}>{part}</Fragment>;
  });
}

type Block = { kind: "p" | "ul" | "ol"; lines: string[] };

function blocks(source: string): Block[] {
  const result: Block[] = [];
  for (const raw of source.split("\n")) {
    const line = raw.trim();
    if (!line) {
      result.push({ kind: "p", lines: [] });
      continue;
    }
    const kind = /^- /.test(line) ? "ul" : /^\d+\. /.test(line) ? "ol" : "p";
    const text = kind === "ul" ? line.slice(2) : kind === "ol" ? line.replace(/^\d+\. /, "") : line;
    const last = result[result.length - 1];
    if (last && last.kind === kind && (kind !== "p" || last.lines.length > 0)) last.lines.push(text);
    else result.push({ kind, lines: [text] });
  }
  return result.filter((b) => b.lines.length > 0);
}

export function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    <div className={className}>
      {blocks(children).map((block, i) => {
        if (block.kind === "ul")
          return (
            <ul key={i} className="my-2 list-disc space-y-1 pl-5">
              {block.lines.map((l, j) => (
                <li key={j}>{inline(l)}</li>
              ))}
            </ul>
          );
        if (block.kind === "ol")
          return (
            <ol key={i} className="my-2 list-decimal space-y-1 pl-5">
              {block.lines.map((l, j) => (
                <li key={j}>{inline(l)}</li>
              ))}
            </ol>
          );
        return (
          <p key={i} className="my-2">
            {inline(block.lines.join(" "))}
          </p>
        );
      })}
    </div>
  );
}
