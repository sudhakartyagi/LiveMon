#!/usr/bin/env python3
"""
v5.6 Mega Update: UI Feedback, Mic Streaming, Offline AI.
Run: python make_v5_mega2.py
"""
from pathlib import Path

ROOT = Path(".")
FILES = {}

# --- 1. UPDATE BRAIN (Ollama Integration) ---
FILES["app/brain.py"] = '''import os
import httpx
from sqlalchemy import text
from app.db import tenant_session

class AIBrain:
    @staticmethod
    def get_embedding(text: str) -> list:
        if not os.getenv("OPENAI_API_KEY") and not os.getenv("OLLAMA_HOST"):
            return [float(hash(text + str(i)) % 100) / 100.0 for i in range(1536)]
        elif os.getenv("OLLAMA_HOST"):
            # Ollama local embeddings
            try:
                import ollama
                response = ollama.embeddings(model='nomic-embed-text', prompt=text)
                return response['embedding']
            except Exception:
                return [0.0] * 1536
        else:
            from openai import OpenAI
            client = OpenAI()
            response = client.embeddings.create(input=text, model="text-embedding-3-small")
            return response.data[0].embedding

    @staticmethod
    def analyze_misconception(transcript: str, school_id: str) -> str:
        query_vector = AIBrain.get_embedding(transcript)
        context = ""
        with tenant_session(school_id) as db:
            results = db.execute(
                text("SELECT content FROM curriculum_docs ORDER BY embedding <=> :vec LIMIT 1"),
                {"vec": str(query_vector)}
            ).fetchone()
            if results:
                context = results[0]

        prompt = f"You are an AI teaching assistant. The teacher just said: '{transcript}'. Curriculum context: {context}. If the teacher made a factual error, provide a 1-sentence polite interjection. If no error, say 'None'."

        # 1. Ollama (Local & Free)
        if os.getenv("OLLAMA_HOST"):
            try:
                import ollama
                response = ollama.chat(model='llama3', messages=[{'role': 'user', 'content': prompt}])
                return response['message']['content']
            except Exception as e:
                print("Ollama failed, falling back...", e)

        # 2. OpenAI
        if os.getenv("OPENAI_API_KEY"):
            from openai import OpenAI
            client = OpenAI()
            response = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}])
            return response.choices[0].message.content

        # 3. Mock fallback
        return f"[Mock AI] Let me clarify that using the curriculum: {context}."
'''

# --- 2. UPDATE MAIN (Add Rate Endpoint for UI) ---
FILES["app/main.py"] = '''import uuid
from datetime import datetime, timezone, time, timedelta
from fastapi import FastAPI, Depends, HTTPException
from app.db import tenant_session
from app.deps import get_principal
from app.models import Student, AgentAction, Policy, AuditLog, Dispute, Lesson, ClassState, CurriculumDoc
from app.schemas import PolicyCreate, ActionRequest, DisputeRequest, AudioChunk, CurriculumUpload, RateRequest
from app.engine import PolicyEngine
from app.audio import AudioProcessor
from app.brain import AIBrain

app = FastAPI(title="Classroom Agent v5.6 (Voice + Offline AI)")

@app.get("/health")
def health():
    return {"status": "ok", "version": "5.6.0"}

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

@app.post("/actions/{action_id}/rate")
def rate_action(action_id: uuid.UUID, req: RateRequest, principal=Depends(get_principal)):
    with tenant_session(principal["school_id"]) as db:
        action = db.get(AgentAction, action_id)
        if not action: raise HTTPException(404, "Action not found")
        action.status = f"rated_{req.rating}"
        return {"status": "success", "action_status": action.status}

@app.get("/teacher/dashboard/{lesson_id}")
def teacher_dashboard(lesson_id: uuid.UUID, principal=Depends(get_principal)):
    with tenant_session(principal["school_id"]) as db:
        actions = db.query(AgentAction).filter(AgentAction.lesson_id == lesson_id).order_by(AgentAction.created_at.desc()).all()
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

@app.post("/audio/ingest")
def ingest_audio(chunk: AudioChunk, principal=Depends(get_principal)):
    with tenant_session(principal["school_id"]) as db:
        state = db.query(ClassState).filter(ClassState.class_id == chunk.class_id).first()
        if state and state.is_paused: return {"status": "ignored", "reason": "Agent is paused"}
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

# --- 3. UPDATE SCHEMAS (Add RateRequest) ---
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

class RateRequest(BaseModel):
    rating: str # "good", "bad"

class AudioChunk(BaseModel):
    class_id: UUID
    lesson_id: UUID
    transcript: str
    speaker: str
    noise_db: int

class CurriculumUpload(BaseModel):
    content: str
'''

# --- 4. UPDATE STREAMLIT UI (Add Feedback Buttons) ---
FILES["ui/app.py"] = '''import streamlit as st
import httpx
import uuid

API_URL = "http://localhost:8000"
st.set_page_config(page_title="Classroom Agent v5.6", layout="wide")
st.title("🤖 Classroom Agent v5.6")

st.sidebar.header("Authentication")
token = st.sidebar.text_input("Paste JWT Token here", type="password")
if not token: st.stop()
HEADERS = {"Authorization": f"Bearer {token}"}

tab1, tab2, tab3 = st.tabs(["Teacher View", "Principal Digest", "Curriculum Upload"])

with tab1:
    st.header("Teacher Live Dashboard")
    class_id = st.text_input("Class ID", value="e7061104-7c79-46b6-84c1-bad640d12761")
    lesson_id = st.text_input("Lesson ID", value="b89639f4-0fef-46e4-8740-5f501e63d62d")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🚨 Pause Agent (Kill Switch)"):
            httpx.post(f"{API_URL}/agent/pause/{class_id}", headers=HEADERS)
            st.success("Paused")
    with col2:
        if st.button("▶️ Resume Agent"):
            httpx.post(f"{API_URL}/agent/resume/{class_id}", headers=HEADERS)
            st.success("Resumed")

    st.subheader("Simulate Live Audio")
    transcript = st.text_area("Teacher Transcript", value="1/2 is bigger than 3/4")
    noise_db = st.slider("Noise Level (dB)", 0, 100, 80)
    
    if st.button("🎤 Send Audio Chunk"):
        r = httpx.post(f"{API_URL}/audio/ingest", headers=HEADERS, json={
            "class_id": class_id, "lesson_id": lesson_id,
            "transcript": transcript, "speaker": "teacher", "noise_db": noise_db
        })
        st.json(r.json())
            
    st.subheader("Live Timeline & Feedback")
    if st.button("Refresh Timeline"):
        r = httpx.get(f"{API_URL}/teacher/dashboard/{lesson_id}", headers=HEADERS)
        if r.status_code == 200:
            actions = r.json()
            for a in actions:
                with st.expander(f"[{a['time']}] {a['action']} (Tier {a['tier']})"):
                    st.write(f"**Reason:** {a['reason']}")
                    st.write(f"**Status:** {a['status']}")
                    
                    # Feedback buttons
                    c1, c2, c3 = st.columns(3)
                    if c1.button("✅ Accept", key=f"acc_{a['id']}"):
                        httpx.post(f"{API_URL}/actions/{a['id']}/rate", headers=HEADERS, json={"rating": "good"})
                        st.success("Rated Good!")
                    if c2.button("❌ Reject", key=f"rej_{a['id']}"):
                        httpx.post(f"{API_URL}/actions/{a['id']}/rate", headers=HEADERS, json={"rating": "bad"})
                        st.warning("Rated Bad!")
                    if c3.button("🚩 Flag", key=f"flg_{a['id']}"):
                        httpx.post(f"{API_URL}/actions/{a['id']}/flag", headers=HEADERS, json={"flag_reason": "Teacher disagreed"})
                        st.error("Flagged to Principal")

with tab2:
    st.header("Principal After-Class Digest")
    if st.button("Load Today's Digest"):
        r = httpx.get(f"{API_URL}/principal/digest", headers=HEADERS)
        if r.status_code == 200:
            data = r.json()
            st.subheader("Action Items (Tier 4)")
            st.table(data.get("action_items", []))
            st.subheader("Disputes")
            st.table(data.get("disputes", []))
            st.subheader("Discipline Logs")
            st.table(data.get("discipline_flags", []))

with tab3:
    st.header("Curriculum Grounding (RAG)")
    curriculum_text = st.text_area("Paste NCERT Chapter Text", height=200)
    if st.button("Upload to Vector DB"):
        r = httpx.post(f"{API_URL}/curriculum/upload", headers=HEADERS, json={"content": curriculum_text})
        if r.status_code == 200: st.success(r.json())
'''

# --- 5. CREATE MIC LISTENER SCRIPT ---
FILES["mic_listener.py"] = '''import speech_recognition as sr
import httpx
import time

API_URL = "http://localhost:8000"
TOKEN = input("Paste your JWT Token: ")
CLASS_ID = input("Paste your Class ID: ")
LESSON_ID = input("Paste your Lesson ID: ")

HEADERS = {"Authorization": f"Bearer {TOKEN}"}
r = sr.Recognizer()

print("\\n🎤 Microphone Active. Speak into your mic...")
while True:
    try:
        with sr.Microphone() as source:
            r.adjust_for_ambient_noise(source, duration=1)
            print("Listening...")
            audio = r.listen(source, timeout=5, phrase_time_limit=5)
            
            print("Transcribing...")
            # Using Google's free speech recognition
            transcript = r.recognize_google(audio)
            print(f"Teacher said: {transcript}")
            
            # Mocking noise level based on audio length or random for demo
            noise_db = 40 if len(transcript) > 10 else 80
            
            # Send to API
            response = httpx.post(f"{API_URL}/audio/ingest", headers=HEADERS, json={
                "class_id": CLASS_ID,
                "lesson_id": LESSON_ID,
                "transcript": transcript,
                "speaker": "teacher",
                "noise_db": noise_db
            })
            print(f"API Response: {response.json()}\\n")
            
    except sr.WaitTimeoutError:
        pass # No speech detected
    except sr.UnknownValueError:
        print("Could not understand audio")
    except Exception as e:
        print(f"Error: {e}")
'''

def main():
    for relpath, content in FILES.items():
        p = ROOT / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    print("v5.6 Mega Update written successfully!")

if __name__ == "__main__":
    main()