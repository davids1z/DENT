import json
import logging
import time

import httpx
from pydantic import BaseModel

from .prompts import build_evidence_prompt, build_system_prompt
from .weather import WeatherVerification, verify_weather

logger = logging.getLogger(__name__)


class AgentReasoningStep(BaseModel):
    step: int
    category: str
    observation: str
    assessment: str
    impact: str


class AgentDecision(BaseModel):
    outcome: str = "HumanReview"
    confidence: float = 0.0
    reasoning_steps: list[AgentReasoningStep] = []
    weather_assessment: str | None = None
    fraud_indicators: list[str] = []
    recommended_actions: list[str] = []
    summary_hr: str = ""
    stp_eligible: bool = False
    stp_blockers: list[str] = []
    model_used: str = ""
    processing_time_ms: int = 0
    weather_verification: WeatherVerification | None = None
    fallback_used: bool = False
    error: str | None = None


class AgentEvaluateRequest(BaseModel):
    damages: list[dict] = []
    forensic_modules: list[dict] = []
    overall_forensic_risk_score: float = 0.0
    overall_forensic_risk_level: str = "Low"
    cost_min: float = 0.0
    cost_max: float = 0.0
    gross_total: float | None = None
    vehicle_make: str | None = None
    vehicle_model: str | None = None
    vehicle_year: int | None = None
    vehicle_color: str | None = None
    structural_integrity: str | None = None
    urgency_level: str | None = None
    is_driveable: bool | None = None
    latitude: float | None = None
    longitude: float | None = None
    capture_timestamp: str | None = None
    capture_source: str | None = None
    damage_causes: list[str] = []


class AgentOrchestrator:
    def __init__(
        self,
        openrouter_api_key: str,
        model: str,
        agent_model: str | None = None,
        stp_cost_threshold: float = 500.0,
        escalation_cost_threshold: float = 3000.0,
        stp_max_forensic_risk: float = 0.25,
        escalation_forensic_risk: float = 0.75,
    ):
        self._api_key = openrouter_api_key
        self._model = agent_model or model
        self._stp_cost_threshold = stp_cost_threshold
        self._escalation_cost_threshold = escalation_cost_threshold
        self._stp_max_forensic_risk = stp_max_forensic_risk
        self._escalation_forensic_risk = escalation_forensic_risk

    async def evaluate(self, request: AgentEvaluateRequest) -> AgentDecision:
        t0 = time.perf_counter()

        # Step 1: Weather verification
        weather = await verify_weather(
            request.latitude,
            request.longitude,
            request.capture_timestamp,
            request.damage_causes,
        )

        # Step 2: Build prompts
        system_prompt = build_system_prompt(
            stp_cost_threshold=self._stp_cost_threshold,
            escalation_cost_threshold=self._escalation_cost_threshold,
            stp_max_forensic_risk=self._stp_max_forensic_risk,
            escalation_forensic_risk=self._escalation_forensic_risk,
        )

        evidence_prompt = build_evidence_prompt(
            damages=request.damages,
            forensic_modules=request.forensic_modules,
            overall_forensic_risk=request.overall_forensic_risk_score,
            overall_forensic_level=request.overall_forensic_risk_level,
            weather=weather.model_dump() if weather.queried else None,
            cost_min=request.cost_min,
            cost_max=request.cost_max,
            gross_total=request.gross_total,
            vehicle_info={
                "make": request.vehicle_make,
                "model": request.vehicle_model,
                "year": request.vehicle_year,
                "color": request.vehicle_color,
            },
            capture_metadata={
                "source": request.capture_source,
                "latitude": request.latitude,
                "longitude": request.longitude,
            },
        )

        # Step 3: Call LLM
        decision = await self._call_llm(system_prompt, evidence_prompt)

        # Step 4: Attach metadata
        decision.weather_verification = weather
        if weather.queried and not weather.error:
            if weather.corroborates_claim is False:
                decision.weather_assessment = weather.discrepancy_note
            elif weather.corroborates_claim is True:
                decision.weather_assessment = (
                    f"Vremenski uvjeti na lokaciji potkrjepljuju tvrdnju. "
                    f"Zabilježeno: {weather.weather_description}, "
                    f"padaline: {weather.precipitation_mm} mm."
                )

        decision.processing_time_ms = int((time.perf_counter() - t0) * 1000)
        decision.model_used = self._model

        return decision

    async def _call_llm(
        self, system_prompt: str, evidence_prompt: str
    ) -> AgentDecision:
        if not self._api_key:
            logger.warning("No OpenRouter API key, returning fallback")
            return AgentDecision(
                outcome="HumanReview",
                confidence=0.0,
                summary_hr="OpenRouter API ključ nije konfiguriran. Proslijeđeno na ručni pregled.",
                fallback_used=True,
            )

        for attempt in range(2):
            try:
                extra_instruction = ""
                if attempt == 1:
                    extra_instruction = (
                        "\n\nVAŽNO: Prethodni odgovor nije bio validan JSON. "
                        "Odgovori ISKLJUČIVO validnim JSON-om, bez markdown oznaka, "
                        "bez teksta prije ili poslije JSON objekta."
                    )

                async with httpx.AsyncClient(timeout=90.0) as client:
                    response = await client.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Content-Type": "application/json",
                            "HTTP-Referer": "https://dent.xyler.ai",
                            "X-Title": "DENT - Agent Evaluation",
                        },
                        json={
                            "model": self._model,
                            "max_tokens": 4000,
                            "temperature": 0.1,
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {
                                    "role": "user",
                                    "content": evidence_prompt + extra_instruction,
                                },
                            ],
                        },
                    )

                response.raise_for_status()
                result = response.json()
                response_text = result["choices"][0]["message"]["content"]

                # Strip markdown code blocks
                text = response_text.strip()
                if "```json" in text:
                    text = text.split("```json")[1].split("```")[0].strip()
                elif "```" in text:
                    text = text.split("```")[1].split("```")[0].strip()

                parsed = json.loads(text)

                # Validate outcome
                outcome = parsed.get("outcome", "HumanReview")
                if outcome not in ("AutoApprove", "HumanReview", "Escalate"):
                    outcome = "HumanReview"

                # Parse reasoning steps
                steps = []
                for s in parsed.get("reasoning_steps", []):
                    steps.append(
                        AgentReasoningStep(
                            step=s.get("step", 0),
                            category=s.get("category", ""),
                            observation=s.get("observation", ""),
                            assessment=s.get("assessment", ""),
                            impact=s.get("impact", ""),
                        )
                    )

                confidence = float(parsed.get("confidence", 0.5))
                confidence = max(0.0, min(1.0, confidence))

                return AgentDecision(
                    outcome=outcome,
                    confidence=confidence,
                    reasoning_steps=steps,
                    weather_assessment=parsed.get("weather_assessment"),
                    fraud_indicators=parsed.get("fraud_indicators", []),
                    recommended_actions=parsed.get("recommended_actions", []),
                    summary_hr=parsed.get("summary_hr", ""),
                    stp_eligible=parsed.get("stp_eligible", False),
                    stp_blockers=parsed.get("stp_blockers", []),
                )

            except (json.JSONDecodeError, KeyError, IndexError) as e:
                if attempt == 0:
                    logger.warning("Agent LLM JSON parse failed (attempt 1), retrying: %s", e)
                    continue
                logger.warning("Agent LLM JSON parse failed (attempt 2): %s", e)
                return AgentDecision(
                    outcome="HumanReview",
                    confidence=0.0,
                    summary_hr="Agent nije mogao parsirati LLM odgovor. Proslijeđeno na ručni pregled.",
                    fallback_used=True,
                    error=str(e),
                )
            except httpx.HTTPStatusError as e:
                logger.warning("Agent LLM API error: %s - %s", e.response.status_code, e.response.text[:200])
                return AgentDecision(
                    outcome="HumanReview",
                    confidence=0.0,
                    summary_hr="Agent API greška. Proslijeđeno na ručni pregled.",
                    fallback_used=True,
                    error=f"HTTP {e.response.status_code}",
                )
            except Exception as e:
                logger.warning("Agent LLM call failed: %s", e)
                return AgentDecision(
                    outcome="HumanReview",
                    confidence=0.0,
                    summary_hr="Agent poziv nije uspio. Proslijeđeno na ručni pregled.",
                    fallback_used=True,
                    error=str(e),
                )

        # Should not reach here, but safety fallback
        return AgentDecision(
            outcome="HumanReview",
            confidence=0.0,
            summary_hr="Agent nije mogao donijeti odluku.",
            fallback_used=True,
        )
