"""Microsoft Agent Framework workflows for the loan processor."""

from .risk_workflow import (
    RiskWorkflowInput,
    RiskWorkflowResult,
    build_risk_workflow,
    run_risk_workflow,
    stream_risk_workflow,
)

__all__ = [
    "RiskWorkflowInput",
    "RiskWorkflowResult",
    "build_risk_workflow",
    "run_risk_workflow",
    "stream_risk_workflow",
]
