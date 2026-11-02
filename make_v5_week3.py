#!/usr/bin/env python3
"""
Generate Week 3: Teacher Dashboard, Principal Digest, and Resolution API.
Run: python make_v5_week3.py
"""
from pathlib import Path
import zipfile

ROOT = Path("classroom_copilot_v5")
FILES = {}

# --- MAIN APP ---
FILES["app/main.py"] = '''import uuid
from datetime import datetime, timedelta
from fastapi import FastAPI, Depends, HTTPException, Query
from app.db import tenant_session
from app.deps import get_principal
from app.models import Student, AgentAction, Policy, AuditLog, Dispute, Lesson
from app.schemas import PolicyCreate, ActionRequest, DisputeRequest
from app.engine import PolicyEngine

app = FastAPI(title="Classroom Agent v5.0 (Week 3)")

@app.get("/health")
def health():
    return {"status": "ok", "version": "5.0.0-week3"}

@app.get("/students/{student_id}")
def get_student(student_id: uuid.UUID, principal=Depends(get_principal)):
    with tenant_session(principal["school_id"]) as db:
        student = db.get(Student, student_id)
        if student is None:
            raise HTTPException(404, "Not found")
        return {"id": str(student.id), "pseudonym": student.pseudonym}

@app.post("/policies", status_code=201)
def create_policy(policy: PolicyCreate, principal=Depends(get_principal)):
    if principal.get("role") not in ["admin", "principal"]:
        raise HTTPException(403, "Only principal/admin can set policies")
    with tenant_session(principal["school_id"]) as db:
        new_policy = Policy(
            school_id=uuid.UUID(principal["school_id"]),
            name=policy.name,
            config=policy.config
        )
        db.add(new_policy)
        db.flush()
        return {"id": str(new_policy.id)}

@app.post("/actions", status_code=201)
def trigger_action(req: ActionRequest, principal=Depends(get_principal)):
    with tenant_session(principal["school_id"]) as db:
        policy = db.query(Policy).order_by(Policy.created_at.desc()).first()
        config = policy.config if policy else {}

        tier = PolicyEngine.route_action(req.action_type, req.context, config)

        action = AgentAction(
            school_id=uuid.UUID(principal["school_id"]),
            lesson_id=req.lesson_id,
            action_type=req.action_type,
            tier=tier,
            reason=req.reason,
            principal_notified=(tier == 4)
        )
        db.add(action)
        db.flush()

        return {"id": str(action.id), "tier": tier, "requires_principal": (tier == 4)}

@app.post("/actions/{action_id}/flag", status_code=201)
def flag_action(action_id: uuid.UUID, req: DisputeRequest, principal=Depends(get_principal)):
    with tenant_session(principal["school_id"]) as db:
        action = db.get(AgentAction, action_id)
        if not action:
            raise HTTPException(404, "Action not found")

        dispute = Dispute(
            school_id=uuid.UUID(principal["school_id"]),
            agent_action_id=action.id,
            teacher_id=uuid.UUID(principal["sub"]),
            flag_reason=req.flag_reason,
            resolution="agent_wrong" if action.tier >= 3 else "agent_right"
        )
        db.add(dispute)
        action.status = "flagged"
        return {"dispute_id": str(dispute.id), "resolution": dispute.resolution}

# --- NEW WEEK 3 ENDPOINTS ---

@app.get("/teacher/dashboard/{lesson_id}")
def teacher_dashboard(lesson_id: uuid.UUID, principal=Depends(get_principal)):
    """Teacher sees exactly what the agent did during their lesson."""
    if principal.get("role") not in ["teacher", "principal"]:
        raise HTTPException(403, "Access denied")
    
    with tenant_session(principal["school_id"]) as db:
        actions = db.query(AgentAction).filter(AgentAction.lesson_id == lesson_id).order_by(AgentAction.created_at).all()
        return [
            {
                "id": str(a.id),
                "time": a.created_at.strftime("%H:%M:%S"),
                "action": a.action_type,
                "tier": a.tier,
                "reason": a.reason,
                "status": a.status
            } for a in actions
        ]

@app.get("/principal/digest")
def principal_digest(date: str = None, principal=Depends(get_principal)):
    """
    Principal sees the after-class digest. Highlights Tier 4 (Live Push), 
    Disputes, and Discipline flags.
    """
    if principal.get("role") not in ["principal", "admin"]:
        raise HTTPException(403, "Access denied. Principal only.")

    if not date:
        date = datetime.utcnow().strftime("%Y-%m-%d")

    with tenant_session(principal["school_id"]) as db:
        # 1. Action Items (Tier 4)
        action_items = db.query(AgentAction).filter(
            AgentAction.tier == 4,
            AgentAction.created_at >= f"{date} 00:00:00",
            AgentAction.created_at <= f"{date} 23:59:59"
        ).all()

        # 2. Disputes
        disputes = db.query(Dispute).filter(
            Dispute.created_at >= f"{date} 00:00:00"
        ).all()

        # 3. Discipline Naming Flags (Tier 3 or specific action type)
        discipline_flags = db.query(AgentAction).filter(
            AgentAction.action_type == "discipline_naming",
            AgentAction.created_at >= f"{date} 00:00:00"
        ).all()

        return {
            "date": date,
            "action_items": [
                {"id": str(a.id), "type": a.action_type, "reason": a.reason, "status": a.status} 
                for a in action_items
            ],
            "disputes": [
                {"id": str(d.id), "reason": d.flag_reason, "resolution": d.resolution}
                for d in disputes
            ],
            "discipline_flags": [
                {"id": str(a.id), "action": a.action_type, "status": a.status}
                for a in discipline_flags
            ]
        }

@app.post("/principal/resolve/{action_id}")
def resolve_action(action_id: uuid.UUID, principal=Depends(get_principal)):
    """Principal acknowledges or closes a Tier 4 Action Item."""
    if principal.get("role") not in ["principal", "admin"]:
        raise HTTPException(403, "Principal only")

    with tenant_session(principal["school_id"]) as db:
        action = db.get(AgentAction, action_id)
        if not action:
            raise HTTPException(404, "Action not found")
        
        action.status = "resolved_by_principal"
        return {"id": str(action.id), "status": action.status}
'''

# --- TESTS ---
FILES["tests/test_week3.py"] = '''import uuid
from sqlalchemy import text
from app.main import app
from app.db import tenant_session

def auth(token):
    return {"Authorization": f"Bearer {token}"}

def test_teacher_dashboard(client, two_schools):
    # Setup: Create a lesson and an action
    lesson_id = uuid.uuid4()
    with tenant_session(two_schools["school_a"]) as db:
        db.execute(text("INSERT INTO lessons (id, school_id, class_id) VALUES (:id, :sid, :cid)"), 
                   {"id": lesson_id, "sid": two_schools["school_a"], "cid": uuid.uuid4()})
    
    client.post("/actions", headers=auth(two_schools["token_a"]), json={
        "lesson_id": str(lesson_id),
        "action_type": "recap",
        "reason": "Pacing check",
        "context": {}
    })

    # Teacher fetches dashboard
    r = client.get(f"/teacher/dashboard/{lesson_id}", headers=auth(two_schools["token_a"]))
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["action"] == "recap"

def test_principal_digest(client, two_schools, monkeypatch):
    # Mock the token to have role="principal"
    monkeypatch.setattr("app.deps.get_principal", lambda authorization: {
        "sub": str(uuid.uuid4()),
        "school_id": str(two_schools["school_a"]),
        "role": "principal"
    })

    # Create a Tier 4 action (teacher absent)
    client.post("/actions", headers=auth("fake"), json={
        "lesson_id": str(uuid.uuid4()),
        "action_type": "teacher_absent",
        "reason": "Teacher absent > 3 min",
        "context": {"teacher_absent_minutes": 5}
    })

    r = client.get("/principal/digest", headers=auth("fake"))
    assert r.status_code == 200
    assert len(r.json()["action_items"]) >= 1

def test_principal_cannot_see_other_school_digest(client, two_schools, monkeypatch):
    monkeypatch.setattr("app.deps.get_principal", lambda authorization: {
        "sub": str(uuid.uuid4()),
        "school_id": str(two_schools["school_b"]),
        "role": "principal"
    })

    # School B principal tries to view digest. Should be empty.
    r = client.get("/principal/digest", headers=auth("fake"))
    assert r.status_code == 200
    assert len(r.json()["action_items"]) == 0
    assert len(r.json()["disputes"]) == 0
'''

FILES["README.md"] = '''# Classroom Agent v5.0 — Week 3

Week 3 adds the Teacher Dashboard, Principal Digest, and Action Resolution.

## Run
1. `python -m pytest -v`

## New Features
- **Teacher Dashboard**: `/teacher/dashboard/{lesson_id}` shows the teacher a timeline of what the agent did.
- **Principal Digest**: `/principal/digest` aggregates Tier 4 alerts, Disputes, and Discipline flags for a specific date.
- **Resolution**: `/principal/resolve/{action_id}` allows the principal to close out Action Items.
- **Strict Role Isolation**: Teachers cannot access the Principal Digest, and Principals cannot see other schools' data.
'''

def main():
    ROOT.mkdir(exist_ok=True)
    for relpath, content in FILES.items():
        p = ROOT / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    zip_path = Path("classroom_copilot_v5_week3.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in ROOT.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(ROOT.parent))

    print(f"Created {zip_path.resolve()} ({zip_path.stat().st_size} bytes)")
    print(f"Files written: {len(FILES)}")
    for p in sorted(FILES):
        print(f"  {p}")

if __name__ == "__main__":
    main()