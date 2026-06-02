import { useState, useRef } from "react";

type StageKey = "intake" | "websearch" | "risk";
type StageStatus = "idle" | "running" | "done" | "error";

interface Stage {
  status: StageStatus;
  payload?: unknown;
}

const initialStages: Record<StageKey, Stage> = {
  intake: { status: "idle" },
  websearch: { status: "idle" },
  risk: { status: "idle" },
};

const STAGE_LABELS: Record<StageKey, string> = {
  intake: "Extracted Loan Data",
  websearch: "Market Context (Web Search)",
  risk: "Risk Assessment",
};

const API_BASE = (import.meta.env.VITE_WORKFLOW_API_URL as string) || "/api";

function formatPayload(payload: unknown): string {
  if (payload == null) return "(waiting…)";
  if (typeof payload === "string") return payload;
  if (typeof payload === "object" && payload !== null && "text" in (payload as object)) {
    return String((payload as { text: unknown }).text);
  }
  return JSON.stringify(payload, null, 2);
}

export default function App() {
  const [docUrl, setDocUrl] = useState("");
  const [docText, setDocText] = useState("");
  const [stages, setStages] = useState<Record<StageKey, Stage>>(initialStages);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const updateStage = (key: StageKey, patch: Partial<Stage>) =>
    setStages((s) => ({ ...s, [key]: { ...s[key], ...patch } }));

  const handleRun = async () => {
    if (!docUrl && !docText) {
      setError("Provide a document URL or paste document text.");
      return;
    }
    setError(null);
    setStages({
      intake: { status: "running" },
      websearch: { status: "running" },
      risk: { status: "idle" },
    });
    setRunning(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch(`${API_BASE}/workflows/risk/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({
          document_url: docUrl || null,
          document_text: docText || null,
        }),
        signal: controller.signal,
      });

      if (!res.ok || !res.body) {
        throw new Error(`Server error: ${res.status} ${res.statusText}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let sep;
        while ((sep = buffer.indexOf("\n\n")) !== -1) {
          const block = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          handleSseBlock(block);
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setError((err as Error).message);
      }
    } finally {
      setRunning(false);
      abortRef.current = null;
    }
  };

  const handleSseBlock = (block: string) => {
    let event = "message";
    let data = "";
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data += line.slice(5).trim();
    }
    if (!data) return;
    let parsed: any;
    try {
      parsed = JSON.parse(data);
    } catch {
      return;
    }
    const stage = parsed.stage as string;
    const status = parsed.status as string;

    if (stage === "intake" || stage === "websearch" || stage === "risk") {
      if (status === "running" && parsed.payload?.text) {
        // Incremental delta — append to buffered text.
        const delta = String(parsed.payload.text);
        setStages((s) => {
          const prev = s[stage as StageKey];
          const prevText =
            prev.payload && typeof prev.payload === "object" && "text" in (prev.payload as object)
              ? String((prev.payload as { text: unknown }).text ?? "")
              : "";
          return {
            ...s,
            [stage]: { status: "running", payload: { text: prevText + delta } },
          };
        });
      } else if (status === "completed") {
        updateStage(stage as StageKey, {
          status: "done",
          payload: parsed.payload,
        });
      } else if (status === "started") {
        updateStage(stage as StageKey, { status: "running", payload: { text: "" } });
      }
    } else if (stage === "final" && parsed.payload) {
      const p = parsed.payload as {
        extracted_loan_data: string;
        web_search_results: string;
        risk_assessment: string;
      };
      setStages({
        intake: { status: "done", payload: { text: p.extracted_loan_data } },
        websearch: { status: "done", payload: { text: p.web_search_results } },
        risk: { status: "done", payload: { text: p.risk_assessment } },
      });
    } else if (event === "workflow" && status === "error") {
      setError(parsed.payload?.message ?? "Workflow error");
    }
  };

  return (
    <div className="app">
      <h1>MAF Risk Assessment Workflow</h1>
      <p className="subtitle">
        Code-first Microsoft Agent Framework workflow orchestrating
        loan-processing-json, web-search-agent, and risk-assessment-agent-aisearch-tool.
      </p>

      {error && <div className="error-banner">{error}</div>}

      <div className="input-card">
        <label htmlFor="doc-url">Document URL (SAS or public)</label>
        <input
          id="doc-url"
          type="text"
          value={docUrl}
          onChange={(e) => setDocUrl(e.target.value)}
          placeholder="https://…/sample-loan-application.pdf?sv=…"
          disabled={running}
        />
        <div style={{ height: 12 }} />
        <label htmlFor="doc-text">…or paste document text</label>
        <textarea
          id="doc-text"
          value={docText}
          onChange={(e) => setDocText(e.target.value)}
          placeholder="Loan application markdown / text…"
          disabled={running}
        />
        <div style={{ height: 12 }} />
        <div className="row">
          <button onClick={handleRun} disabled={running}>
            {running ? "Running…" : "Run Workflow"}
          </button>
          {running && (
            <button
              style={{ background: "#6b7280" }}
              onClick={() => abortRef.current?.abort()}
            >
              Cancel
            </button>
          )}
        </div>
      </div>

      <div className="panels">
        {(Object.keys(STAGE_LABELS) as StageKey[]).map((key) => (
          <div key={key} className="panel">
            <h3>
              {STAGE_LABELS[key]}
              <span className={`status ${stages[key].status}`}>
                {stages[key].status}
              </span>
            </h3>
            <pre>{formatPayload(stages[key].payload)}</pre>
          </div>
        ))}
      </div>
    </div>
  );
}
