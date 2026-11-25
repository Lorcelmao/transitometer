import Link from "next/link";

export default function NotFound() {
  return (
    <section className="mx-auto max-w-lg rounded-xl border border-rule bg-surface p-8 text-center shadow-xs">
      <p className="text-xs font-semibold text-muted-ink">Error 404</p>
      <h1 className="mt-2 text-2xl font-bold tracking-tight text-ink">This page does not exist.</h1>
      <p className="mt-4 text-sm text-muted-ink">
        <Link href="/" prefetch={false} className="font-semibold">
          Back to the overview
        </Link>
      </p>
    </section>
  );
}
