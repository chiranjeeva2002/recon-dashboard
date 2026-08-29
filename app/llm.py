import json
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from app.config import settings

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured on the server.")
        _client = OpenAI(api_key=settings.openai_api_key)
    return _client


class ExplanationResult(BaseModel):
    headline: str
    likely_cause: str
    recommended_action: str
    confidence: Literal["low", "medium", "high"]


SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "One sentence summary of the issue in plain language."},
        "likely_cause": {"type": "string", "description": "What most likely happened, in 1-3 sentences."},
        "recommended_action": {
            "type": "string",
            "description": "What a revenue/ops person should concretely do next.",
        },
        "confidence": {
            "type": "string",
            "enum": ["low", "medium", "high"],
            "description": "Confidence that likely_cause is correct given the evidence.",
        },
    },
    "required": ["headline", "likely_cause", "recommended_action", "confidence"],
    "additionalProperties": False,
}


def _fallback(reason: str) -> ExplanationResult:
    return ExplanationResult(
        headline="Automatic explanation unavailable",
        likely_cause=f"The explanation service could not produce a result ({reason}). "
        "The underlying discrepancy data above is still accurate.",
        recommended_action="Review the raw discrepancy details manually, or retry generating an explanation.",
        confidence="low",
    )


def explain_discrepancies(discrepancies: list[dict]) -> ExplanationResult:
    """
    discrepancies: list of dicts with keys type, order_id, amount_at_risk,
    currency, summary, details — i.e. already-finalized deterministic output.
    """
    if not discrepancies:
        return _fallback("no discrepancies provided")

    system = (
        "You are a financial reconciliation assistant for an online store's revenue team. "
        "You are given one or more discrepancies that were already deterministically detected "
        "by a separate rules engine. You do NOT decide whether records match - that decision "
        "has already been made. Your only job is to explain the discrepancy in plain language "
        "and suggest a concrete next action for a non-technical operator. Be concise, factual, "
        "and avoid speculation beyond what the data supports. Respond ONLY with a JSON object "
        "matching the given schema, nothing else."
    )
    user = f"Discrepancy data:\n{json.dumps(discrepancies, indent=2, default=str)}"

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=settings.openai_model,
            # Low temperature: this is an explanatory/summarization task, not
            # a creative one. The same discrepancy should reliably produce a
            # stable, factual explanation rather than varied phrasing.
            temperature=0.2,
            max_tokens=400,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "discrepancy_explanation", "strict": True, "schema": SCHEMA},
            },
        )
        raw = response.choices[0].message.content
        if not raw:
            return _fallback("empty response from model")

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return _fallback("model returned malformed JSON")

        try:
            return ExplanationResult(**parsed)
        except ValidationError:
            return _fallback("model response did not match the expected schema")

    except Exception as exc:  # network errors, auth errors, rate limits, etc.
        return _fallback(f"request failed: {exc}")