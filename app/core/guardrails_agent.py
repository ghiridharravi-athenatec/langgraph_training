'''The single owner of every guardrail decision in the pipeline.

Deliberately NOT an autonomous/LLM-driven agent - unlike app/core/db_agent.py
(the app's one genuinely agentic, tool-calling piece), GuardrailsAgent is a
plain deterministic orchestrator. Guardrails have to run unconditionally on
every turn; letting a model decide whether to run one would defeat the point.
"Agent" here names an architectural role, not an autonomy claim: the document
pipeline (app/utils/retrieve.py + app/utils/llm.py) and the database agent
(app/core/db_agent.py, via app/api/v1/database.py) are task-performing agents
that call into this one for every guardrail outcome instead of deciding it
themselves.

Every method is a thin delegation to app.core.guardrails, which stays the
low-level implementation layer - this module owns *orchestration*, not new
check logic. Return shapes are unchanged from the functions they wrap, so
nothing downstream (Mongo persistence, the frontend's guardrail trace, this
project's messages.yml) needed to change to adopt this.

redact_pii/restore_pii aren't exposed here - they're already fully
encapsulated inside check_input/check_output, and restore_pii stays unwired
from every pipeline path by design. timed_node also isn't wrapped - it's a
generic LangGraph node-timing decorator, not guardrail-specific.
'''

from typing import Any, Dict, List, Optional, Tuple

from app.core import guardrails


class GuardrailsAgent:
    # -----------------------------------------------------------------
    # Shared by both chatbots
    # -----------------------------------------------------------------

    def check_input(self, question: str) -> Dict[str, Any]:
        return guardrails.validate_input(question)

    def check_quota(self, tokens_used_today: int, daily_quota: int, stage: str = "quota_check") -> Dict[str, Any]:
        return guardrails.validate_quota(tokens_used_today, daily_quota, stage=stage)

    def check_output(self, answer: str) -> Dict[str, Any]:
        return guardrails.validate_output(answer)

    def check_json_schema(self, raw_text: str, required_fields: Dict[str, type], stage: str) -> Dict[str, Any]:
        return guardrails.validate_json_schema(raw_text, required_fields, stage)

    def check_model_safety(self, response: Any, stage: str) -> Dict[str, Any]:
        return guardrails.evaluate_model_safety(response, stage)

    def build_safety_settings(self) -> List[Any]:
        return guardrails.build_safety_settings()

    # -----------------------------------------------------------------
    # Document pipeline only
    # -----------------------------------------------------------------

    def check_has_documents(self, has_documents: bool) -> Dict[str, Any]:
        return guardrails.validate_has_documents(has_documents)

    def check_retrieval(self, chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
        return guardrails.validate_retrieval(chunks)

    def apply_context_budget(self, chunks: List[Dict[str, Any]], stage: str = "context_budget") -> Dict[str, Any]:
        return guardrails.validate_context_budget(chunks, stage=stage)

    def check_groundedness(
        self, answer: str, context: str, embedding_model: Any, stage: str = "groundedness_check"
    ) -> Dict[str, Any]:
        return guardrails.validate_groundedness(answer, context, embedding_model, stage=stage)

    def check_intent_confidence(self, intent: str, confidence: float) -> Dict[str, Any]:
        return guardrails.evaluate_intent_detection(intent, confidence)

    def intent_guardrail_fragments(self) -> Tuple[str, str]:
        '''Prompt fragments IntentClassifier splices into its one classification call -
        the always-on injection-detection and self-harm-detection instructions, plus
        topic-restriction instructions if an admin has configured allowed_topics. Returns
        (extra_instructions, extra_schema_fields); schema_fields always includes the
        injection and self-harm fields (both always-on) and only adds the topic fields
        when topic restriction is configured.'''
        topic_instructions = guardrails.build_topic_restriction_instructions()
        instructions = (
            guardrails.INJECTION_DETECTION_INSTRUCTIONS
            + guardrails.SELF_HARM_DETECTION_INSTRUCTIONS
            + (topic_instructions or "")
        )
        schema_fields = f"{guardrails.INJECTION_DETECTION_SCHEMA_FIELDS},\n                    {guardrails.SELF_HARM_DETECTION_SCHEMA_FIELDS}"
        if topic_instructions:
            schema_fields += f",\n                    {guardrails.TOPIC_RESTRICTION_SCHEMA_FIELDS}"
        return instructions, schema_fields

    def interpret_intent_guardrails(self, parsed: Dict[str, Any], topic_checked: bool) -> List[Dict[str, Any]]:
        '''Evaluates every guardrail signal riding on IntentClassifier's classification
        response. topic_checked should be True iff intent_guardrail_fragments() included
        topic-restriction instructions on this same call - keeps evaluate_topic_restriction
        from running (and reporting a permissive pass) on a call that never asked for it.'''
        events = [
            guardrails.evaluate_llm_injection_verdict(
                bool(parsed.get("is_prompt_injection")), parsed.get("injection_reason"),
            ),
            guardrails.evaluate_self_harm_check(
                bool(parsed.get("is_self_harm_content")), parsed.get("self_harm_reason"),
            ),
        ]
        if topic_checked:
            events.append(
                guardrails.evaluate_topic_restriction(
                    bool(parsed.get("topic_in_scope", True)), parsed.get("topic_reason"),
                )
            )
        return events

    def bias_guardrail_fragments(self) -> Tuple[str, str]:
        '''Prompt fragments answer_node splices into its one generation call, if bias
        self-reporting is enabled. Returns ("", "") when disabled, so the caller can
        splice unconditionally without its own enabled-check.'''
        from app.core import guardrail_config

        if not guardrail_config.get_config().get("bias_detection_enabled", True):
            return "", ""
        return guardrails.BIAS_DETECTION_INSTRUCTIONS, f",\n                    {guardrails.BIAS_DETECTION_SCHEMA_FIELDS}"

    def interpret_bias_guardrail(self, parsed: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        '''Returns the bias event if bias detection is enabled and the generation
        response actually included a bias_flag field (i.e. bias_guardrail_fragments()
        was spliced into that same call), else None.'''
        from app.core import guardrail_config

        if not guardrail_config.get_config().get("bias_detection_enabled", True):
            return None
        if "bias_flag" not in parsed:
            return None
        return guardrails.evaluate_bias_detection(bool(parsed.get("bias_flag")), parsed.get("bias_reason"))


guardrails_agent = GuardrailsAgent()
