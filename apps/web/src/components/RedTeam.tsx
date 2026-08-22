import { useEffect, useState } from "react";
import { api, type EvalResults } from "../api";

export default function RedTeam() {
  const [results, setResults] = useState<EvalResults | null>(null);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    api
      .getEvalResults()
      .then(setResults)
      .catch(() => setNotFound(true));
  }, []);

  if (notFound) {
    return (
      <div className="rounded border border-line bg-surface p-6 text-center">
        <p className="text-sm text-muted">
          No eval run yet. Run{" "}
          <code className="rounded bg-ink px-1.5 py-0.5 font-mono text-xs text-paper">
            make eval
          </code>{" "}
          to generate the red-team report.
        </p>
      </div>
    );
  }

  if (!results) return <p className="text-sm text-muted">Loading…</p>;

  return (
    <div className="space-y-4">
      <div className="rounded border border-line bg-surface p-4">
        <h2 className="mb-3 font-heading text-sm font-semibold tracking-wide text-paper">
          RED TEAM — {results.total_scenarios} scenarios · {results.honest_count} honest ·{" "}
          {results.attack_count} attack
        </h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="CATCH RATE" value={`${(results.catch_rate * 100).toFixed(1)}%`} />
          <Stat label="FALSE BLOCK" value={`${(results.false_block_rate * 100).toFixed(1)}%`} />
          <Stat label="STEP-UP" value={`${(results.step_up_rate * 100).toFixed(1)}%`} />
          <Stat label="P95" value={`${results.p95_latency_seconds.toFixed(2)}s`} />
        </div>
      </div>

      <div className="overflow-x-auto rounded border border-line bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs text-muted">
              <th className="p-3 font-heading font-semibold">ATTACK CLASS</th>
              <th className="p-3 font-heading font-semibold">N</th>
              <th className="p-3 font-heading font-semibold">CAUGHT</th>
              <th className="p-3 font-heading font-semibold">MISSED</th>
              <th className="p-3 font-heading font-semibold">CAUGHT BY</th>
            </tr>
          </thead>
          <tbody>
            {results.attack_results.map((r) => (
              <tr key={r.attack_class} className="border-b border-line last:border-0">
                <td className="p-3 text-paper">{r.attack_class}</td>
                <td className="p-3 font-mono text-xs text-muted">{r.n}</td>
                <td className="p-3 font-mono text-xs text-seal">{r.caught}</td>
                <td className="p-3 font-mono text-xs text-stamp">{r.missed}</td>
                <td className="p-3 text-xs text-muted">{r.caught_by}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="overflow-x-auto rounded border border-line bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs text-muted">
              <th className="p-3 font-heading font-semibold">ABLATION</th>
              <th className="p-3 font-heading font-semibold">CATCH</th>
              <th className="p-3 font-heading font-semibold">FALSE BLOCK</th>
              <th className="p-3 font-heading font-semibold">P95</th>
            </tr>
          </thead>
          <tbody>
            {results.ablation.map((row) => (
              <tr key={row.configuration} className="border-b border-line last:border-0">
                <td className="p-3 text-paper">{row.configuration}</td>
                <td className="p-3 font-mono text-xs text-muted">
                  {(row.catch_rate * 100).toFixed(1)}%
                </td>
                <td className="p-3 font-mono text-xs text-muted">
                  {(row.false_block_rate * 100).toFixed(1)}%
                </td>
                <td className="p-3 font-mono text-xs text-muted">
                  {row.p95_latency_seconds.toFixed(2)}s
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-line bg-ink p-3">
      <div className="font-heading text-xs font-semibold tracking-wide text-muted">{label}</div>
      <div className="mt-1 font-heading text-xl font-semibold text-paper">{value}</div>
    </div>
  );
}
