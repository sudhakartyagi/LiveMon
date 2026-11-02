from app.db import tenant_session
from app.auth import issue_token
from sqlalchemy import text

# Fetch the demo school and teacher we created earlier
with tenant_session("00000000-0000-0000-0000-000000000000") as db:
    school = db.execute(text("SELECT id FROM schools LIMIT 1")).fetchone()
    teacher = db.execute(text("SELECT id FROM teachers LIMIT 1")).fetchone()

if school and teacher:
    token = issue_token(str(school[0]), str(teacher[0]), "teacher")
    print("\nCopy this TOKEN:\n")
    print(token)
    print("\n")
else:
    print("No demo data found. Run `python seed_demo.py` first.")