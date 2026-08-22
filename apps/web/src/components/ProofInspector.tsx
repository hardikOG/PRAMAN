import { useEffect, useState } from "react";
import { api, type Decision, type ProofBundle } from "../api";
import { formatPaise, truncateHash } from "../format";
import OutcomeBadge from "./OutcomeBadge";

export default function ProofInspector({
  decisionId,
  onClose,
}: {
  decisionId: string;
  onClose: () => void;
}) {
  const [decision, setDecision] = useState<Decision | null>(null);
  const [proof, setProof] = useState<ProofBundle | null>(null);
  const [proofError, setProofError] = useState<string | null>(null);

  useEffect(() => {
    api.getDecision(decisionId).then(setDecision);
    api
      .getProof(decisionId)
      .then(setProof)
      .catch(() => setProofError("no proof bundle for this decision"));
  }, [decisionId]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded border border-line bg-surface p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-heading text-sm font-semibold text-paper">
            {decision ? <OutcomeBadge outcome={decision.outcome} /> : "…"}
          </h2>
          <button onClick={onClose} className="text-muted hover:text-paper">
            ✕
          </button>
        </div>

        {decision && (
          <div className="space-y-4 text-sm">
            <Section title="CART">
              {decision.cart?.items.map((item) => (
                <div key={item.sku} className="flex justify-between border-b border-line py-1.5 last:border-0">
                  <span className="font-mono text-xs text-paper">
                    {item.sku} · {item.name} × {item.qty}
                  </span>
                  <span className="font-mono text-xs text-muted">
                    {formatPaise(item.unit_price_paise * item.qty)}
                  </span>
                </div>
              ))}
              {decision.stripped_items.length > 0 && (
                <p className="mt-2 text-xs text-amber">
                  stripped: {decision.stripped_items.join(", ")}
                </p>
              )}
            </Section>

            <Section title="FINDINGS">
              {decision.findings.map((f) => (
                <div key={f.constraint_id} className="border-b border-line py-1.5 last:border-0">
                  <div className="flex justify-between font-mono text-xs">
                    <span
                      className={
                        f.verdict === "SATISFIED"
                          ? "text-seal"
                          : f.verdict === "VIOLATED"
                            ? "text-stamp"
                            : "text-amber"
                      }
                    >
                      {f.verdict}
                    </span>
                    <span className="text-muted">{f.adjudicator}</span>
                  </div>
                  <p className="mt-0.5 text-xs text-muted">{f.evidence}</p>
                </div>
              ))}
            </Section>

            <Section title="BEHAVIOUR">
              <p className="text-xs text-muted">
                risk {decision.behaviour_score.toFixed(2)} · signals:{" "}
                {decision.behaviour_signals.length > 0 ? decision.behaviour_signals.join(", ") : "none"}
              </p>
            </Section>

            {decision.razorpay_order_id && (
              <Section title="RAZORPAY">
                <p className="font-mono text-xs text-muted">
                  {decision.razorpay_order_id} · {decision.razorpay_payment_id}
                </p>
              </Section>
            )}

            <Section title="PROOF">
              {proof && (
                <div className="space-y-1 font-mono text-xs text-muted">
                  <div>id {truncateHash(proof.id, 8)}</div>
                  <div>prev {truncateHash(proof.prev_hash)}</div>
                  <div>hash {truncateHash(proof.payload_hash)}</div>
                  <div>sig {truncateHash(proof.signature, 12)}</div>
                  <div className="pt-1 text-seal">✓ chained and signed</div>
                </div>
              )}
              {proofError && <p className="text-xs text-muted">{proofError}</p>}
            </Section>
          </div>
        )}
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="mb-1.5 font-heading text-xs font-semibold tracking-wide text-muted">{title}</h3>
      {children}
    </div>
  );
}
