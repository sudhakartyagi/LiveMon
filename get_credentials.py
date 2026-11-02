import psycopg
from app.auth import issue_token

def get_latest_credentials():
    print("Fetching your classroom details...\n")
    try:
        # Connect as superuser to bypass RLS and get the latest data
        with psycopg.connect("postgresql://postgres:postgres@localhost:5432/copilot") as conn:
            with conn.cursor() as cur:
                # Get School
                cur.execute("SELECT id FROM schools ORDER BY created_at DESC LIMIT 1")
                school = cur.fetchone()
                if not school:
                    print("❌ No school found. Please run `python seed_demo.py` first.")
                    return
                school_id = str(school[0])
                
                # Get Teacher
                cur.execute("SELECT id FROM teachers WHERE school_id = %s LIMIT 1", (school_id,))
                teacher = cur.fetchone()
                teacher_id = str(teacher[0])

                # Get Class
                cur.execute("SELECT id FROM classes WHERE school_id = %s LIMIT 1", (school_id,))
                cls = cur.fetchone()
                class_id = str(cls[0])

                # Get Lesson
                cur.execute("SELECT id FROM lessons WHERE school_id = %s ORDER BY started_at DESC LIMIT 1", (school_id,))
                lesson = cur.fetchone()
                lesson_id = str(lesson[0])

                # Generate a fresh Token
                token = issue_token(school_id, teacher_id, "teacher")

                print("✅ HERE ARE YOUR CREDENTIALS:\n")
                print(f"CLASS_ID:  {class_id}")
                print(f"LESSON_ID: {lesson_id}")
                print(f"\nTOKEN:\n{token}\n")
                print("Copy and paste these into the Streamlit UI and Mic Listener!")

    except Exception as e:
        print(f"❌ Error: {e}. Is Docker running?")

if __name__ == "__main__":
    get_latest_credentials()