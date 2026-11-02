import psycopg
import uuid
from app.brain import AIBrain
from app.db import tenant_session
from app.models import CurriculumDoc

CURRICULUM_DATA = [
    "A fraction represents a part of a whole. It is written as a numerator over a denominator. The denominator tells you how many equal parts the whole is divided into.",
    "Equivalent fractions are fractions that look different but represent the same value. For example, 1/2 is exactly equal to 2/4. If you multiply the numerator and denominator by the same number, you get an equivalent fraction.",
    "When comparing fractions with the same denominator, the fraction with the larger numerator is greater. For example, 3/4 is greater than 1/4.",
    "A quarter (1/4) is smaller than a half (1/2). Imagine a pizza cut into 4 slices versus 2 slices. One slice of the 2-slice pizza is bigger."
]

def load_data():
    print("🔍 Finding your demo school in the database...")
    try:
        # Connect as superuser to find the school
        with psycopg.connect("postgresql://postgres:postgres@localhost:5432/copilot") as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM schools ORDER BY created_at DESC LIMIT 1")
                school = cur.fetchone()
                
                if not school:
                    print("❌ No school found. Run `python seed_demo.py` first.")
                    return
                
                school_id = str(school[0])
                print(f"✅ Found School ID: {school_id}")

        print("\n📥 Loading curriculum into the vector database...")
        with tenant_session(school_id) as db:
            for text in CURRICULUM_DATA:
                print(f"Embedding: {text[:50]}...")
                vector = AIBrain.get_embedding(text)
                doc = CurriculumDoc(
                    school_id=uuid.UUID(school_id),
                    content=text,
                    embedding=vector
                )
                db.add(doc)
        print("\n🎉 Curriculum loaded successfully! Your AI now has textbook knowledge.")
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    load_data()