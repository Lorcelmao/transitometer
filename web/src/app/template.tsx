import { PageFlow } from "@/components/site/page-flow";

/**
 * Re-mounted on every navigation (unlike the layout), so each page rises into place with a short
 * transition (.page-enter, off for reduced motion) and ends with links to its neighbours.
 */
export default function Template({ children }: { children: React.ReactNode }) {
  return (
    <div className="page-enter">
      {children}
      <PageFlow />
    </div>
  );
}
