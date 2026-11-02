from pathlib import Path
import shutil
import zipfile

# Set ROOT to the current directory, not a nested folder
ROOT = Path(".")
FILES = {}

FILES["alembic/versions/0003_week4.py"] = '''"""Week 4: Audio State & Kill Switch"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"

def upgrade():
    op.create_table(
        "class_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("school_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("class_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("classes.id"), nullable=False),
        sa.Column("is_paused", sa.Boolean, server_default="false"),
        sa.Column("paused_at", sa.DateTime, nullable=True),
    )
    op.execute("ALTER TABLE class_states ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE class_states FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON class_states
        USING (school_id = current_setting('app.current_tenant_id', true)::uuid)
        WITH CHECK (school_id = current_setting('app.current_tenant_id', true)::uuid)
    """)
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON class_states TO app_user")

def downgrade():
    op.execute("DROP TABLE IF EXISTS class_states CASCADE")
'''

FILES["app/audio.py"] = '''from typing import Dict, Any, Optional
from app.engine import PolicyEngine, Tier
import uuid

class AudioProcessor:
    @staticmethod
    def process_chunk(chunk: dict) -> Optional[dict]:
        transcript = chunk.get("transcript", "").lower()
        noise = chunk.get("noise_db", 0)
        
        if noise > 75:
            return {
                "action_type": "scripted_reminder",
                "reason": f"Ambient noise exceeded threshold ({noise}dB)",
                "context": {"trigger": "noise"},
                "tier": Tier.ACT
            }
        if "1/2 is bigger than 3/4" in transcript:
            return {
                "action_type": "factual_correction",
                "reason": "Teacher stated a mathematical misconception",
                "context": {"trigger": "misconception"},
                "tier": Tier.OBSERVE 
            }
        return None
'''

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
    context: Dict[str, Any] = Field(default_factory=dict)

class DisputeRequest(BaseModel):
    flag_reason: str

class AudioChunk(BaseModel):
    class_id: UUID
    transcript: str
    speaker: str
    noise_db: int
'''

FILES["app/main.py"] = '''import uuid
from datetime import datetime, timedelta
from fastapi import FastAPI, Depends, HTTPException
from app.db import tenant_session
from app.deps import get_principal
from app.models import Student, AgentAction, Policy, AuditLog, Dispute, Lesson, ClassState
from app.schemas import PolicyCreate, ActionRequest, DisputeRequest, AudioChunk
from app.engine import PolicyEngine
from app.audio import AudioProcessor

app = FastAPI(title="Classroom Agent v5.0 (Week 4)")

@app.get("/health")
def health():
    return {"status": "ok", "version": "5.0.0-week4"}

@app.post("/audio/ingest")
def ingest_audio(chunk: AudioChunk, principal=Depends(get_principal)):
    with tenant_session(principal["school_id"]) as db:
        state = db.query(ClassState).filter(ClassState.class_id == chunk.class_id).first()
        if state and state.is_paused:
            return {"status": "ignored", "reason": "Agent is paused for this class"}

        result = AudioProcessor.process_chunk(chunk.dict())
        if result:
            action = AgentAction(
                school_id=uuid.UUID(principal["school_id"]),
                lesson_id=uuid.uuid4(),
                action_type=result["action_type"],
                tier=result["tier"],
                reason=result["reason"],
                status="logged" if result["tier"] == 0 else "executed"
            )
            db.add(action)
            db.flush()
            return {"status": "action_triggered", "action_id": str(action.id), "tier": result["tier"], "reason": result["reason"]}
        return {"status": "processed", "action": None}

@app.post("/agent/pause/{class_id}")
def pause_agent(class_id: uuid.UUID, principal=Depends(get_principal)):
    with tenant_session(principal["school_id"]) as db:
        state = db.query(ClassState).filter(ClassState.class_id == class_id).first()
        if not state:
            state = ClassState(school_id=uuid.UUID(principal["school_id"]), class_id=class_id, is_paused=True, paused_at=datetime.utcnow())
            db.add(state)
        else:
            state.is_paused = True
            state.paused_at = datetime.utcnow()
        return {"status": "paused", "class_id": str(class_id)}

@app.post("/agent/resume/{class_id}")
def resume_agent(class_id: uuid.UUID, principal=Depends(get_principal)):
    with tenant_session(principal["school_id"]) as db:
        state = db.query(ClassState).filter(ClassState.class_id == class_id).first()
        if state:
            state.is_paused = False
            state.paused_at = None
        return {"status": "resumed", "class_id": str(class_id)}

@app.post("/policies", status_code=201)
def create_policy(policy: PolicyCreate, principal=Depends(get_principal)):
    if principal.get("role") not in ["admin", "principal"]:
        raise HTTPException(403, "Only principal/admin can set policies")
    with tenant_session(principal["school_id"]) as db:
        new_policy = Policy(school_id=uuid.UUID(principal["school_id"]), name=policy.name, config=policy.config)
        db.add(new_policy)
        db.flush()
        return {"id": str(new_policy.id)}
'''

FILES["tests/test_week4.py"] = '''import uuid
from sqlalchemy import text
from app.main import app
from app.db import tenant_session

def auth(token):
    return {"Authorization": f"Bearer {token}"}

def test_audio_ingest_noise_trigger(client, two_schools):
    r = client.post("/audio/ingest", headers=auth(two_schools["token_a"]), json={
        "class_id": str(uuid.uuid4()),
        "transcript": "Let's move to page 42",
        "speaker": "teacher",
        "noise_db": 80
    })
    assert r.status_code == 200
    assert r.json()["status"] == "action_triggered"
    assert r.json()["tier"] == 2

def test_audio_ingest_clean_audio(client, two_schools):
    r = client.post("/audio/ingest", headers=auth(two_schools["token_a"]), json={
        "class_id": str(uuid.uuid4()),
        "transcript": "Let's move to page 42",
        "speaker": "teacher",
        "noise_db": 40
    })
    assert r.status_code == 200
    assert r.json()["status"] == "processed"

def test_kill_switch(client, two_schools):
    class_id = uuid.uuid4()
    r = client.post(f"/agent/pause/{class_id}", headers=auth(two_schools["token_a"]))
    assert r.status_code == 200

    r = client.post("/audio/ingest", headers=auth(two_schools["token_a"]), json={
        "class_id": str(class_id), "transcript": "Talking", "speaker": "teacher", "noise_db": 90
    })
    assert r.json()["status"] == "ignored"

    client.post(f"/agent/resume/{class_id}", headers=auth(two_schools["token_a"]))
    r = client.post("/audio/ingest", headers=auth(two_schools["token_a"]), json={
        "class_id": str(class_id), "transcript": "Talking", "speaker": "teacher", "noise_db": 90
    })
    assert r.json()["status"] == "action_triggered"
'''

def main():
    # Clean up the nested folder if it exists
    nested = Path("classroom_copilot_v5")
    if nested.exists() and nested.is_dir():
        print("Cleaning up nested folder...")
        shutil.rmtree(nested)

    for relpath, content in FILES.items():
        p = ROOT / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    # Patch models.py
    models_path = ROOT / "app" / "models.py"
    if models_path.exists():
        content = models_path.read_text(encoding="utf-8")
        if "class ClassState" not in content:
            content += "\n\nclass ClassState(Base):\n    __tablename__ = 'class_states'\n    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)\n    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('schools.id'), nullable=False)\n    class_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('classes.id'), nullable=False)\n    is_paused: Mapped[bool] = mapped_column(Boolean, default=False)\n    paused_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)\n"
            models_path.write_text(content, encoding="utf-8")

    print("Fixed Week 4 files written successfully!")

if __name__ == "__main__":
    main()