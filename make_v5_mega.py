#!/usr/bin/env python3
"""
Generate v5.5 Mega-Bundle: RAG + LLM Brain + Streamlit UI.
Run: python make_v5_mega.py
"""
from pathlib import Path
import zipfile

ROOT = Path(".")
FILES = {}

# --- 1. NEW MIGRATION (Vector DB) ---
FILES["alembic/versions/0004_vector.py"] = '''"""Add pgvector for curriculum RAG"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

revision = "0004"
down_revision = "0003"

def upgrade():
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    
    op.create_table(
        "curriculum_docs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("school_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("content", sa.String(2000), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=True),
    )
    
    op.execute("ALTER TABLE curriculum_docs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE curriculum_docs FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tenant_isolation ON curriculum_docs USING (school_id = current_setting('app.current_tenant_id', true)::uuid) WITH CHECK (school_id = current_setting('app.current_tenant_id', true)::uuid)")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON curriculum_docs TO app_user")

def downgrade():
    op.execute("DROP TABLE IF EXISTS curriculum_docs CASCADE")
'''

# --- 2. MODELS (Add CurriculumDoc) ---
FILES["app/models.py"] = '''import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, func, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from pgvector.sqlalchemy import Vector

class Base(DeclarativeBase):
    pass

def _uuid():
    return uuid.uuid4()

class School(Base):
    __tablename__ = "schools"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

class Teacher(Base):
    __tablename__ = "teachers"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("schools.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

class Principal(Base):
    __tablename__ = "principals"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("schools.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

class Classroom(Base):
    __tablename__ = "classes"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("schools.id"), nullable=False)
    grade: Mapped[int] = mapped_column(nullable=False)
    section: Mapped[str] = mapped_column(String(10), nullable=False)
    subject: Mapped[str] = mapped_column(String(50), nullable=False)
    teacher_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("teachers.id"), nullable=False)

class Student(Base):
    __tablename__ = "students"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("schools.id"), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("classes.id"), nullable=False)
    pseudonym: Mapped[str] = mapped_column(String(100), nullable=False)

class Lesson(Base):
    __tablename__ = "lessons"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("schools.id"), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("classes.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    mode: Mapped[str] = mapped_column(String(20), default="normal")

class Policy(Base):
    __tablename__ = "policies"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("schools.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("schools.id"), nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource: Mapped[str] = mapped_column(String(200), nullable=False)
    is_cross_tenant_attempt: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class AgentAction(Base):
    __tablename__ = "agent_actions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("schools.id"), nullable=False)
    lesson_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("lessons.id"), nullable=False)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    tier: Mapped[int] = mapped_column(nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    target_type: Mapped[str] = mapped_column(String(50), nullable=True)
    target_id: Mapped[str] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="logged")
    principal_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class Dispute(Base):
    __tablename__ = "disputes"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("schools.id"), nullable=False)
    agent_action_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_actions.id"), nullable=False)
    teacher_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    flag_reason: Mapped[str] = mapped_column(String(500), nullable=False)
    resolution: Mapped[str] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class ClassState(Base):
    __tablename__ = "class_states"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("schools.id"), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("classes.id"), nullable=False)
    is_paused: Mapped[bool] = mapped_column(Boolean, default=False)
    paused_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

class CurriculumDoc(Base):
    __tablename__ = "curriculum_docs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("schools.id"), nullable=False)
    content: Mapped[str] = mapped_column(String(2000), nullable=False)
    embedding: Mapped[list] = mapped_column(Vector(1536), nullable=True)
'''

# --- 3. RAG & LLM ENGINE ---
FILES["app/brain.py"] = '''import os
from sqlalchemy import text
from app.db import tenant_session

class AIBrain:
    @staticmethod
    def get_embedding(text: str) -> list:
        """Mock embedding: if OpenAI key is missing, generate a deterministic vector."""
        if not os.getenv("OPENAI_API_KEY"):
            # Simple mock: hash the text into a 1536-length vector
            return [float(hash(text + str(i)) % 100) / 100.0 for i in range(1536)]
        
        from openai import OpenAI
        client = OpenAI()
        response = client.embeddings.create(input=text, model="text-embedding-3-small")
        return response.data[0].embedding

    @staticmethod
    def analyze_misconception(transcript: str, school_id: str) -> str:
        """
        1. Searches curriculum_docs for context.
        2. Uses LLM to generate a correction.
        """
        # RAG: Find relevant curriculum
        query_vector = AIBrain.get_embedding(transcript)
        context = ""
        with tenant_session(school_id) as db:
            # pgvector cosine distance search (<=>)
            results = db.execute(
                text("SELECT content FROM curriculum_docs ORDER BY embedding <=> :vec LIMIT 1"),
                {"vec": str(query_vector)}
            ).fetchone()
            if results:
                context = results[0]

        if not os.getenv("OPENAI_API_KEY"):
            return f"[Mock AI] I noticed a misconception. Based on our curriculum ({context}), let's re-explain this step-by-step."

        from openai import OpenAI
        client = OpenAI()
        prompt = f"""You are an AI teaching assistant. The teacher just said: "{transcript}".
Here is the official curriculum context: {context}.
If the teacher made a factual error, provide a 1-sentence, polite interjection to correct it. If no error, say 'None'."""
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
'''

# --- 4. UPDATE AUDIO PROCESSOR ---
FILES["app/audio.py"] = '''from typing import Optional
from app.engine import Tier
from app.brain import AIBrain
import uuid

class AudioProcessor:
    @staticmethod
    def process_chunk(chunk: dict, school_id: str) -> Optional[dict]:
        transcript = chunk.get("transcript", "").lower()
        noise = chunk.get("noise_db", 0)
        
        if noise > 75:
            return {"action_type": "scripted_reminder", "reason": f"Ambient noise exceeded threshold ({noise}dB)", "tier": Tier.ACT}
        
        # If math terms are spoken, trigger the AI Brain
        if "fraction" in transcript or "half" in transcript or "quarter" in transcript:
            ai_response = AIBrain.analyze_misconception(transcript, school_id)
            if ai_response and ai_response != "None":
                return {"action_type": "factual_correction", "reason": ai_response, "tier": Tier.CORRECT}
                
        return None
'''

# --- 5. UPDATE MAIN (Pass school_id to audio processor) ---
FILES["app/main.py"] = '''import uuid
from datetime import datetime, timezone, time, timedelta
from fastapi import FastAPI, Depends, HTTPException
from app.db import tenant_session
from app.deps import get_principal
from app.models import Student, AgentAction, Policy, AuditLog, Dispute, Lesson, ClassState, CurriculumDoc
from app.schemas import PolicyCreate, ActionRequest, DisputeRequest, AudioChunk, CurriculumUpload
from app.engine import PolicyEngine
from app.audio import AudioProcessor
from app.brain import AIBrain

app = FastAPI(title="Classroom Agent v5.5 (RAG + AI)")

@app.get("/health")
def health():
    return {"status": "ok", "version": "5.5.0"}

@app.get("/students/{student_id}")
def get_student(student_id: uuid.UUID, principal=Depends(get_principal)):
    with tenant_session(principal["school_id"]) as db:
        student = db.get(Student, student_id)
        if student is None: raise HTTPException(404, "Not found")
        return {"id": str(student.id), "pseudonym": student.pseudonym}

@app.post("/curriculum/upload")
def upload_curriculum(data: CurriculumUpload, principal=Depends(get_principal)):
    with tenant_session(principal["school_id"]) as db:
        vector = AIBrain.get_embedding(data.content)
        doc = CurriculumDoc(school_id=uuid.UUID(principal["school_id"]), content=data.content, embedding=vector)
        db.add(doc)
        return {"status": "uploaded"}

@app.post("/policies", status_code=201)
def create_policy(policy: PolicyCreate, principal=Depends(get_principal)):
    if principal.get("role") not in ["admin", "principal"]: raise HTTPException(403, "Only principal/admin can set policies")
    with tenant_session(principal["school_id"]) as db:
        new_policy = Policy(school_id=uuid.UUID(principal["school_id"]), name=policy.name, config=policy.config)
        db.add(new_policy)
        db.flush()
        return {"id": str(new_policy.id)}

@app.post("/actions", status_code=201)
def trigger_action(req: ActionRequest, principal=Depends(get_principal)):
    with tenant_session(principal["school_id"]) as db:
        policy = db.query(Policy).order_by(Policy.created_at.desc()).first()
        config = policy.config if policy else {}
        
        if req.action_type in ["praise_naming", "discipline_naming"]:
            if not req.target_student_id: raise HTTPException(400, f"{req.action_type} requires target_student_id")
            if req.action_type == "praise_naming" and not config.get("allow_praise_naming", False):
                raise HTTPException(403, "Praise naming is disabled by school policy")
            if req.action_type == "discipline_naming":
                thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
                recent = db.query(AgentAction).filter(AgentAction.action_type == "discipline_naming", AgentAction.target_id == str(req.target_student_id), AgentAction.created_at >= thirty_days_ago).count()
                if recent >= 2:
                    action = AgentAction(school_id=uuid.UUID(principal["school_id"]), lesson_id=req.lesson_id, action_type="pattern_report", tier=4, reason=f"Student {req.target_student_id} flagged 3 times in 30 days.", target_type="student", target_id=str(req.target_student_id), principal_notified=True)
                    db.add(action)
                    db.flush()
                    return {"id": str(action.id), "tier": 4, "requires_principal": True, "note": "Pattern threshold reached"}

        tier = PolicyEngine.route_action(req.action_type, req.context, config)
        action = AgentAction(school_id=uuid.UUID(principal["school_id"]), lesson_id=req.lesson_id, action_type=req.action_type, tier=tier, reason=req.reason, target_type="student" if req.target_student_id else None, target_id=str(req.target_student_id) if req.target_student_id else None, principal_notified=(tier == 4))
        db.add(action)
        db.flush()
        return {"id": str(action.id), "tier": tier, "requires_principal": (tier == 4)}

@app.post("/actions/{action_id}/flag", status_code=201)
def flag_action(action_id: uuid.UUID, req: DisputeRequest, principal=Depends(get_principal)):
    with tenant_session(principal["school_id"]) as db:
        action = db.get(AgentAction, action_id)
        if not action: raise HTTPException(404, "Action not found")
        dispute = Dispute(school_id=uuid.UUID(principal["school_id"]), agent_action_id=action.id, teacher_id=uuid.UUID(principal["sub"]), flag_reason=req.flag_reason, resolution="agent_wrong" if action.tier >= 3 else "agent_right")
        db.add(dispute)
        action.status = "flagged"
        return {"dispute_id": str(dispute.id), "resolution": dispute.resolution}

@app.get("/teacher/dashboard/{lesson_id}")
def teacher_dashboard(lesson_id: uuid.UUID, principal=Depends(get_principal)):
    if principal.get("role") not in ["teacher", "principal"]: raise HTTPException(403, "Access denied")
    with tenant_session(principal["school_id"]) as db:
        actions = db.query(AgentAction).filter(AgentAction.lesson_id == lesson_id).order_by(AgentAction.created_at).all()
        return [{"id": str(a.id), "time": a.created_at.strftime("%H:%M:%S"), "action": a.action_type, "tier": a.tier, "reason": a.reason, "status": a.status} for a in actions]

@app.get("/principal/digest")
def principal_digest(date: str = None, principal=Depends(get_principal)):
    if principal.get("role") not in ["principal", "admin"]: raise HTTPException(403, "Access denied. Principal only.")
    if not date: target_date = datetime.now(timezone.utc).date()
    else:
        try: target_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError: raise HTTPException(400, "Invalid date format. Use YYYY-MM-DD")
    start_of_day = datetime.combine(target_date, time.min)
    end_of_day = datetime.combine(target_date, time.max)

    with tenant_session(principal["school_id"]) as db:
        action_items = db.query(AgentAction).filter(AgentAction.tier == 4, AgentAction.created_at >= start_of_day, AgentAction.created_at <= end_of_day).all()
        disputes = db.query(Dispute).filter(Dispute.created_at >= start_of_day).all()
        discipline_flags = db.query(AgentAction).filter(AgentAction.action_type == "discipline_naming", AgentAction.created_at >= start_of_day).all()
        return {"date": str(target_date), "action_items": [{"id": str(a.id), "type": a.action_type, "reason": a.reason, "status": a.status} for a in action_items], "disputes": [{"id": str(d.id), "reason": d.flag_reason, "resolution": d.resolution} for d in disputes], "discipline_flags": [{"id": str(a.id), "action": a.action_type, "status": a.status} for a in discipline_flags]}

@app.post("/principal/resolve/{action_id}")
def resolve_action(action_id: uuid.UUID, principal=Depends(get_principal)):
    if principal.get("role") not in ["principal", "admin"]: raise HTTPException(403, "Principal only")
    with tenant_session(principal["school_id"]) as db:
        action = db.get(AgentAction, action_id)
        if not action: raise HTTPException(404, "Action not found")
        action.status = "resolved_by_principal"
        return {"id": str(action.id), "status": action.status}

@app.post("/audio/ingest")
def ingest_audio(chunk: AudioChunk, principal=Depends(get_principal)):
    with tenant_session(principal["school_id"]) as db:
        state = db.query(ClassState).filter(ClassState.class_id == chunk.class_id).first()
        if state and state.is_paused: return {"status": "ignored", "reason": "Agent is paused for this class"}
        
        # Pass school_id for RAG context
        result = AudioProcessor.process_chunk(chunk.model_dump(), principal["school_id"])
        if result:
            action = AgentAction(school_id=uuid.UUID(principal["school_id"]), lesson_id=chunk.lesson_id, action_type=result["action_type"], tier=result["tier"], reason=result["reason"], status="logged" if result["tier"] == 0 else "executed")
            db.add(action)
            db.flush()
            return {"status": "action_triggered", "action_id": str(action.id), "tier": result["tier"], "reason": result["reason"]}
        return {"status": "processed", "action": None}

@app.post("/agent/pause/{class_id}")
def pause_agent(class_id: uuid.UUID, principal=Depends(get_principal)):
    with tenant_session(principal["school_id"]) as db:
        state = db.query(ClassState).filter(ClassState.class_id == class_id).first()
        if not state:
            state = ClassState(school_id=uuid.UUID(principal["school_id"]), class_id=class_id, is_paused=True, paused_at=datetime.now(timezone.utc))
            db.add(state)
        else:
            state.is_paused = True
            state.paused_at = datetime.now(timezone.utc)
        return {"status": "paused", "class_id": str(class_id)}

@app.post("/agent/resume/{class_id}")
def resume_agent(class_id: uuid.UUID, principal=Depends(get_principal)):
    with tenant_session(principal["school_id"]) as db:
        state = db.query(ClassState).filter(ClassState.class_id == class_id).first()
        if state:
            state.is_paused = False
            state.paused_at = None
        return {"status": "resumed", "class_id": str(class_id)}
'''

# --- 6. UPDATE SCHEMAS ---
FILES["app/schemas.py"] = '''from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from uuid import UUID

class PolicyCreate(BaseModel):
    name: str
    config: Dict[str, Any]

class ActionRequest(BaseModel):
    lesson_id: UUID
    action_type: str
    reason: str
    target_student_id: Optional[UUID] = None
    context: Dict[str, Any] = Field(default_factory=dict)

class DisputeRequest(BaseModel):
    flag_reason: str

class AudioChunk(BaseModel):
    class_id: UUID
    lesson_id: UUID
    transcript: str
    speaker: str
    noise_db: int

class CurriculumUpload(BaseModel):
    content: str
'''

# --- 7. STREAMLIT UI ---
FILES["ui/app.py"] = '''import streamlit as st
import httpx
import uuid
from datetime import datetime

API_URL = "http://localhost:8000"
# For demo purposes, we bypass real JWT auth in the UI by using a mock token
# In production, this would be a login screen
HEADERS = {"Authorization": "Bearer <MOCK_TOKEN>"}

st.set_page_config(page_title="Classroom Agent v5.5", layout="wide")
st.title("🤖 Classroom Agent v5.5")

tab1, tab2, tab3 = st.tabs(["Teacher View", "Principal Digest", "Curriculum Upload"])

with tab1:
    st.header("Teacher Live Dashboard")
    class_id = st.text_input("Class ID", value=str(uuid.uuid4()))
    lesson_id = st.text_input("Lesson ID", value=str(uuid.uuid4()))
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🚨 Pause Agent (Kill Switch)"):
            with httpx.Client() as client:
                r = client.post(f"{API_URL}/agent/pause/{class_id}", headers=HEADERS)
                st.success(r.json())
    with col2:
        if st.button("▶️ Resume Agent"):
            with httpx.Client() as client:
                r = client.post(f"{API_URL}/agent/resume/{class_id}", headers=HEADERS)
                st.success(r.json())

    st.subheader("Simulate Live Audio")
    transcript = st.text_area("Teacher Transcript", value="1/2 is bigger than 3/4")
    noise_db = st.slider("Noise Level (dB)", 0, 100, 80)
    
    if st.button("🎤 Send Audio Chunk"):
        with httpx.Client() as client:
            r = client.post(f"{API_URL}/audio/ingest", headers=HEADERS, json={
                "class_id": class_id,
                "lesson_id": lesson_id,
                "transcript": transcript,
                "speaker": "teacher",
                "noise_db": noise_db
            })
            st.json(r.json())
            
    st.subheader("Live Timeline")
    if st.button("Refresh Timeline"):
        with httpx.Client() as client:
            r = client.get(f"{API_URL}/teacher/dashboard/{lesson_id}", headers=HEADERS)
            st.table(r.json())

with tab2:
    st.header("Principal After-Class Digest")
    if st.button("Load Today's Digest"):
        with httpx.Client() as client:
            r = client.get(f"{API_URL}/principal/digest", headers=HEADERS)
            data = r.json()
            st.subheader("Action Items (Tier 4)")
            st.table(data.get("action_items", []))
            st.subheader("Disputes")
            st.table(data.get("disputes", []))
            st.subheader("Discipline Naming Logs")
            st.table(data.get("discipline_flags", []))

with tab3:
    st.header("Curriculum Grounding (RAG)")
    curriculum_text = st.text_area("Paste NCERT Chapter Text", height=200)
    if st.button("Upload to Vector DB"):
        with httpx.Client() as client:
            r = client.post(f"{API_URL}/curriculum/upload", headers=HEADERS, json={"content": curriculum_text})
            st.success(r.json())
'''

# --- 8. SEED DATA SCRIPT (For UI Testing) ---
FILES["seed_demo.py"] = '''import httpx
import uuid
from app.auth import issue_token
from app.db import tenant_session
from sqlalchemy import text

# Create a demo school, teacher, and class
school_id = uuid.uuid4()
teacher_id = uuid.uuid4()
class_id = uuid.uuid4()
lesson_id = uuid.uuid4()

with tenant_session(school_id) as db:
    db.execute(text("INSERT INTO schools (id, name) VALUES (:sid, 'Demo School')"), {"sid": school_id})
    db.execute(text("INSERT INTO teachers (id, school_id, name) VALUES (:tid, :sid, 'Demo Teacher')"), {"tid": teacher_id, "sid": school_id})
    db.execute(text("INSERT INTO classes (id, school_id, grade, section, subject, teacher_id) VALUES (:cid, :sid, 4, 'A', 'Math', :tid)"), {"cid": class_id, "sid": school_id, "tid": teacher_id})
    db.execute(text("INSERT INTO lessons (id, school_id, class_id) VALUES (:lid, :sid, :cid)"), {"lid": lesson_id, "sid": school_id, "cid": class_id})

token = issue_token(str(school_id), str(teacher_id), "teacher")
print("✅ Demo Data Seeded!")
print(f"CLASS_ID: {class_id}")
print(f"LESSON_ID: {lesson_id}")
print(f"TOKEN: {token}")
'''

# --- 9. UPDATE PYPROJECT.TOML ---
FILES["pyproject.toml"] = '''[project]
name = "classroom-copilot-v5"
version = "5.5.0"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.115",
  "uvicorn>=0.30",
  "sqlalchemy>=2.0",
  "psycopg[binary]>=3.2",
  "alembic>=1.13",
  "pyjwt>=2.8",
  "pytest>=8.0",
  "httpx>=0.27",
  "pgvector>=0.2.5",
  "openai>=1.10",
  "streamlit>=1.31",
]

[tool.setuptools.packages.find]
include = ["app*"]
exclude = ["alembic*", "tests*"]
'''

def main():
    for relpath, content in FILES.items():
        p = ROOT / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    print("Mega-Bundle v5.5 written successfully!")

if __name__ == "__main__":
    main()