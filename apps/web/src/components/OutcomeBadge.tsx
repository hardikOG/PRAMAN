const STYLES: Record<string, string> = {
  ALLOW: "bg-seal/15 text-seal border-seal/40",
  STEP_UP: "bg-amber/15 text-amber border-amber/40",
  BLOCK: "bg-stamp/15 text-stamp border-stamp/40",
};

const LABELS: Record<string, string> = {
  ALLOW: "ALLOW",
  STEP_UP: "STEP UP",
  BLOCK: "BLOCK",
};

export default function OutcomeBadge({ outcome }: { outcome: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded border px-2 py-0.5 font-heading text-xs font-semibold tracking-wide ${STYLES[outcome] ?? "border-line text-muted"}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {LABELS[outcome] ?? outcome}
    </span>
  );
}
