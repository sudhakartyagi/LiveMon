from pathlib import Path

ROOT = Path(".")
FILES = {}

# 1. RESTORE ENGINE
FILES["app/engine.py"] = '''from enum import IntEnum
from typing import Dict, Any

class Tier(IntEnum):
    OBSERVE = 0
    SILENT = 1
    ACT = 2
    CORRECT = 3
    ESCALATE = 4

class PolicyEngine:
    @staticmethod
    def route_action(action_type: str, context: Dict[str, Any], policy_config: dict) -> int:
        if context.get("teacher_absent_minutes", 0) > 3:
            return Tier.ESCALATE
        if context.get("safety_event"):
            return Tier.ESCALATE
        rules = policy_config.get("rules", {})
        if action_type in rules:
            return int(rules[action_type])
        defaults = {
            "timer": Tier.ACT, "recap": Tier.ACT, "common_mistake": Tier.ACT,
            "language_nudge": Tier.ACT, "factual_correction": Tier.CORRECT,
            "praise_naming": Tier.CORRECT, "individual_hint": Tier.SILENT,
            "discipline_naming": Tier.OBSERVE,
        }
        return defaults.get(action_type, Tier.OBSERVE)
'''

# 2. RESTORE AUDIO
FILES["app/audio.py"] = '''from typing import Optional
from app.engine import Tier

class AudioProcessor:
    @staticmethod
    def process_chunk(chunk: dict) -> Optional[dict]:
        transcript = chunk.get("transcript", "").lower()
        noise = chunk.get("noise_db", 0)
        if noise > 75:
            return {"action_type": "scripted_reminder", "reason": f"Ambient noise exceeded threshold ({noise}dB)", "context": {"trigger": "noise"}, "tier": Tier.ACT}
        if "1/2 is bigger than 3/4" in transcript:
            return {"action_type": "factual_correction", "reason": "Teacher stated a mathematical misconception", "context": {"trigger": "misconception"}, "tier": Tier.OBSERVE}
        return None
'''

# 3. RESTORE FULL MAIN.PY (Weeks 2 + 3 + 4)
FILES["app/main.py"] = '''import uuid
from datetime import datetime
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

# --- WEEK 2 ENDPOINTS ---
@app.post("/policies", status_code=201)
def create_policy(policy: PolicyCreate, principal=Depends(get_principal)):
    if principal.get("role") not in ["admin", "principal"]:
        raise HTTPException(403, "Only principal/admin can set policies")
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
        tier = PolicyEngine.route_action(req.action_type, req.context, config)
        action = AgentAction(school_id=uuid.UUID(principal["school_id"]), lesson_id=req.lesson_id, action_type=req.action_type, tier=tier, reason=req.reason, principal_notified=(tier == 4))
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

# --- WEEK 3 ENDPOINTS ---
@app.get("/teacher/dashboard/{lesson_id}")
def teacher_dashboard(lesson_id: uuid.UUID, principal=Depends(get_principal)):
    if principal.get("role") not in ["teacher", "principal"]: raise HTTPException(403, "Access denied")
    with tenant_session(principal["school_id"]) as db:
        actions = db.query(AgentAction).filter(AgentAction.lesson_id == lesson_id).order_by(AgentAction.created_at).all()
        return [{"id": str(a.id), "time": a.created_at.strftime("%H:%M:%S"), "action": a.action_type, "tier": a.tier, "reason": a.reason, "status": a.status} for a in actions]

@app.get("/principal/digest")
def principal_digest(date: str = None, principal=Depends(get_principal)):
    if principal.get("role") not in ["principal", "admin"]: raise HTTPException(403, "Access denied. Principal only.")
    if not date: date = datetime.utcnow().strftime("%Y-%m-%d")
    with tenant_session(principal["school_id"]) as db:
        action_items = db.query(AgentAction).filter(AgentAction.tier == 4, AgentAction.created_at >= f"{date} 00:00:00", AgentAction.created_at <= f"{date} 23:59:59").all()
        disputes = db.query(Dispute).filter(Dispute.created_at >= f"{date} 00:00:00").all()
        discipline_flags = db.query(AgentAction).filter(AgentAction.action_type == "discipline_naming", AgentAction.created_at >= f"{date} 00:00:00").all()
        return {"date": date, "action_items": [{"id": str(a.id), "type": a.action_type, "reason": a.reason, "status": a.status} for a in action_items], "disputes": [{"id": str(d.id), "reason": d.flag_reason, "resolution": d.resolution} for d in disputes], "discipline_flags": [{"id": str(a.id), "action": a.action_type, "status": a.status} for a in discipline_flags]}

@app.post("/principal/resolve/{action_id}")
def resolve_action(action_id: uuid.UUID, principal=Depends(get_principal)):
    if principal.get("role") not in ["principal", "admin"]: raise HTTPException(403, "Principal only")
    with tenant_session(principal["school_id"]) as db:
        action = db.get(AgentAction, action_id)
        if not action: raise HTTPException(404, "Action not found")
        action.status = "resolved_by_principal"
        return {"id": str(action.id), "status": action.status}

# --- WEEK 4 ENDPOINTS ---
@app.post("/audio/ingest")
def ingest_audio(chunk: AudioChunk, principal=Depends(get_principal)):
    with tenant_session(principal["school_id"]) as db:
        state = db.query(ClassState).filter(ClassState.class_id == chunk.class_id).first()
        if state and state.is_paused: return {"status": "ignored", "reason": "Agent is paused for this class"}
        result = AudioProcessor.process_chunk(chunk.dict())
        if result:
            action = AgentAction(school_id=uuid.UUID(principal["school_id"]), lesson_id=uuid.uuid4(), action_type=result["action_type"], tier=result["tier"], reason=result["reason"], status="logged" if result["tier"] == 0 else "executed")
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
'''

# 4. RESTORE TESTS (Merging Week 2, 3, and 4)
FILES["tests/test_week2.py"] = '''import uuid
import threading
from sqlalchemy import text
from app.db import tenant_session

def test_policy_engine_routing():
    from app.engine import PolicyEngine
    assert PolicyEngine.route_action("timer", {}, {}) == 2
    assert PolicyEngine.route_action("timer", {}, {"rules": {"timer": 3}}) == 3
    assert PolicyEngine.route_action("timer", {"teacher_absent_minutes": 4}, {}) == 4

def test_concurrent_isolation(two_schools):
    errors = []
    def query_school(school_id, expected_pseudonym):
        try:
            with tenant_session(school_id) as db:
                import time; time.sleep(0.1)
                result = db.execute(text("SELECT pseudonym FROM students")).fetchall()
                assert len(result) == 1
                assert result[0][0] == expected_pseudonym
        except Exception as e:
            errors.append(e)
    threads = []
    for _ in range(10):
        threads.append(threading.Thread(target=query_school, args=(two_schools["school_a"], "stuA")))
        threads.append(threading.Thread(target=query_school, args=(two_schools["school_b"], "stuB")))
    for t in threads: t.start()
    for t in threads: t.join()
    assert len(errors) == 0, f"Concurrency isolation failed: {errors}"
'''

FILES["tests/test_week3.py"] = '''import uuid
from sqlalchemy import text
from app.db import tenant_session

def auth(token):
    return {"Authorization": f"Bearer {token}"}

def test_teacher_dashboard(client, two_schools):
    lesson_id = uuid.uuid4()
    with tenant_session(two_schools["school_a"]) as db:
        db.execute(text("INSERT INTO lessons (id, school_id, class_id) VALUES (:id, :sid, :cid)"), {"id": lesson_id, "sid": two_schools["school_a"], "cid": uuid.uuid4()})
    client.post("/actions", headers=auth(two_schools["token_a"]), json={"lesson_id": str(lesson_id), "action_type": "recap", "reason": "Pacing check", "context": {}})
    r = client.get(f"/teacher/dashboard/{lesson_id}", headers=auth(two_schools["token_a"]))
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["action"] == "recap"

def test_principal_digest(client, two_schools, monkeypatch):
    monkeypatch.setattr("app.deps.get_principal", lambda authorization: {"sub": str(uuid.uuid4()), "school_id": str(two_schools["school_a"]), "role": "principal"})
    client.post("/actions", headers=auth("fake"), json={"lesson_id": str(uuid.uuid4()), "action_type": "teacher_absent", "reason": "Teacher absent > 3 min", "context": {"teacher_absent_minutes": 5}})
    r = client.get("/principal/digest", headers=auth("fake"))
    assert r.status_code == 200
    assert len(r.json()["action_items"]) >= 1
'''

FILES["tests/test_week4.py"] = '''import uuid

def auth(token):
    return {"Authorization": f"Bearer {token}"}

def test_audio_ingest_noise_trigger(client, two_schools):
    r = client.post("/audio/ingest", headers=auth(two_schools["token_a"]), json={"class_id": str(uuid.uuid4()), "transcript": "Let's move to page 42", "speaker": "teacher", "noise_db": 80})
    assert r.status_code == 200
    assert r.json()["status"] == "action_triggered"
    assert r.json()["tier"] == 2

def test_kill_switch(client, two_schools):
    class_id = uuid.uuid4()
    r = client.post(f"/agent/pause/{class_id}", headers=auth(two_schools["token_a"]))
    assert r.status_code == 200
    r = client.post("/audio/ingest", headers=auth(two_schools["token_a"]), json={"class_id": str(class_id), "transcript": "Talking", "speaker": "teacher", "noise_db": 90})
    assert r.json()["status"] == "ignored"
'''

def main():
    for relpath, content in FILES.items():
        p = ROOT / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    print("All missing files restored successfully!")

if __name__ == "__main__":
    main()