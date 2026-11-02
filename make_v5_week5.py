#!/usr/bin/env python3
"""
Generate Week 5: Naming & Discipline Engine, Pattern Detection.
Run: python make_v5_week5.py
"""
from pathlib import Path
import zipfile

ROOT = Path(".")
FILES = {}

# --- SCHEMAS (Add target_student_id) ---
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
    target_student_id: Optional[UUID] = None # Required for naming actions
    context: Dict[str, Any] = Field(default_factory=dict)

class DisputeRequest(BaseModel):
    flag_reason: str

class AudioChunk(BaseModel):
    class_id: UUID
    lesson_id: UUID
    transcript: str
    speaker: str
    noise_db: int
'''

# --- MAIN APP (Add Naming Logic & Pattern Detection) ---
FILES["app/main.py"] = '''import uuid
from datetime import datetime, timezone, time, timedelta
from fastapi import FastAPI, Depends, HTTPException
from app.db import tenant_session
from app.deps import get_principal
from app.models import Student, AgentAction, Policy, AuditLog, Dispute, Lesson, ClassState
from app.schemas import PolicyCreate, ActionRequest, DisputeRequest, AudioChunk
from app.engine import PolicyEngine
from app.audio import AudioProcessor

app = FastAPI(title="Classroom Agent v5.0 (Week 5)")

@app.get("/health")
def health():
    return {"status": "ok", "version": "5.0.0-week5"}

@app.get("/students/{student_id}")
def get_student(student_id: uuid.UUID, principal=Depends(get_principal)):
    with tenant_session(principal["school_id"]) as db:
        student = db.get(Student, student_id)
        if student is None: raise HTTPException(404, "Not found")
        return {"id": str(student.id), "pseudonym": student.pseudonym}

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
        
        # --- WEEK 5 LOGIC: NAMING RULES ---
        if req.action_type in ["praise_naming", "discipline_naming"]:
            if not req.target_student_id:
                raise HTTPException(400, f"{req.action_type} requires target_student_id")
            
            # 1. Praise Naming requires opt-in
            if req.action_type == "praise_naming" and not config.get("allow_praise_naming", False):
                raise HTTPException(403, "Praise naming is disabled by school policy")
                
            # 2. Discipline Naming: Check for patterns (>= 3 incidents in last 30 days)
            if req.action_type == "discipline_naming":
                thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
                recent_incidents = db.query(AgentAction).filter(
                    AgentAction.action_type == "discipline_naming",
                    AgentAction.target_id == str(req.target_student_id),
                    AgentAction.created_at >= thirty_days_ago
                ).count()
                
                if recent_incidents >= 2: # The current one will be the 3rd
                    # Escalate to Tier 4 Pattern Report
                    action = AgentAction(
                        school_id=uuid.UUID(principal["school_id"]),
                        lesson_id=req.lesson_id,
                        action_type="pattern_report",
                        tier=4, # Escalated to Principal
                        reason=f"Student {req.target_student_id} flagged for discipline 3 times in 30 days.",
                        target_type="student",
                        target_id=str(req.target_student_id),
                        principal_notified=True
                    )
                    db.add(action)
                    db.flush()
                    return {"id": str(action.id), "tier": 4, "requires_principal": True, "note": "Pattern threshold reached"}

        # Standard Routing
        tier = PolicyEngine.route_action(req.action_type, req.context, config)
        
        action = AgentAction(
            school_id=uuid.UUID(principal["school_id"]),
            lesson_id=req.lesson_id,
            action_type=req.action_type,
            tier=tier,
            reason=req.reason,
            target_type="student" if req.target_student_id else None,
            target_id=str(req.target_student_id) if req.target_student_id else None,
            principal_notified=(tier == 4)
        )
        db.add(action)
        db.flush()
        return {"id": str(action.id), "tier": tier, "requires_principal": (tier == 4)}

# --- REMAINING ENDPOINTS (Dashboard, Digest, Audio, Kill Switch) ---
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
        # Digest only shows discipline flags, not praise
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
        result = AudioProcessor.process_chunk(chunk.model_dump())
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

# --- TESTS ---
FILES["tests/test_week5.py"] = '''import uuid
from sqlalchemy import text
from app.db import tenant_session

def auth(token):
    return {"Authorization": f"Bearer {token}"}

def test_praise_naming_disabled_by_default(client, two_schools):
    lesson_id = uuid.uuid4()
    with tenant_session(two_schools["school_a"]) as db:
        db.execute(text("INSERT INTO lessons (id, school_id, class_id) VALUES (:id, :sid, :cid)"), {"id": lesson_id, "sid": two_schools["school_a"], "cid": two_schools["class_a"]})
    
    # Try to praise name without policy opt-in
    r = client.post("/actions", headers=auth(two_schools["token_a"]), json={
        "lesson_id": str(lesson_id),
        "action_type": "praise_naming",
        "reason": "Good job",
        "target_student_id": str(two_schools["student_a"]),
        "context": {}
    })
    assert r.status_code == 403
    assert "disabled by school policy" in r.json()["detail"]

def test_praise_naming_enabled_by_policy(client, two_schools):
    lesson_id = uuid.uuid4()
    with tenant_session(two_schools["school_a"]) as db:
        db.execute(text("INSERT INTO lessons (id, school_id, class_id) VALUES (:id, :sid, :cid)"), {"id": lesson_id, "sid": two_schools["school_a"], "cid": two_schools["class_a"]})
    
    # Create policy enabling praise naming (Requires mocking principal role since token_a is a teacher)
    from app.deps import get_principal
    from app.main import app
    app.dependency_overrides[get_principal] = lambda: {"sub": str(uuid.uuid4()), "school_id": str(two_schools["school_a"]), "role": "principal"}
    
    client.post("/policies", headers=auth("fake"), json={
        "name": "Opt-in Policy",
        "config": {"allow_praise_naming": True}
    })
    
    # Now try as teacher
    app.dependency_overrides.clear()
    r = client.post("/actions", headers=auth(two_schools["token_a"]), json={
        "lesson_id": str(lesson_id),
        "action_type": "praise_naming",
        "reason": "Great work",
        "target_student_id": str(two_schools["student_a"]),
        "context": {}
    })
    assert r.status_code == 201
    assert r.json()["tier"] == 3 # Praise goes to digest (Tier 3)

def test_discipline_pattern_report(client, two_schools):
    lesson_id = uuid.uuid4()
    with tenant_session(two_schools["school_a"]) as db:
        db.execute(text("INSERT INTO lessons (id, school_id, class_id) VALUES (:id, :sid, :cid)"), {"id": lesson_id, "sid": two_schools["school_a"], "cid": two_schools["class_a"]})

    # 1st Incident
    r1 = client.post("/actions", headers=auth(two_schools["token_a"]), json={
        "lesson_id": str(lesson_id), "action_type": "discipline_naming", "reason": "Talking",
        "target_student_id": str(two_schools["student_a"]), "context": {}
    })
    assert r1.json()["tier"] == 0 # Default is log only (Tier 0)

    # 2nd Incident
    client.post("/actions", headers=auth(two_schools["token_a"]), json={
        "lesson_id": str(lesson_id), "action_type": "discipline_naming", "reason": "Talking again",
        "target_student_id": str(two_schools["student_a"]), "context": {}
    })

    # 3rd Incident -> Should trigger Tier 4 Pattern Report
    r3 = client.post("/actions", headers=auth(two_schools["token_a"]), json={
        "lesson_id": str(lesson_id), "action_type": "discipline_naming", "reason": "Still talking",
        "target_student_id": str(two_schools["student_a"]), "context": {}
    })
    assert r3.json()["tier"] == 4
    assert r3.json()["requires_principal"] is True
    assert "Pattern threshold reached" in r3.json()["note"]
'''

def main():
    for relpath, content in FILES.items():
        p = ROOT / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    print("Week 5 files written successfully!")

if __name__ == "__main__":
    main()