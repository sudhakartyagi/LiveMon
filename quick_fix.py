import json
from app.db import tenant_session
from app.auth import issue_token
from sqlalchemy import text
import uuid

print("Connecting...")
try:
    # We use a fake school ID just to bypass RLS, then query the real school
    with tenant_session("00000000-0000-0000-0000-000000000000") as db:
        # RLS will block this unless we are superuser, so we use a raw connection
        pass
except:
    pass

# Use a direct psycopg connection as superuser (bypasses RLS safely for this script)
import psycopg
try:
    print("Fetching school and teacher...")
    with psycopg.connect("postgresql://postgres:postgres@localhost:5432/copilot") as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM schools LIMIT 1")
            school = cur.fetchone()
            if not school:
                print("❌ No school found. Run `python seed_demo.py` first.")
                exit()
            
            school_id = str(school[0])
            cur.execute("SELECT id FROM teachers WHERE school_id = %s LIMIT 1", (school_id,))
            teacher = cur.fetchone()
            teacher_id = str(teacher[0])

            # Generate token
            token = issue_token(school_id, teacher_id, "teacher")

            # Update config.json
            with open("config.json", "r") as f:
                config = json.load(f)
            config["token"] = token
            with open("config.json", "w") as f:
                json.dump(config, f)
            
            print("✅ TOKEN UPDATED SUCCESSFULLY in config.json!")
            
except Exception as e:
    print(f"❌ Error: {e}")