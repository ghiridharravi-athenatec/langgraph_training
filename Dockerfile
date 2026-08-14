# FastAPI backend — RAG pipeline (LangGraph + MongoDB Atlas + Gemini)
FROM python:3.11-slim

# System libraries needed by opencv/paddleocr (imaging) and pymupdf/presidio at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

# Install the CPU-only torch build first so the default PyPI resolve doesn't pull
# multi-gigabyte CUDA wheels; requirements.txt's own torch entry is then already
# satisfied and pip skips reinstalling it.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch>=2.3.0" \
    && pip install --no-cache-dir -r requirements.txt \
    && python -m spacy download en_core_web_md

COPY app ./app
COPY streamlit_app.py .

# Runtime-writable dirs (log rotation, uploaded files, OCR-extracted images).
RUN mkdir -p logs app/uploads app/extracted_images

# 7860 is Hugging Face Spaces' conventional Docker SDK port (see README.md's
# `app_port` front matter) - used here instead of 8000 so this same image
# deploys unchanged to a Space. Local docker-compose maps host 8000 to this
# same container port, so `docker compose up` still serves on localhost:8000.
EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:7860/ || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
