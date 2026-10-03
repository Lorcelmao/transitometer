import type { Metadata } from "next";

import { Markdown } from "@/components/markdown";
import { ProvenanceLine } from "@/components/site/provenance-line";
import { PageIntro } from "@/components/story/page-parts";
import { readMeta, readView } from "@/data/load";
import { validation } from "@/data/schemas";
import { count } from "@/lib/format";

export const metadata: Metadata = { title: "Data & validation" };

function Table({ rows, caption }: { rows: Record<string, string | number | null>[]; caption: string }) {
  const columns = rows.length ? Object.keys(rows[0]) : [];
  return (
    <div className="overflow-x-auto border-y border-rule" tabIndex={0} role="region" aria-label={caption}>
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-panel">
          <tr>
            {columns.map((c) => (
              <th key={c} scope="col" className="px-3 py-2 text-left text-xs font-medium uppercase tracking-wider text-muted-ink">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-t border-rule/60">
              {columns.map((c, j) =>
                j === 0 ? (
                  <th key={c} scope="row" className="px-3 py-1.5 text-left font-medium">
                    {row[c]}
                  </th>
                ) : (
                  <td key={c} className="num px-3 py-1.5">
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

function Section({ number, title, question, children }: { number: string; title: string; question: string; children: React.ReactNode }) {
  return (
    <section className="mt-14" aria-labelledby={`section-${number}`}>
      <div className="border-b border-ink pb-2">
        <span className="num text-sm text-accent-red">{number}</span>
        <h2 id={`section-${number}`} className="font-display text-2xl md:text-3xl">
          {title}
        </h2>
      </div>
      <p className="mt-3 max-w-prose">{question}</p>
      <div className="mt-4">{children}</div>
    </section>
  );
}

export default function Page() {
  const meta = readMeta();
  const { data, source } = readView("validation.json", validation);
  const evidence = meta.snapshot.evidence;
  const link = (file: string) => (
    <a href={`/evidence/${file}`} className="num">
      {file}
    </a>
  );
  return (
    <>
      <PageIntro section="Data quality" title="The evidence behind every number">
        What the data is, and the evidence that the pipeline processed it correctly. Every figure on
        this page is read from a result file of the validated run; nothing is typed in by hand. Each
        file is published here with its SHA-256, so the evidence can be checked against the repository.
      </PageIntro>

      <Section number="01" title="Dataset provenance" question="Where does the data come from?">
        <Table rows={data.datasets} caption="Datasets" />
        <p className="mt-3 text-sm text-muted-ink">
          The archive holds the feeds as the MTA published them. They are replayed through Kafka as
          protobuf messages, as a live feed would arrive; the pipeline does not connect to the live
          MTA feeds. Source data from the MTA, used under the MTA Terms of Use; not endorsed by the MTA.
        </p>
      </Section>

      <Section number="02" title="Source integrity" question="Did the data reach the lakehouse complete and unaltered?">
        {data.integrity.available ? (
          <>
            <Table rows={data.integrity_table} caption="Source integrity checks per feed" />
            <p className="mt-3 text-sm text-muted-ink">Evidence: {data.integrity.files.map((f, i) => <span key={f}>{i ? ", " : ""}{link(f)}</span>)}.</p>
          </>
        ) : (
          <p>Not yet measured (no {data.integrity.files.join(", ")}).</p>
        )}
      </Section>

      <Section
        number="03"
        title="Golden-reference parity"
        question="The same rules were implemented a second time, independently, as DuckDB SQL over the raw archive. Does every Spark table equal its golden counterpart?"
      >
        {data.parity.available ? (
          <>
            <dl className="grid gap-6 sm:grid-cols-2">
              {data.parity.layers.map((layer) => (
                <div key={layer.layer} className="border-t-2 border-ink pt-2" data-testid={`parity-${layer.layer}`}>
                  <dt className="text-xs font-medium uppercase tracking-wider text-muted-ink">{layer.layer} tables equal to golden</dt>
                  <dd className="num mt-1 text-4xl">
                    {layer.passed} / {layer.total}
                  </dd>
                  <dd className="mt-1 text-sm">Evidence: {link(layer.file)}</dd>
                </div>
              ))}
            </dl>
            <details className="mt-6 border-y border-rule py-3">
              <summary className="min-h-11 cursor-pointer py-2 font-medium">Every table compared</summary>
              <Table rows={data.parity_tables} caption="Tables compared with the golden reference" />
            </details>
            <details className="border-b border-rule py-3">
              <summary className="min-h-11 cursor-pointer py-2 font-medium">Tolerance policy</summary>
              <Markdown className="max-w-prose text-sm">{data.policy}</Markdown>
              <p className="text-sm">Evidence: {link("tolerance.json")}</p>
            </details>
            <p className="mt-3 max-w-prose text-sm text-muted-ink">
              Parity shows that two independent implementations of the same written rules agree; it does
              not show that the rules themselves are the best possible definition.
            </p>
          </>
        ) : (
          <p>Not yet measured.</p>
        )}
      </Section>

      <Section number="04" title="Automated tests" question="Are the code paths exercised automatically?">
        {data.tests.available ? (
          <dl className="grid gap-6 sm:grid-cols-2">
            <div className="border-t-2 border-ink pt-2">
              <dt className="text-xs font-medium uppercase tracking-wider text-muted-ink">Tests passed</dt>
              <dd className="num mt-1 text-4xl" data-testid="tests-passed">
                {count(data.tests.passed)} / {count(data.tests.total)}
              </dd>
              <dd className="mt-1 text-sm">
                {count(data.tests.failed)} failed, {count(data.tests.skipped)} skipped · evidence: {link(data.tests.file)}
              </dd>
            </div>
          </dl>
        ) : (
          <p>Not yet measured (no {data.tests.file}).</p>
        )}
      </Section>

      <Section number="05" title="Files of this snapshot" question="Which files does this site serve, and can they be verified?">
        <div className="overflow-x-auto border-y border-rule" tabIndex={0} role="region" aria-label="Snapshot files">
          <table className="w-full text-sm">
            <caption className="sr-only">Snapshot tables and evidence files with their SHA-256</caption>
            <thead className="bg-panel">
              <tr>
                <th scope="col" className="px-3 py-2 text-left text-xs uppercase tracking-wider text-muted-ink">File</th>
                <th scope="col" className="px-3 py-2 text-right text-xs uppercase tracking-wider text-muted-ink">Rows</th>
                <th scope="col" className="px-3 py-2 text-left text-xs uppercase tracking-wider text-muted-ink">Compared with golden</th>
                <th scope="col" className="px-3 py-2 text-left text-xs uppercase tracking-wider text-muted-ink">SHA-256</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(meta.snapshot.tables).map(([name, t]) => (
                <tr key={name} className="border-t border-rule/60">
                  <th scope="row" className="num px-3 py-1.5 text-left font-medium">{name}.parquet</th>
                  <td className="num px-3 py-1.5 text-right">{count(t.rows)}</td>
                  <td className="px-3 py-1.5">{t.validated ? "Yes" : "Reference data (no golden counterpart)"}</td>
                  <td className="num whitespace-normal break-all px-3 py-1.5 text-xs text-muted-ink">{t.sha256}</td>
                </tr>
              ))}
              {Object.entries(evidence).map(([name, sha]) => (
                <tr key={name} className="border-t border-rule/60">
                  <th scope="row" className="px-3 py-1.5 text-left font-medium">{link(name)}</th>
                  <td className="px-3 py-1.5" />
                  <td className="px-3 py-1.5">Evidence file</td>
                  <td className="num whitespace-normal break-all px-3 py-1.5 text-xs text-muted-ink">{sha}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
      <div className="mt-8">
        <ProvenanceLine source={source} />
      </div>
    </>
  );
}
