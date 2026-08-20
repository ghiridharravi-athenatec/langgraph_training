from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

KNOWN_PII_ENTITIES = {
    "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "US_SSN", "US_BANK_NUMBER",
    "US_DRIVER_LICENSE", "US_PASSPORT", "IBAN_CODE", "IP_ADDRESS", "CRYPTO",
    "PERSON", "LOCATION", "NRP", "MEDICAL_LICENSE",
}
KNOWN_HARM_CATEGORIES = {
    "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
    "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT",
}
KNOWN_SAFETY_THRESHOLDS = {"BLOCK_NONE", "BLOCK_ONLY_HIGH", "BLOCK_MEDIUM_AND_ABOVE", "BLOCK_LOW_AND_ABOVE"}


class GuardrailConfigOut(BaseModel):
    min_question_length: int
    max_question_length: int
    blocked_keywords: List[str]
    input_pii_entities: List[str]
    input_pii_score_threshold: float
    output_pii_entities: List[str]
    output_pii_score_threshold: float
    daily_token_quota: int
    model_safety_categories: List[str]
    model_safety_threshold: str
    intent_confidence_threshold: float
    semantic_cache_similarity_threshold: float
    semantic_cache_max_candidates: int
    min_relevance_score: float
    max_context_chunks: int
    max_context_chars: int
    min_groundedness_score: float
    allowed_url_domains: List[str]
    max_answer_length: int
    allowed_topics: List[str]
    compliance_keywords: List[str]
    bias_detection_enabled: bool
    tone_calibration_enabled: bool
    document_routing_enabled: bool
    document_routing_min_score: float
    indirect_injection_detection_enabled: bool


def _clean_list(values: List[str]) -> List[str]:
    return sorted({v.strip().lower() for v in values if v and v.strip()})


class GuardrailConfigUpdate(BaseModel):
    '''A partial update - every field is optional, and only the ones actually
    provided are persisted/applied. Numeric bounds are sanity limits (not
    tuned values in themselves) so a typo can't wedge the pipeline, e.g. a
    quota of -5 or a max_context_chunks of 0.'''

    min_question_length: Optional[int] = Field(None, ge=0, le=500)
    max_question_length: Optional[int] = Field(None, ge=10, le=20000)
    blocked_keywords: Optional[List[str]] = None
    input_pii_entities: Optional[List[str]] = None
    input_pii_score_threshold: Optional[float] = Field(None, ge=0, le=1)
    output_pii_entities: Optional[List[str]] = None
    output_pii_score_threshold: Optional[float] = Field(None, ge=0, le=1)
    daily_token_quota: Optional[int] = Field(None, ge=0)
    model_safety_categories: Optional[List[str]] = None
    model_safety_threshold: Optional[str] = None
    intent_confidence_threshold: Optional[float] = Field(None, ge=0, le=1)
    semantic_cache_similarity_threshold: Optional[float] = Field(None, ge=0, le=1)
    semantic_cache_max_candidates: Optional[int] = Field(None, ge=1, le=2000)
    min_relevance_score: Optional[float] = Field(None, ge=0, le=1)
    max_context_chunks: Optional[int] = Field(None, ge=1, le=100)
    max_context_chars: Optional[int] = Field(None, ge=500, le=200000)
    min_groundedness_score: Optional[float] = Field(None, ge=0, le=1)
    allowed_url_domains: Optional[List[str]] = None
    max_answer_length: Optional[int] = Field(None, ge=100, le=50000)
    allowed_topics: Optional[List[str]] = None
    compliance_keywords: Optional[List[str]] = None
    bias_detection_enabled: Optional[bool] = None
    tone_calibration_enabled: Optional[bool] = None
    document_routing_enabled: Optional[bool] = None
    document_routing_min_score: Optional[float] = Field(None, ge=0, le=1)
    indirect_injection_detection_enabled: Optional[bool] = None

    @field_validator("blocked_keywords", "allowed_url_domains", "allowed_topics", "compliance_keywords")
    @classmethod
    def _clean_free_text_list(cls, v):
        return None if v is None else _clean_list(v)

    @field_validator("input_pii_entities", "output_pii_entities")
    @classmethod
    def _validate_pii_entities(cls, v):
        if v is None:
            return v
        unknown = set(v) - KNOWN_PII_ENTITIES
        if unknown:
            raise ValueError(f"Unknown PII entity type(s): {', '.join(sorted(unknown))}")
        return v

    @field_validator("model_safety_categories")
    @classmethod
    def _validate_categories(cls, v):
        if v is None:
            return v
        unknown = set(v) - KNOWN_HARM_CATEGORIES
        if unknown:
            raise ValueError(f"Unknown harm category/categories: {', '.join(sorted(unknown))}")
        return v

    @field_validator("model_safety_threshold")
    @classmethod
    def _validate_threshold(cls, v):
        if v is not None and v not in KNOWN_SAFETY_THRESHOLDS:
            raise ValueError(f"Unknown safety threshold '{v}' - must be one of {sorted(KNOWN_SAFETY_THRESHOLDS)}")
        return v

    @model_validator(mode="after")
    def _min_lt_max_question_length(self):
        if (
            self.min_question_length is not None
            and self.max_question_length is not None
            and self.min_question_length >= self.max_question_length
        ):
            raise ValueError("min_question_length must be less than max_question_length")
        return self

    def as_patch(self) -> dict:
        return {k: v for k, v in self.model_dump().items() if v is not None}
