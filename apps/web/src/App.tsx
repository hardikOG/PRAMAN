/**
 * Phase 0 placeholder. The real console — Playground, Ledger, Proof
 * inspector, Red Team (PRAMAN_BUILD.md §7, wireframes A-D) — lands in
 * Phase 7. This exists so the `web` container has something to build and
 * serve, and so the compose healthcheck has a real page to fetch.
 */
export default function App(): JSX.Element {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-2 font-heading">
      <h1 className="text-2xl tracking-wide">PRAMAN</h1>
      <p className="font-body text-sm text-muted">
        Console scaffolded — screens land in Phase 7.
      </p>
    </main>
  );
}
