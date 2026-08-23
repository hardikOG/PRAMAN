import { useEffect, useState } from "react";
import {
  api,
  type Preset,
  type PlaygroundRunResponse,
  type Constraint,
  type Finding,
  type StepUpConfirmResponse,
} from "../api";
import { formatPaise, truncateHash } from "../format";
import OutcomeBadge from "./OutcomeBadge";

const STAGE_LABELS: Record<string, string> = {
  s1: "S1 · MANDATE",
  s2: "S2 · FAITHFULNESS",
  s3: "S3 · BEHAVIOUR",
};

function ConstraintRow({ c, findings }: { c: Constraint; findings: Finding[] }) {
  const finding = findings.find((f) => f.constraint_id === c.id);
  const colour =
    finding?.verdict === "SATISFIED" ? "text-seal" : finding?.verdict === "VIOLATED" ? "text-stamp" : "text-amber";
  return (
    <div className="flex items-start justify-between gap-3 border-b border-line py-2 text-sm">
      <div>
        <span className="font-mono text-xs text-muted">{c.type}</span>
        <span className="ml-2 text-paper">{c.source_span}</span>
      </div>
      <div className={`shrink-0 text-right font-mono text-xs ${colour}`}>
        {finding ? finding.verdict : "…"}
      </div>
    </div>
  );
}

export default function Playground() {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [selected, setSelected] = useState<string>("honest");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<PlaygroundRunResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revealCount, setRevealCount] = useState(0);
  const [confirming, setConfirming] = useState(false);
  const [confirmResult, setConfirmResult] = useState<StepUpConfirmResponse | null>(null);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [waking, setWaking] = useState(false);

  useEffect(() => {
    let settled = false;
    // Free-tier hosting (e.g. Render's free web services) spins the API
    // down after 15 minutes idle; the first request wakes it and can take
    // 30-60s. Only show this after a delay, so it never flashes on a local
    // dev server that responds in milliseconds.
    const wakeTimer = setTimeout(() => {
      if (!settled) setWaking(true);
    }, 3000);
    api
      .listPresets()
      .then(setPresets)
      .catch((e) => setError(String(e)))
      .finally(() => {
        settled = true;
        clearTimeout(wakeTimer);
        setWaking(false);
      });
    return () => {
      settled = true;
      clearTimeout(wakeTimer);
    };
  }, []);

  async function run() {
    setRunning(true);
    setError(null);
    setResult(null);
    setRevealCount(0);
    setConfirmResult(null);
    setConfirmError(null);
    try {
      const response = await api.runPreset(selected);
      setResult(response);
      const stageCount = 4;
      for (let i = 1; i <= stageCount; i++) {
        await new Promise((r) => setTimeout(r, 220));
        setRevealCount(i);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(false);
    }
  }

  async function confirmStepUp() {
    if (!result?.step_up_token) return;
    setConfirming(true);
    setConfirmError(null);
    try {
      const response = await api.confirmStepUp(result.step_up_token);
      setConfirmResult(response);
    } catch (e) {
      setConfirmError(e instanceof Error ? e.message : String(e));
    } finally {
      setConfirming(false);
    }
  }

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <div className="space-y-4">
        <div className="rounded border border-line bg-surface p-4">
          <h2 className="mb-3 font-heading text-sm font-semibold tracking-wide text-paper">
            BUYER AGENT
          </h2>
          <p className="mb-3 font-body text-sm text-muted">
            "running shoes under ₹4000, size 9, not white"
          </p>
          {waking && presets.length === 0 && (
            <div className="mb-3 rounded border border-amber/40 bg-ink p-3 text-xs text-amber">
              Connecting to PRAMAN Gateway… backend may take up to a minute
              to wake on free-tier infrastructure.
            </div>
          )}
          <div className="space-y-2">
            {presets.map((p) => (
              <button
                key={p.key}
                onClick={() => setSelected(p.key)}
                className={`w-full rounded border px-3 py-2 text-left text-sm transition-colors ${
                  selected === p.key
                    ? "border-chain bg-raised text-paper"
                    : "border-line bg-ink text-muted hover:bg-raised"
                }`}
              >
                <div className="font-medium">{p.label}</div>
                <div className="text-xs text-muted">{p.description}</div>
              </button>
            ))}
          </div>
          <button
            onClick={run}
            disabled={running}
            className="mt-4 w-full rounded bg-chain px-4 py-2 font-heading text-sm font-semibold text-ink disabled:opacity-50"
          >
            {running ? "Running…" : "Run scenario"}
          </button>
        </div>

        {result && (
          <div className="rounded border border-line bg-surface p-4">
            <h3 className="mb-2 font-heading text-xs font-semibold tracking-wide text-muted">
              CONSTRAINTS ({result.constraints.length})
            </h3>
            {result.constraints.map((c) => (
              <ConstraintRow key={c.id} c={c} findings={result.decision.findings} />
            ))}
            <div className="mt-3 font-mono text-xs text-muted">
              cart: {result.cart.items.map((i) => i.sku).join(", ")} —{" "}
              {formatPaise(result.cart.total_paise)}
            </div>
          </div>
        )}
      </div>

      <div className="rounded border border-line bg-surface p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-heading text-sm font-semibold tracking-wide text-paper">
            DECISION TRACE
          </h2>
          {result && <span className="text-xs text-muted">● {result.llm_mode}</span>}
        </div>

        {error && <div className="rounded border border-stamp/40 bg-stamp/10 p-3 text-sm text-stamp">{error}</div>}

        {!result && !error && (
          <p className="text-sm text-muted">Run a scenario to see the pipeline trace.</p>
        )}

        {result && (
          <div className="relative space-y-4 border-l-2 border-chain pl-4">
            {(["s1", "s2", "s3"] as const).map((stage, idx) => (
              <div
                key={stage}
                className={`transition-opacity duration-300 motion-reduce:transition-none ${
                  revealCount > idx ? "opacity-100" : "opacity-0"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-heading text-xs font-semibold text-chain">
                    {STAGE_LABELS[stage]}
                  </span>
                  <span className="font-mono text-xs text-muted">
                    {result.decision.stage_latencies_ms[stage]?.toFixed(2)}ms
                  </span>
                </div>
              </div>
            ))}

            <div
              className={`transition-opacity duration-300 motion-reduce:transition-none ${
                revealCount >= 4 ? "opacity-100" : "opacity-0"
              }`}
            >
              <div className="flex items-center justify-between border-t border-line pt-3">
                <span className="font-heading text-xs font-semibold text-chain">S4 · DECISION</span>
                <OutcomeBadge outcome={result.decision.outcome} />
              </div>
              <p className="mt-1 font-mono text-xs text-muted">{result.decision.reason_code}</p>

              {result.decision.stripped_items.length > 0 && (
                <p className="mt-2 text-xs text-amber">
                  ⚠ stripped: {result.decision.stripped_items.join(", ")}
                </p>
              )}

              {result.decision.razorpay_order_id && (
                <p className="mt-2 font-mono text-xs text-muted">
                  {result.decision.razorpay_order_id} · {result.decision.razorpay_payment_id}
                </p>
              )}

              {result.proof_bundle && (
                <div className="mt-3 rounded border border-chain/40 bg-ink p-3">
                  <div className="font-heading text-xs font-semibold text-chain">
                    PROOF {truncateHash(result.proof_bundle.id, 6)}
                  </div>
                  <div className="mt-1 font-mono text-xs text-muted">
                    hash {truncateHash(result.proof_bundle.payload_hash)}
                  </div>
                  <div className="font-mono text-xs text-muted">
                    prev {truncateHash(result.proof_bundle.prev_hash)}
                  </div>
                </div>
              )}

              {result.step_up_token && !confirmResult && (
                <div className="mt-3 rounded border border-amber/40 bg-ink p-3">
                  <div className="font-heading text-xs font-semibold text-amber">STEP-UP TOKEN</div>
                  <div className="mt-1 font-mono text-xs text-muted">{result.step_up_token}</div>
                  <p className="mt-2 text-xs text-muted">
                    A human confirms this exact cart before payment executes — the original
                    decision above never changes; confirming creates a new one.
                  </p>
                  <button
                    onClick={confirmStepUp}
                    disabled={confirming}
                    className="mt-2 w-full rounded bg-amber px-3 py-1.5 font-heading text-xs font-semibold text-ink disabled:opacity-50"
                  >
                    {confirming ? "Confirming…" : "Confirm as human"}
                  </button>
                  {confirmError && (
                    <p className="mt-2 text-xs text-stamp">{confirmError}</p>
                  )}
                </div>
              )}

              {confirmResult && (
                <div className="mt-3 rounded border border-seal/40 bg-ink p-3">
                  <div className="flex items-center justify-between">
                    <span className="font-heading text-xs font-semibold text-seal">
                      HUMAN-CONFIRMED
                    </span>
                    <OutcomeBadge outcome={confirmResult.decision.outcome} />
                  </div>
                  <p className="mt-1 font-mono text-xs text-muted">
                    {confirmResult.decision.reason_code}
                  </p>
                  <p className="mt-2 font-mono text-xs text-muted">
                    {confirmResult.decision.razorpay_order_id} ·{" "}
                    {confirmResult.decision.razorpay_payment_id}
                  </p>
                  <div className="mt-3 rounded border border-chain/40 bg-surface p-3">
                    <div className="font-heading text-xs font-semibold text-chain">
                      PROOF {truncateHash(confirmResult.proof_bundle.id, 6)}
                    </div>
                    <div className="mt-1 font-mono text-xs text-muted">
                      hash {truncateHash(confirmResult.proof_bundle.payload_hash)}
                    </div>
                    <div className="font-mono text-xs text-muted">
                      prev {truncateHash(confirmResult.proof_bundle.prev_hash)}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
