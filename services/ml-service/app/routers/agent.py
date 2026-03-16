import logging

from fastapi import APIRouter

from ..agent.orchestrator import AgentDecision, AgentEvaluateRequest, AgentOrchestrator
from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/agent/evaluate", response_model=AgentDecision)
async def agent_evaluate(request: AgentEvaluateRequest) -> AgentDecision:
    """AI agent evaluation of an insurance claim."""
    if not settings.agent_enabled:
        return AgentDecision(
            outcome="HumanReview",
            confidence=0.0,
            summary_hr="Agent je onemogućen. Proslijeđeno na ručni pregled.",
            fallback_used=True,
        )

    orchestrator = AgentOrchestrator(
        openrouter_api_key=settings.openrouter_api_key,
        model=settings.model,
        agent_model=settings.agent_model or None,
        stp_cost_threshold=settings.agent_stp_cost_threshold,
        escalation_cost_threshold=settings.agent_escalation_cost_threshold,
        stp_max_forensic_risk=settings.agent_stp_max_forensic_risk,
        escalation_forensic_risk=settings.agent_escalation_forensic_risk,
    )

    return await orchestrator.evaluate(request)
