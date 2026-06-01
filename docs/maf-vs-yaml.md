# MAF Workflow vs YAML Workflow

The repository now hosts two functionally equivalent risk-assessment
workflows. Both call the **same three Foundry agents** —
`loan-processing-json`, `web-search-agent`, and
`risk-assessment-agent-aisearch-tool`. Only the orchestration layer differs.

| Aspect                        | YAML (`websearch-loan-workflow.yaml`)            | MAF (`risk_workflow.py`)                                  |
| ----------------------------- | ------------------------------------------------- | --------------------------------------------------------- |
| Authoring model               | Declarative YAML, hosted in Foundry               | Code-first Python, `WorkflowBuilder`                      |
| Execution                     | Sequential (intake → websearch → risk)            | **Parallel** fan-out (intake + websearch) → risk          |
| Typed I/O                     | None (free-form messages)                         | Pydantic `RiskWorkflowInput` / `RiskWorkflowResult`       |
| Streaming                     | Conversation messages only                        | Stage-level events via `run_stream()`, exposed as SSE      |
| Local execution               | Requires Foundry runtime                          | Runs locally with `DefaultAzureCredential`                 |
| Error handling                | Engine-defined, opaque                            | Standard Python exceptions, structured                    |
| Observability                 | Foundry tracing                                   | OpenTelemetry → Foundry / App Insights (same UI)          |
| Frontends                     | Copilot Studio / Foundry playground               | Copilot Studio (via hosted wrapper) **and** React UI      |
| Source of truth               | `src/workflows/websearch-loan-workflow.yaml`     | `src/loan_processor/workflows/risk_workflow.py`           |
| Foundry name                  | `web-search-risk-assessment-workflow`             | `maf-risk-assessment-workflow`                            |

## When to choose which

* **YAML** — fastest path to a Foundry-listed workflow with no infra to
  host. Good for purely declarative orchestration.
* **MAF** — needed once you require parallelism, typed contracts, custom
  Python logic between agent calls (e.g. policy checks, retries, branching),
  local debugging, or a custom UI.

Both stay deployed side-by-side; the MAF version registers a thin proxy
workflow YAML so it appears in the Foundry Workflows tab next to the
original.
