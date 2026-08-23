const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8010";

export interface Preset {
  key: string;
  label: string;
  description: string;
  items: [string, number][];
}

export interface Constraint {
  id: string;
  type: string;
  field: string;
  operator: string;
  value: string;
  is_deterministic: boolean;
  source_span: string;
}

export interface CartItem {
  sku: string;
  name: string;
  description: string;
  unit_price_paise: number;
  qty: number;
  attributes: Record<string, string>;
}

export interface Cart {
  id: string;
  merchant_id: string;
  total_paise: number;
  currency: string;
  items: CartItem[];
}

export interface Finding {
  constraint_id: string;
  verdict: "SATISFIED" | "VIOLATED" | "UNDETERMINED";
  evidence: string;
  confidence: number;
  adjudicator: "RULE" | "LLM";
}

export interface Decision {
  id: string;
  cart_id: string;
  outcome: "ALLOW" | "STEP_UP" | "BLOCK";
  reason_code: string;
  behaviour_score: number;
  behaviour_signals: string[];
  stripped_items: string[];
  stage_latencies_ms: Record<string, number>;
  razorpay_order_id: string | null;
  razorpay_payment_id: string | null;
  created_at?: string;
  cart?: Cart;
  findings: Finding[];
}

export interface ProofBundle {
  id: string;
  decision_id: string;
  prev_hash: string;
  payload_hash: string;
  signature: string;
  signed_at: string;
  payload: unknown;
}

export interface PlaygroundRunResponse {
  mandate_id: string;
  intent_text: string;
  constraints: Constraint[];
  cart: Cart;
  decision: Decision;
  proof_bundle: ProofBundle | null;
  step_up_token: string | null;
  llm_mode: "live" | "offline_demo";
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    const body = await response.text();
    throw new ApiError(response.status, body || `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export interface StepUpConfirmResponse {
  decision: Decision;
  proof_bundle: ProofBundle;
}

export interface AttackClassResult {
  attack_class: string;
  n: number;
  caught: number;
  missed: number;
  caught_by: string;
}

export interface AblationRow {
  configuration: string;
  catch_rate: number;
  false_block_rate: number;
  p95_latency_seconds: number;
}

export interface EvalResults {
  total_scenarios: number;
  honest_count: number;
  attack_count: number;
  catch_rate: number;
  false_block_rate: number;
  step_up_rate: number;
  p95_latency_seconds: number;
  attack_results: AttackClassResult[];
  ablation: AblationRow[];
}

export const api = {
  listPresets: () => json<Preset[]>("/playground/presets"),
  runPreset: (preset: string) =>
    json<PlaygroundRunResponse>("/playground/run", {
      method: "POST",
      body: JSON.stringify({ preset }),
    }),
  listDecisions: (limit = 50) => json<Decision[]>(`/decisions?limit=${limit}`),
  getDecision: (id: string) => json<Decision>(`/decisions/${id}`),
  getProof: (id: string) => json<ProofBundle>(`/decisions/${id}/proof`),
  getEvalResults: () => json<EvalResults>("/eval/results"),
  confirmStepUp: (token: string) =>
    json<StepUpConfirmResponse>("/decisions/step-up/confirm", {
      method: "POST",
      body: JSON.stringify({ token }),
    }),
};
