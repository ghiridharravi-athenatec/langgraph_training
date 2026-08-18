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

import re
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


# Claude 4.7+/5-series models (Opus 5, Sonnet 5, Fable 5, Opus 4.7, Opus 4.8)
# reject explicit sampling params entirely - `temperature`/`top_p`/`top_k` all
# return a 400 ("`temperature` is deprecated for this model"). Older models
# (Haiku 4.5, Opus 4.6, Sonnet 4.6, ...) still accept temperature=0 and it's
# worth keeping there for deterministic guardrail/classification output.
_NO_SAMPLING_PARAMS_MODELS = {
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-fable-5",
    "claude-mythos-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
}

# Claude Opus 5 and Sonnet 5 run adaptive thinking by default even with no
# `thinking` param at all (unlike Opus 4.7/4.8, which stay off unless asked) -
# a behavior change from the model these prompts were originally tuned for.
# Every call through this function is a short, structured JSON completion with
# no need for extended reasoning, and some (e.g. intent classification's
# max_tokens=300) leave little headroom - thinking was silently consuming the
# entire budget and returning empty text, which then failed the JSON-schema
# guardrail with a confusing "not valid JSON" block. Explicitly disabling
# thinking fixes that. (Fable 5/Mythos 5 aren't included here - thinking can't
# be disabled on those at all, and this app doesn't select them by default.)
_THINKING_ON_BY_DEFAULT_MODELS = {"claude-opus-5", "claude-sonnet-5"}


def _generate_with_claude(prompt: str, max_tokens: int, stage: str, model: Optional[str]) -> LLMResult:
    if _anthropic_client is None:
        raise RuntimeError("CLAUDE_API_KEY not configured")

    resolved_model = resolve_claude_model(model)
    create_kwargs = {
        "model": resolved_model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if resolved_model not in _NO_SAMPLING_PARAMS_MODELS:
        create_kwargs["temperature"] = 0
    if resolved_model in _THINKING_ON_BY_DEFAULT_MODELS:
        create_kwargs["thinking"] = {"type": "disabled"}
    response = _anthropic_client.messages.create(**create_kwargs)
    text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
    token_count = (response.usage.input_tokens or 0) + (response.usage.output_tokens or 0)
    return LLMResult(
        text=text,
        token_count=token_count,
        provider="claude",
        safety_event=_claude_safety_event(stage),
        log=f"Answered using claude ({resolved_model})",
    )


def _gemini_finish_reason(response: Any) -> Optional[str]:
    '''Best-effort diagnostic for why response.text came back empty/None despite
    evaluate_model_safety() passing - that check only inspects prompt_feedback.block_reason
    and the four tracked harm categories' safety_ratings, so a candidate with no usable
    text for another reason (RECITATION, MAX_TOKENS, OTHER, ...) sails through it.'''
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return "no candidates in response"
    reason = getattr(candidates[0], "finish_reason", None)
    return str(reason) if reason else None


def _generate_with_gemini(prompt: str, max_tokens: int, stage: str) -> LLMResult:
    if _gemini_client is None:
        raise RuntimeError("GEMINI_API_KEY not configured")

    text, safety_event, token_count = "", None, 0
    # Up to 2 attempts: response.text can come back None/empty even when the
    # harm-category safety check passes (see _gemini_finish_reason) - observed
    # non-deterministic despite temperature=0, so one retry clears most of these
    # instead of needlessly failing a benign request's JSON-schema check.
    for attempt in range(2):
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
        if not safety_event["passed"]:
            text = ""
            break  # a real safety block - retrying won't help
        text = response.text or ""
        if text:
            break
        logger.warning(
            "Gemini returned no text for stage=%s (finish_reason=%s, attempt %d/2)",
            stage, _gemini_finish_reason(response), attempt + 1,
        )

    return LLMResult(
        text=text,
        token_count=token_count,
        provider="gemini",
        safety_event=safety_event,
        log=f"Answered using gemini ({config.GEMINI_MODEL})",
    )


_MARKDOWN_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", re.DOTALL)
_OPEN_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?", re.DOTALL)


def _strip_markdown_fence(text: str) -> str:
    '''Gemini's response_mime_type="application/json" forces raw JSON with no wrapping,
    but Claude's messages.create() has no equivalent - a "return ONLY valid JSON"
    prompt instruction alone isn't always honored. Claude sometimes wraps its answer in
    a ```json ... ``` code fence, sometimes adds a stray sentence before/after it, and
    on a tight max_tokens budget can get cut off mid-fence with no closing ```` ``` ````
    at all. json.loads() then fails on the leading backtick (or leading prose) with
    "Expecting value: line 1 column 1 (char 0)" - the exact same error an empty response
    produces, which is what made this look like an empty-response bug rather than a
    formatting one. Handles, in order: a complete fence wrapping the whole string: strip
    it; an opening fence with no closing one (truncated output): drop just the opener; no
    fence, but a JSON object with prose around it: slice out the first {...} span. Falls
    back to the trimmed original text so a genuine parse failure still surfaces normally.'''
    stripped = text.strip()

    match = _MARKDOWN_FENCE_RE.match(stripped)
    if match:
        return match.group(1).strip()

    opener = _OPEN_FENCE_RE.match(stripped)
    if opener:
        stripped = stripped[opener.end():].strip()

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        return stripped[start:end + 1]

    return stripped


def generate_json(prompt: str, max_tokens: int, stage: str, model: Optional[str] = None) -> LLMResult:
    '''Both providers are prompted identically (the prompt itself asks for raw JSON,
    same as before this abstraction existed) - validate_json_schema, already
    provider-agnostic, is what actually confirms the response parsed, same as today.
    `model` is a UI-facing Claude model choice ("haiku"/"sonnet"/"opus"); it has no
    effect on which Gemini model the fallback uses.'''
    try:
        result = _generate_with_claude(prompt, max_tokens, stage, model)
    except Exception as e:
        logger.warning("Claude request failed for stage=%s (%s) - falling back to Gemini", stage, e)
        result = _generate_with_gemini(prompt, max_tokens, stage)
        result.log = f"Claude failed ({e.__class__.__name__}) - fell back to gemini ({config.GEMINI_MODEL})"
    result.text = _strip_markdown_fence(result.text)
    return result
