import { useEffect, useState } from "react";
import { api, type Decision } from "../api";
import { formatPaise } from "../format";
import OutcomeBadge from "./OutcomeBadge";
import ProofInspector from "./ProofInspector";

export default function Ledger() {
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      setDecisions(await api.listDecisions());
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 4000);
    return () => clearInterval(interval);
  }, []);

  const allowed = decisions.filter((d) => d.outcome === "ALLOW").length;
  const steppedUp = decisions.filter((d) => d.outcome === "STEP_UP").length;
  const blocked = decisions.filter((d) => d.outcome === "BLOCK").length;
  const gmv = decisions
    .filter((d) => d.outcome === "ALLOW" && d.cart)
    .reduce((sum, d) => sum + (d.cart?.total_paise ?? 0), 0);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatTile label="ALLOWED" value={allowed} colour="text-seal" />
        <StatTile label="STEPPED UP" value={steppedUp} colour="text-amber" />
        <StatTile label="BLOCKED" value={blocked} colour="text-stamp" />
        <StatTile label="GMV CLEARED" value={formatPaise(gmv)} colour="text-paper" />
      </div>

      {error && <div className="rounded border border-stamp/40 bg-stamp/10 p-3 text-sm text-stamp">{error}</div>}

      <div className="overflow-x-auto rounded border border-line bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs text-muted">
              <th className="p-3 font-heading font-semibold">TIME</th>
              <th className="p-3 font-heading font-semibold">CART</th>
              <th className="p-3 font-heading font-semibold">AMOUNT</th>
              <th className="p-3 font-heading font-semibold">WHY</th>
              <th className="p-3 font-heading font-semibold">OUTCOME</th>
            </tr>
          </thead>
          <tbody>
            {decisions.map((d) => (
              <tr
                key={d.id}
                onClick={() => setSelectedId(d.id)}
                className="cursor-pointer border-b border-line last:border-0 hover:bg-raised"
              >
                <td className="p-3 font-mono text-xs text-muted">
                  {d.created_at ? new Date(d.created_at).toLocaleTimeString() : "—"}
                </td>
                <td className="p-3 font-mono text-xs text-paper">
                  {d.cart?.items.map((i) => i.sku).join(", ") ?? d.cart_id}
                </td>
                <td className="p-3 font-mono text-xs text-paper">
                  {d.cart ? formatPaise(d.cart.total_paise) : "—"}
                </td>
                <td className="p-3 text-xs text-muted">{d.reason_code}</td>
                <td className="p-3">
                  <OutcomeBadge outcome={d.outcome} />
                </td>
              </tr>
            ))}
            {decisions.length === 0 && (
              <tr>
                <td colSpan={5} className="p-6 text-center text-sm text-muted">
                  No decisions yet — run a scenario in the Playground.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {selectedId && <ProofInspector decisionId={selectedId} onClose={() => setSelectedId(null)} />}
    </div>
  );
}

function StatTile({ label, value, colour }: { label: string; value: string | number; colour: string }) {
  return (
    <div className="rounded border border-line bg-surface p-3">
      <div className="font-heading text-xs font-semibold tracking-wide text-muted">{label}</div>
      <div className={`mt-1 font-heading text-xl font-semibold ${colour}`}>{value}</div>
    </div>
  );
}
