import Link from "next/link";

export default function NotFound() {
  return (
    <section className="py-24">
      <p className="text-xs font-medium uppercase tracking-widest text-accent-red">404</p>
      <h1 className="mt-2 font-display text-4xl">This page does not exist.</h1>
      <p className="mt-4">
        <Link href="/">Back to the overview</Link>
      </p>
    </section>
  );
}
