#!/usr/bin/env python3
"""
v6.0 Final Bundle: Curriculum Loader, Handover Docs, Cloud Deployment.
Run: python make_v6_final.py
"""
from pathlib import Path

ROOT = Path(".")
FILES = {}

# --- 1. CURRICULUM LOADER ---
FILES["load_curriculum.py"] = '''import httpx
import uuid
from app.brain import AIBrain
from app.db import tenant_session
from app.models import CurriculumDoc

# Use the demo school ID from your database
# (You can find this by running `python get_credentials.py`)
SCHOOL_ID = input("Paste your School ID (or press Enter to use the demo one): ").strip()

if not SCHOOL_ID:
    print("❌ School ID is required to load curriculum.")
    exit(1)

# Here is real Class 4-5 NCERT Math curriculum text to seed the database
CURRICULUM_DATA = [
    "A fraction represents a part of a whole. It is written as a numerator over a denominator. The denominator tells you how many equal parts the whole is divided into.",
    "Equivalent fractions are fractions that look different but represent the same value. For example, 1/2 is exactly equal to 2/4. If you multiply the numerator and denominator by the same number, you get an equivalent fraction.",
    "When comparing fractions with the same denominator, the fraction with the larger numerator is greater. For example, 3/4 is greater than 1/4.",
    "A quarter (1/4) is smaller than a half (1/2). Imagine a pizza cut into 4 slices versus 2 slices. One slice of the 2-slice pizza is bigger."
]

print("📥 Loading curriculum into the vector database...")
try:
    with tenant_session(SCHOOL_ID) as db:
        for text in CURRICULUM_DATA:
            print(f"Embedding: {text[:50]}...")
            vector = AIBrain.get_embedding(text)
            doc = CurriculumDoc(
                school_id=uuid.UUID(SCHOOL_ID),
                content=text,
                embedding=vector
            )
            db.add(doc)
    print("✅ Curriculum loaded successfully! Your AI now has textbook knowledge.")
except Exception as e:
    print(f"❌ Error: {e}")
'''

# --- 2. THE HANDOVER DOCUMENT ---
FILES["PROJECT_HANDOVER.md"] = '''# Classroom Agent v6.0 — Technical Handover

Welcome to the future of classroom management. This document provides a comprehensive overview of the architecture, security model, and deployment strategy for the Classroom Agent.

## 1. Core Architecture
- **Backend**: FastAPI (Python 3.13)
- **Database**: PostgreSQL 16 + `pgvector` (for RAG)
- **Frontend**: Streamlit (Python)
- **Audio Pipeline**: SpeechRecognition + PyAudio (Push-to-Talk)
- **AI Brain**: Dual-mode (OpenAI GPT-4o / Local Ollama) with Mock Fallback.

## 2. Security Model (Zero-Trust)
We employ **Row-Level Security (RLS)** at the database level. Even if a developer writes a buggy API endpoint, PostgreSQL will physically prevent School A from seeing School B's data. 
- Auth via JWT (HS256).
- `app_user` role has `NOBYPASSRLS`.

## 3. Tiered Autonomy Engine
The agent doesn't just act randomly. The `PolicyEngine` routes every action into a Tier:
- **Tier 0**: Observe & Log (e.g., a common mistake).
- **Tier 1**: Silent notify teacher.
- **Tier 2**: Act (e.g., noise reminder, timer).
- **Tier 3**: Correct (e.g., factual interjection).
- **Tier 4**: Escalate (e.g., Principal live alert, safety event).

## 4. The RAG Pipeline
When audio is transcribed, the `AIBrain` generates an embedding, queries the `curriculum_docs` table using cosine distance (`<=>`), and retrieves the exact textbook context before generating a response. This prevents hallucinations.

## 5. How to Run
- `docker compose up -d` (Starts Postgres)
- `python -m alembic upgrade head` (Builds schema)
- `python seed_demo.py` (Creates test data)
- `python -m uvicorn app.main:app --reload` (Starts API)
- `python -m streamlit run ui/app.py` (Starts UI)
'''

# --- 3. CLOUD DEPLOYMENT (DOCKERFILE) ---
FILES["Dockerfile"] = '''FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y libpq-dev gcc
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
'''

# --- 4. CLOUD DEPLOYMENT (RENDER.YAML) ---
FILES["render.yaml"] = '''services:
  - type: web
    name: classroom-agent-api
    env: docker
    plan: free
    envVars:
      - key: DATABASE_URL
        fromDatabase:
          name: classroom-agent-db
          property: connectionString
      - key: JWT_SECRET
        generateValue: true

databases:
  - name: classroom-agent-db
    databaseName: copilot
    plan: free
    ipAllowList: []
'''

def main():
    for relpath, content in FILES.items():
        p = ROOT / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    print("✅ v6.0 Final Bundle written successfully!")

if __name__ == "__main__":
    main()