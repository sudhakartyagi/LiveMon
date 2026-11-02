# Classroom Agent v6.0 — Technical Handover

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
