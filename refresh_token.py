import json
import psycopg
from app.auth import issue_token

def refresh():
    print("Refreshing your JWT token...")
    try:
        with psycopg.connect("postgresql://postgres:postgres@localhost:5432/copilot") as conn:
            with conn.cursor() as cur:
                # Get the latest school and teacher
                cur.execute("SELECT id FROM schools ORDER BY created_at DESC LIMIT 1")
                school_id = str(cur.fetchone()[0])
                
                cur.execute("SELECT id FROM teachers WHERE school_id = %s LIMIT 1", (school_id,))
                teacher_id = str(cur.fetchone()[0])
                
                # Issue new token
                new_token = issue_token(school_id, teacher_id, "teacher")
                
                # Update config.json
                with open("config.json", "r") as f:
                    config = json.load(f)
                
                config["token"] = new_token
                
                with open("config.json", "w") as f:
                    json.dump(config, f)
                    
                print("✅ Token refreshed and saved to config.json!")
                
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    refresh()