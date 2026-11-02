import httpx
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
