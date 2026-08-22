import { useState } from "react";
import Playground from "./components/Playground";
import Ledger from "./components/Ledger";
import RedTeam from "./components/RedTeam";

type Tab = "playground" | "ledger" | "redteam";

const TABS: { key: Tab; label: string }[] = [
  { key: "playground", label: "Playground" },
  { key: "ledger", label: "Ledger" },
  { key: "redteam", label: "Red Team" },
];

export default function App(): JSX.Element {
  const [tab, setTab] = useState<Tab>("playground");

  return (
    <div className="min-h-screen bg-ink text-paper">
      <header className="border-b border-line bg-surface px-6 py-4">
        <div className="mx-auto flex max-w-6xl items-center justify-between">
          <h1 className="font-heading text-lg font-semibold tracking-wide">
            PRAMAN <span className="text-muted">▪ proof for agent payments</span>
          </h1>
          <nav className="flex gap-1">
            {TABS.map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={`rounded px-3 py-1.5 font-heading text-sm font-medium transition-colors ${
                  tab === t.key ? "bg-raised text-paper" : "text-muted hover:text-paper"
                }`}
              >
                {t.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-6xl p-6">
        {tab === "playground" && <Playground />}
        {tab === "ledger" && <Ledger />}
        {tab === "redteam" && <RedTeam />}
      </main>
    </div>
  );
}
