import type { Metadata } from "next";

import { Markdown } from "@/components/markdown";
import { ProvenanceLine } from "@/components/site/provenance-line";
import { PageIntro } from "@/components/story/page-parts";
import { readMeta, readView } from "@/data/load";
import { validation } from "@/data/schemas";
import { count } from "@/lib/format";

export const metadata: Metadata = { title: "Data and validation" };

function Table({ rows, caption }: { rows: Record<string, string | number | null>[]; caption: string }) {
  const rawColumns = rows.length ? Object.keys(rows[0]) : [];
  const columns = rawColumns.includes("Check")
    ? ["Check", ...rawColumns.filter((c) => c !== "Check")]
    : rawColumns;
  return (
    <div
      className="max-w-full overflow-x-auto rounded-lg border border-rule bg-surface"
      tabIndex={0}
      role="region"
      aria-label={caption}
    >
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-paper">
          <tr>
            {columns.map((c) => (
              <th
                key={c}
                scope="col"
                className="border-b border-rule px-3 py-2 text-left text-xs font-semibold text-muted-ink"
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-t border-panel hover:bg-paper/70">
              {columns.map((c, j) =>
                j === 0 ? (
                  <th key={c} scope="row" className="px-3 py-2 text-left font-medium text-ink">
                    {row[c]}
                  </th>
                ) : (
                  <td key={c} className="num px-3 py-2 text-ink">
                    {typeof row[c] === "number" ? count(row[c] as number) : (row[c] ?? "—")}
                  </td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Section({
  number,
  title,
  question,
  children,
}: {
  number: string;
  title: string;
  question: string;
  children: React.ReactNode;
}) {
  return (
    <section
      className="rounded-xl border border-rule bg-surface p-5 shadow-xs"
      aria-labelledby={`section-${number}`}
    >
      <div className="flex flex-wrap items-baseline gap-2 border-b border-panel pb-3">
        <span className="num rounded-md bg-brand-soft px-2 py-0.5 text-xs font-semibold text-brand">
          {number}
        </span>
        <h2 id={`section-${number}`} className="text-lg font-bold tracking-tight text-ink">
          {title}
        </h2>
      </div>
      <p className="mt-3 max-w-prose text-sm text-muted-ink">{question}</p>
      <div className="mt-4">{children}</div>
    </section>
  );
}

export default function Page() {
  const meta = readMeta();
  const { data, source } = readView("validation.json", validation);
  const evidence = meta.snapshot.evidence;
  const link = (file: string) => (
    <a href={`/evidence/${file}`} className="mono-id text-xs">
      {file}
    </a>
  );
  return (
    <div className="space-y-5">
      <PageIntro section="Data quality" title="The evidence behind every number">
        What the data is, and the evidence that the pipeline processed it correctly. Every figure on this page is read
        from a result file of the validated run; nothing is typed in by hand. Each file is published here with its
        SHA-256 hash so the evidence can be verified against the repository.
      </PageIntro>

      <Section number="01" title="Dataset provenance" question="Where does the data come from?">
        <Table rows={data.datasets} caption="Datasets" />
        <p className="mt-3 text-xs text-muted-ink">
          The archive holds the feeds as the MTA published them. They are replayed through Kafka as protobuf messages,
          as a live feed would arrive; the pipeline does not connect to the live MTA feeds. Source data from the MTA,
          used under the MTA Terms of Use; not endorsed by the MTA.
        </p>
      </Section>

      <Section number="02" title="Source integrity" question="Did the data reach the lakehouse complete and unaltered?">
        {data.integrity.available ? (
          <>
            <Table rows={data.integrity_table} caption="Source integrity checks per feed" />
            <p className="mt-3 text-xs text-muted-ink">
              Evidence:{" "}
              {data.integrity.files.map((f, i) => (
                <span key={f}>
                  {i ? ", " : ""}
                  {link(f)}
                </span>
              ))}
              .
            </p>
          </>
        ) : (
          <p className="text-sm text-muted-ink">Not yet measured (no {data.integrity.files.join(", ")}).</p>
        )}
      </Section>

      <Section
        number="03"
        title="Golden-reference parity"
        question="The same rules were implemented a second time, independently, as DuckDB SQL over the raw archive. Does every Spark table equal its golden counterpart?"
      >
        <p className="mb-4 max-w-prose text-xs text-muted-ink">
          Silver holds the cleaned arrivals matched to the timetable; Gold holds the result tables this site shows. The
          golden reference is the separate DuckDB implementation they are compared with: same rules, different code.
        </p>
        {data.parity.available ? (
          <>
            <dl className="grid gap-3.5 sm:grid-cols-2">
              {data.parity.layers.map((layer) => (
                <div
                  key={layer.layer}
                  className="rounded-lg border border-rule bg-paper p-4"
                  data-testid={`parity-${layer.layer}`}
                >
                  <dt className="text-xs font-semibold text-muted-ink">
                    {layer.layer} tables equal to golden
                  </dt>
                  <dd className="num mt-1 text-3xl font-bold tracking-tight text-ink">
                    {layer.passed} / {layer.total}
                  </dd>
                  <dd className="mt-1 text-xs text-muted-ink">Evidence: {link(layer.file)}</dd>
                </div>
              ))}
            </dl>
            <details className="mt-4 rounded-lg border border-rule bg-paper px-4 py-2.5">
              <summary className="min-h-10 cursor-pointer py-1 text-sm font-semibold text-ink">
                Every table compared
              </summary>
              <div className="pt-2">
                <Table rows={data.parity_tables} caption="Tables compared with the golden reference" />
              </div>
            </details>
            <details className="mt-2.5 rounded-lg border border-rule bg-paper px-4 py-2.5">
              <summary className="min-h-10 cursor-pointer py-1 text-sm font-semibold text-ink">
                Tolerance policy
              </summary>
              <div className="pt-2">
                <Markdown className="max-w-prose text-sm text-muted-ink">{data.policy}</Markdown>
                <p className="mt-2 text-xs text-muted-ink">Evidence: {link("tolerance.json")}</p>
              </div>
            </details>
            <p className="mt-3 max-w-prose text-xs text-muted-ink">
              Parity shows that two independent implementations of the same written rules agree; it does not show that
              the rules themselves are the best possible definition.
            </p>
          </>
        ) : (
          <p className="text-sm text-muted-ink">Not yet measured.</p>
        )}
      </Section>

      <Section number="04" title="Automated tests" question="Are the code paths exercised automatically?">
        {data.tests.available ? (
          <dl className="grid gap-3.5 sm:grid-cols-2">
            <div className="rounded-lg border border-rule bg-paper p-4">
              <dt className="text-xs font-semibold text-muted-ink">Tests passed</dt>
              <dd className="num mt-1 text-3xl font-bold tracking-tight text-ink" data-testid="tests-passed">
                {count(data.tests.passed)} / {count(data.tests.ran)}
              </dd>
              <dd className="mt-1 text-xs text-muted-ink">
                {count(data.tests.failed)} failed, {count(data.tests.skipped)} skipped. Evidence:{" "}
                {link(data.tests.file)}
              </dd>
            </div>
          </dl>
        ) : (
          <p className="text-sm text-muted-ink">Not yet measured (no {data.tests.file}).</p>
        )}
      </Section>

      <Section
        number="05"
        title="Files of this snapshot"
        question="Which files does this site serve, and can they be verified?"
      >
        <div
          className="max-w-full overflow-x-auto rounded-lg border border-rule bg-surface"
          tabIndex={0}
          role="region"
          aria-label="Snapshot files"
        >
          <table className="w-full border-collapse text-sm">
            <caption className="sr-only">Snapshot tables and evidence files with their SHA-256</caption>
            <thead className="bg-paper">
              <tr>
                <th scope="col" className="border-b border-rule px-3 py-2 text-left text-xs font-semibold text-muted-ink">
                  File
                </th>
                <th scope="col" className="border-b border-rule px-3 py-2 text-right text-xs font-semibold text-muted-ink">
                  Rows
                </th>
                <th scope="col" className="border-b border-rule px-3 py-2 text-left text-xs font-semibold text-muted-ink">
                  Compared with golden
                </th>
                <th scope="col" className="border-b border-rule px-3 py-2 text-left text-xs font-semibold text-muted-ink">
                  SHA-256
                </th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(meta.snapshot.tables).map(([name, t]) => (
                <tr key={name} className="border-t border-panel hover:bg-paper/70">
                  <th scope="row" className="mono-id px-3 py-2 text-left text-xs font-medium text-ink">
                    {name}.parquet
                  </th>
                  <td className="num px-3 py-2 text-right">{count(t.rows)}</td>
                  <td className="px-3 py-2">{t.validated ? "Yes" : "Reference data (no golden counterpart)"}</td>
                  <td className="mono-id whitespace-normal break-all px-3 py-2 text-xs text-muted-ink">
                    {t.sha256}
                  </td>
                </tr>
              ))}
              {Object.entries(evidence).map(([name, sha]) => (
                <tr key={name} className="border-t border-panel hover:bg-paper/70">
                  <th scope="row" className="px-3 py-2 text-left font-medium">
                    {link(name)}
                  </th>
                  <td className="px-3 py-2" />
                  <td className="px-3 py-2">Evidence file</td>
                  <td className="mono-id whitespace-normal break-all px-3 py-2 text-xs text-muted-ink">{sha}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <div className="rounded-xl border border-rule bg-surface px-5 py-3 shadow-xs">
        <ProvenanceLine source={source} />
      </div>
    </div>
  );
}
