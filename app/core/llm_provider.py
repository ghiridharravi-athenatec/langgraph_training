'''Single entry point for every text-generation call in the pipeline (intent
classification, answer generation, the database chat agent) - tries Claude
first, falls back to Gemini on ANY failure (auth, rate limit, timeout, network,
malformed response - anything raised by the Anthropic SDK call itself).

Known limitation, not silently papered over: app/core/guardrails.py's
evaluate_model_safety()/build_safety_settings() ("Model safety classifier" on
the Guardrails page) is built entirely around Gemini's proprietary
safety-ratings API (prompt_feedback.block_reason, candidate.safety_ratings[]).
Claude has no equivalent structured signal - its safety behavior is baked into
the model's own refusals, which would surface as an unhelpful/empty answer and
get caught by the existing not_empty/JSON-schema guardrails instead, not by
this one. So: when Claude serves a request, that guardrail reports a
deliberate pass-through event rather than a real inspection; it's a real,
full inspection only on the Gemini fallback path. This is visible in the
returned event via `flagged_categories`/`provider` - see `_claude_safety_event`.
'''

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import anthropic
from google import genai
from google.genai import types as genai_types

from app.core import config
from app.core.guardrails import extract_token_count
from app.core.guardrails_agent import guardrails_agent
from app.core.logger import get_logger

logger = get_logger(__name__)

_anthropic_client = anthropic.Anthropic(api_key=config.CLAUDE_API_KEY) if config.CLAUDE_API_KEY else None
_gemini_client = genai.Client(api_key=config.GEMINI_API_KEY) if config.GEMINI_API_KEY else None


@dataclass
class LLMResult:
    text: str
    token_count: int
    provider: str  # "claude" | "gemini"
    safety_event: Dict[str, Any]
    log: str = field(default="")


def _claude_safety_event(stage: str) -> Dict[str, Any]:
    return {"stage": stage, "passed": True, "reason": None, "flagged_categories": [], "provider": "claude"}


def resolve_claude_model(model_choice: Optional[str]) -> str:
    '''Maps a UI-facing name ("haiku"/"sonnet"/"opus") to a real model id, falling
    back to the configured default for anything unset/unrecognized - never passes
    an arbitrary client-supplied string straight through to the API.'''
    if model_choice and model_choice in config.CLAUDE_MODEL_CHOICES:
        return config.CLAUDE_MODEL_CHOICES[model_choice]
    return config.CLAUDE_MODEL


def _generate_with_claude(prompt: str, max_tokens: int, stage: str, model: Optional[str]) -> LLMResult:
    if _anthropic_client is None:
        raise RuntimeError("CLAUDE_API_KEY not configured")

    resolved_model = resolve_claude_model(model)
    response = _anthropic_client.messages.create(
        model=resolved_model,
        max_tokens=max_tokens,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
    token_count = (response.usage.input_tokens or 0) + (response.usage.output_tokens or 0)
    return LLMResult(
        text=text,
        token_count=token_count,
        provider="claude",
        safety_event=_claude_safety_event(stage),
        log=f"Answered using claude ({resolved_model})",
    )


def _generate_with_gemini(prompt: str, max_tokens: int, stage: str) -> LLMResult:
    if _gemini_client is None:
        raise RuntimeError("GEMINI_API_KEY not configured")

    response = _gemini_client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            temperature=0,
            max_output_tokens=max_tokens,
            response_mime_type="application/json",
            safety_settings=guardrails_agent.build_safety_settings(),
        ),
    )
    token_count = extract_token_count(response)
    safety_event = guardrails_agent.check_model_safety(response, stage=stage)
    safety_event["provider"] = "gemini"
    text = response.text if safety_event["passed"] else ""
    return LLMResult(
        text=text,
        token_count=token_count,
        provider="gemini",
        safety_event=safety_event,
        log=f"Answered using gemini ({config.GEMINI_MODEL})",
    )


def generate_json(prompt: str, max_tokens: int, stage: str, model: Optional[str] = None) -> LLMResult:
    '''Both providers are prompted identically (the prompt itself asks for raw JSON,
    same as before this abstraction existed) - validate_json_schema, already
    provider-agnostic, is what actually confirms the response parsed, same as today.
    `model` is a UI-facing Claude model choice ("haiku"/"sonnet"/"opus"); it has no
    effect on which Gemini model the fallback uses.'''
    try:
        return _generate_with_claude(prompt, max_tokens, stage, model)
    except Exception as e:
        logger.warning("Claude request failed for stage=%s (%s) - falling back to Gemini", stage, e)
        result = _generate_with_gemini(prompt, max_tokens, stage)
        result.log = f"Claude failed ({e.__class__.__name__}) - fell back to gemini ({config.GEMINI_MODEL})"
        return result
