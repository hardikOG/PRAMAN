import { useEffect, useState } from "react";
import {
  ApiError,
  api,
  type StepUpAction,
  type StepUpConfirmResponse,
  type StepUpContext,
} from "../api";
import { formatPaise, truncateHash } from "../format";

type Phase =
  | { kind: "loading" }
  | { kind: "gone" }
  | { kind: "error"; message: string }
  | { kind: "ready"; context: StepUpContext }
  | { kind: "submitting"; context: StepUpContext; action: StepUpAction }
  | { kind: "done"; context: StepUpContext; action: StepUpAction; result: StepUpConfirmResponse };

function readableError(error: unknown): string {
  if (error instanceof ApiError) {
    try {
      const parsed = JSON.parse(error.message) as { detail?: string };
      if (parsed.detail) return parsed.detail;
    } catch {
      /* not JSON — fall through to the raw message */
    }
  }
  return error instanceof Error ? error.message : String(error);
}

/**
 * The shopper's confirmation screen — the one place PRAMAN asks a person (not
 * an engineer) to decide something. Mobile-first, plain language, three
 * clearly-labelled choices, and nothing is charged until one is taken.
 * Opened from a single-use link (`/?confirm=<token>`).
 */
export default function ShopperConfirm({ token }: { token: string }) {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [secondsLeft, setSecondsLeft] = useState(0);

  useEffect(() => {
    api
      .getStepUpContext(token)
      .then((context) => {
        setSecondsLeft(context.expires_in_seconds);
        setPhase({ kind: "ready", context });
      })
      .catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 404) setPhase({ kind: "gone" });
        else setPhase({ kind: "error", message: readableError(e) });
      });
  }, [token]);

  useEffect(() => {
    if (phase.kind !== "ready") return;
    const timer = setInterval(() => setSecondsLeft((s) => Math.max(s - 1, 0)), 1000);
    return () => clearInterval(timer);
  }, [phase.kind]);

  async function choose(context: StepUpContext, action: StepUpAction) {
    setPhase({ kind: "submitting", context, action });
    try {
      const result = await api.confirmStepUp(token, action);
      setPhase({ kind: "done", context, action, result });
      if (window.parent !== window) {
        window.parent.postMessage(
          { type: "praman:step-up-result", action, result },
          window.location.origin,
        );
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setPhase({ kind: "gone" });
      else setPhase({ kind: "error", message: readableError(e) });
    }
  }

  return (
    <div className="min-h-screen bg-day font-body text-daytext">
      <div className="mx-auto flex min-h-screen max-w-md flex-col">
        <header className="flex items-center justify-between px-5 pb-3 pt-5">
          <span className="font-heading text-base font-semibold">Kicks &amp; Co</span>
          <span className="text-xs text-daymuted">Checked by PRAMAN</span>
        </header>

        <main className="flex-1 px-5 pb-6" aria-live="polite">
          {phase.kind === "loading" && <p className="py-16 text-center text-daymuted">Opening your purchase…</p>}

          {phase.kind === "gone" && (
            <Message
              title="This link is no longer active"
              body="It has expired or was already used. If you still want this purchase, ask your agent to try again."
            />
          )}

          {phase.kind === "error" && (
            <Message title="Something went wrong" body={phase.message} tone="error" />
          )}

          {(phase.kind === "ready" || phase.kind === "submitting") && (
            <Review
              context={phase.context}
              secondsLeft={secondsLeft}
              busyAction={phase.kind === "submitting" ? phase.action : null}
              onChoose={(action) => choose(phase.context, action)}
            />
          )}

          {phase.kind === "done" && <Receipt phase={phase} />}
        </main>
      </div>
    </div>
  );
}

function Review({
  context,
  secondsLeft,
  busyAction,
  onChoose,
}: {
  context: StepUpContext;
  secondsLeft: number;
  busyAction: StepUpAction | null;
  onChoose: (action: StepUpAction) => void;
}) {
  const busy = busyAction !== null;
  const withoutAddon = context.total_paise - context.unrequested_paise;
  const expired = secondsLeft === 0;

  return (
    <div className="space-y-5">
      <section className="rounded-lg border-l-4 border-dayamberline bg-dayamber p-4">
        <h1 className="font-heading text-xl font-semibold leading-snug">{context.headline}</h1>
        <p className="mt-2 text-[15px] leading-relaxed text-daymuted">{context.detail}</p>
      </section>

      <section aria-label="What's in the cart">
        <h2 className="mb-2 font-heading text-xs font-semibold tracking-wide text-daymuted">
          IN THE CART
        </h2>
        <ul className="divide-y divide-dayline overflow-hidden rounded-lg border border-dayline bg-daycard">
          {context.items.map((item) => (
            <li
              key={item.sku}
              className={`flex items-start justify-between gap-3 p-3.5 ${
                item.unrequested ? "bg-dayamber" : ""
              }`}
            >
              <div>
                <div className="font-medium">
                  {item.name}
                  {item.qty > 1 ? ` × ${item.qty}` : ""}
                </div>
                <div
                  className={`mt-0.5 text-xs ${item.unrequested ? "font-semibold text-[#9A5B00]" : "text-daymuted"}`}
                >
                  {item.unrequested ? "Not something you asked for" : "Matches what you asked for"}
                </div>
              </div>
              <div className="shrink-0 font-heading font-semibold">{formatPaise(item.line_total_paise)}</div>
            </li>
          ))}
        </ul>
      </section>

      <p className="text-center text-xs text-daymuted">
        Nothing is charged until you choose.{" "}
        {expired ? "This link has expired." : `This link expires in ${Math.max(Math.ceil(secondsLeft / 60), 1)} min.`}
      </p>

      <div className="sticky bottom-0 -mx-5 space-y-2.5 border-t border-dayline bg-day/95 px-5 pb-5 pt-3 backdrop-blur">
        {context.can_remove ? (
          <>
            <ActionButton
              variant="primary"
              disabled={busy || expired}
              busy={busyAction === "remove_unrequested"}
              onClick={() => onChoose("remove_unrequested")}
            >
              Remove it &amp; pay {formatPaise(withoutAddon)}
            </ActionButton>
            <ActionButton
              variant="secondary"
              disabled={busy || expired}
              busy={busyAction === "pay_all"}
              onClick={() => onChoose("pay_all")}
            >
              Keep it &amp; pay {formatPaise(context.total_paise)}
            </ActionButton>
          </>
        ) : (
          <ActionButton
            variant="primary"
            disabled={busy || expired}
            busy={busyAction === "pay_all"}
            onClick={() => onChoose("pay_all")}
          >
            Yes, pay {formatPaise(context.total_paise)}
          </ActionButton>
        )}
        <button
          onClick={() => onChoose("cancel")}
          disabled={busy}
          className="min-h-12 w-full rounded-lg text-[15px] font-medium text-daymuted underline-offset-4 hover:underline disabled:opacity-50"
        >
          {busyAction === "cancel" ? "Cancelling…" : "Cancel — don't buy anything"}
        </button>
      </div>
    </div>
  );
}

function ActionButton({
  variant,
  disabled,
  busy,
  onClick,
  children,
}: {
  variant: "primary" | "secondary";
  disabled: boolean;
  busy: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  const styles =
    variant === "primary"
      ? "bg-daytext text-white"
      : "border border-daytext bg-daycard text-daytext";
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`min-h-12 w-full rounded-lg px-4 font-heading text-base font-semibold transition-opacity disabled:opacity-50 ${styles}`}
    >
      {busy ? "One moment…" : children}
    </button>
  );
}

function Receipt({ phase }: { phase: Extract<Phase, { kind: "done" }> }) {
  const { action, result, context } = phase;

  if (action === "cancel") {
    return (
      <Message
        title="Cancelled — nothing was charged"
        body="Your agent was told not to buy this. Your decision is saved so there's a record you said no."
      />
    );
  }

  const removed = result.decision.stripped_items.length > 0;
  const paid = removed ? context.total_paise - context.unrequested_paise : context.total_paise;
  return (
    <div className="space-y-4 pt-6 text-center">
      <div
        className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-dayseal text-2xl text-white"
        aria-hidden="true"
      >
        ✓
      </div>
      <h1 className="font-heading text-2xl font-semibold">Paid {formatPaise(paid)}</h1>
      {removed && (
        <p className="text-daymuted">
          We took out the item you didn't ask for, so you weren't charged for it.
        </p>
      )}
      <div className="rounded-lg border border-dayline bg-daycard p-4 text-left text-sm">
        <div className="font-heading text-xs font-semibold tracking-wide text-daymuted">
          RECEIPT
        </div>
        <dl className="mt-2 space-y-1.5">
          <Row label="Reference" value={result.decision.razorpay_order_id ?? "—"} />
          {result.proof_bundle && (
            <Row label="Signed record" value={truncateHash(result.proof_bundle.payload_hash)} />
          )}
        </dl>
        <p className="mt-3 text-xs text-daymuted">
          The signed record is proof of exactly what was checked and what you approved.
        </p>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-daymuted">{label}</dt>
      <dd className="break-all text-right font-mono text-xs">{value}</dd>
    </div>
  );
}

function Message({
  title,
  body,
  tone = "neutral",
}: {
  title: string;
  body: string;
  tone?: "neutral" | "error";
}) {
  return (
    <div className="pt-10 text-center">
      <h1 className={`font-heading text-xl font-semibold ${tone === "error" ? "text-[#B3261E]" : ""}`}>
        {title}
      </h1>
      <p className="mx-auto mt-2 max-w-xs text-[15px] leading-relaxed text-daymuted">{body}</p>
    </div>
  );
}
