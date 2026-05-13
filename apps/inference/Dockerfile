FROM python:3.12-slim

# Build tools needed by some sentence-transformers dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first — cached layer, rebuilt only when requirements change
COPY apps/inference/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the embedding model so the container starts instantly
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-large-en-v1.5')"

# Copy application code + shared retrieval module
COPY apps/inference/ ./apps/inference/
COPY load/retrieval.py ./load/retrieval.py
COPY cortex/ ./cortex/

# Copy pre-computed dual embeddings + fix_summaries cache
COPY results/embeddings_noco.npz ./results/embeddings_noco.npz
COPY results/embeddings_rich.npz ./results/embeddings_rich.npz
COPY results/embeddings_meta.json ./results/embeddings_meta.json
COPY results/fix_summaries.json ./results/fix_summaries.json 2>/dev/null || true

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

CMD ["python", "-m", "streamlit", "run", "apps/inference/inference_app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--server.enableCORS=false"]
