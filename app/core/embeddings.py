"""Embedding provider selection.

Both app/utils/retrieve.py and app/utils/ingest_files.py need the exact same
embedding function - whatever ingestion used to store a chunk's vector is what
retrieval must use to search for it. get_embedding_model() is the single place
that decides, based on config.EMBEDDING_PROVIDER, which of the three this is:
local BAAI/bge-m3, the free Hugging Face Inference API calling that same model,
or Google's Gemini embedding API (a genuinely different model/vector space -
see config.EMBEDDING_PROVIDER's comment on what switching to it requires).
"""
import time
from typing import List

import numpy as np
from google import genai
from google.genai import types as genai_types
from huggingface_hub import InferenceClient
from huggingface_hub.errors import HfHubHTTPError
from langchain_community.embeddings import HuggingFaceEmbeddings

from app.core import config
from app.core.logger import get_logger

logger = get_logger(__name__)

# Free-tier cold starts return 503 ("model is currently loading") instead of an
# immediate embedding, and can also surface as a 504 while the backend is still
# spinning the model up - local inference never has this failure mode, so it
# only needs handling here.
_COLD_START_RETRIES = 3
_COLD_START_BACKOFF_SECONDS = 3
_COLD_START_STATUS_CODES = {503, 504}


class HFInferenceAPIEmbeddings:
    """LangChain Embeddings interface (embed_query/embed_documents) backed by the
    free Hugging Face Inference API instead of a local model load."""

    def __init__(self, model_name: str, token: str):
        self.model_name = model_name
        self._client = InferenceClient(token=token)

    def _feature_extraction_with_retry(self, text: str) -> np.ndarray:
        for attempt in range(_COLD_START_RETRIES):
            try:
                return self._client.feature_extraction(text, model=self.model_name)
            except HfHubHTTPError as exc:
                status = getattr(exc.response, "status_code", None)
                if status not in _COLD_START_STATUS_CODES or attempt == _COLD_START_RETRIES - 1:
                    raise
                logger.warning(f"HF Inference API returned {status} (model likely still loading), retrying in {_COLD_START_BACKOFF_SECONDS}s")
                time.sleep(_COLD_START_BACKOFF_SECONDS)

    def _embed(self, text: str) -> List[float]:
        vector = np.asarray(self._feature_extraction_with_retry(text), dtype=float)
        if vector.ndim == 2:
            vector = vector.mean(axis=0)  # per-token response - pool to a single sentence vector
        vector = vector.reshape(-1)
        norm = np.linalg.norm(vector)
        if norm > 0:
            vector = vector / norm  # match encode_kwargs={"normalize_embeddings": True} used locally
        return vector.tolist()

    def embed_query(self, text: str) -> List[float]:
        return self._embed(text)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self._embed(text) for text in texts]


class GeminiEmbeddings:
    """LangChain Embeddings interface backed by Google's Gemini embedding API.
    Tags queries and documents with Gemini's asymmetric task types, which improves
    retrieval quality over embedding both the same way."""

    def __init__(self, model_name: str, api_key: str):
        self.model_name = model_name
        self._client = genai.Client(api_key=api_key)

    def _embed(self, texts: List[str], task_type: str) -> List[List[float]]:
        response = self._client.models.embed_content(
            model=self.model_name,
            contents=texts,
            config=genai_types.EmbedContentConfig(task_type=task_type),
        )
        return [e.values for e in response.embeddings]

    def embed_query(self, text: str) -> List[float]:
        return self._embed([text], "RETRIEVAL_QUERY")[0]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._embed(texts, "RETRIEVAL_DOCUMENT")


def get_embedding_model():
    if config.EMBEDDING_PROVIDER == "hf_api":
        if not config.HF_TOKEN:
            raise RuntimeError(
                "EMBEDDING_PROVIDER=hf_api requires HF_TOKEN to be set - the Hugging Face "
                "Inference API no longer accepts unauthenticated requests. Get a free token "
                "at https://huggingface.co/settings/tokens and set it as HF_TOKEN."
            )
        logger.info(f"Using Hugging Face Inference API for embeddings (model={config.HF_EMBEDDING_MODEL})")
        return HFInferenceAPIEmbeddings(config.HF_EMBEDDING_MODEL, config.HF_TOKEN)

    if config.EMBEDDING_PROVIDER == "gemini":
        if not config.GEMINI_API_KEY:
            raise RuntimeError("EMBEDDING_PROVIDER=gemini requires GEMINI_API_KEY to be set.")
        logger.info(f"Using Gemini API for embeddings (model={config.GEMINI_EMBEDDING_MODEL})")
        return GeminiEmbeddings(config.GEMINI_EMBEDDING_MODEL, config.GEMINI_API_KEY)

    import torch

    device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
    return HuggingFaceEmbeddings(
        model_name=config.HF_EMBEDDING_MODEL,
        model_kwargs={"device": device},
        encode_kwargs={"normalize_embeddings": True},
    )
