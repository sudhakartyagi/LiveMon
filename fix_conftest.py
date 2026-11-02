from pathlib import Path

ROOT = Path(".")
FILES = {}

# FULLY RESTORED CONFTEST.PY with class_a and class_b
FILES["tests/conftest.py"] = '''import uuid
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.main import app
from app.auth import issue_token

SUPER_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/copilot"

@pytest.fixture(scope="session")
def setup_schema():
    import subprocess, sys
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)

@pytest.fixture
def super_session(setup_schema):
    eng = create_engine(SUPER_URL)
    Sess = sessionmaker(bind=eng)
    s = Sess()
    try:
        yield s
        s.commit()
    finally:
        s.close()

@pytest.fixture
def two_schools(super_session):
    sa, sb = uuid.uuid4(), uuid.uuid4()
    ta, tb = uuid.uuid4(), uuid.uuid4()
    ca, cb = uuid.uuid4(), uuid.uuid4()
    sta, stb = uuid.uuid4(), uuid.uuid4()

    super_session.execute(text("INSERT INTO schools (id, name) VALUES (:a,'A'),(:b,'B')"), {"a": sa, "b": sb})
    super_session.execute(
        text("INSERT INTO teachers (id, school_id, name) VALUES (:a,:sa,'TA'),(:b,:sb,'TB')"),
        {"a": ta, "sa": sa, "b": tb, "sb": sb},
    )
    super_session.execute(
        text(
            "INSERT INTO classes (id, school_id, grade, section, subject, teacher_id) "
            "VALUES (:a,:sa,4,'A','Math',:ta),(:b,:sb,4,'B','Math',:tb)"
        ),
        {"a": ca, "sa": sa, "ta": ta, "b": cb, "sb": sb, "tb": tb},
    )
    super_session.execute(
        text("INSERT INTO students (id, school_id, class_id, pseudonym) VALUES (:a,:sa,:ca,'stuA'),(:b,:sb,:cb,'stuB')"),
        {"a": sta, "sa": sa, "ca": ca, "b": stb, "sb": sb, "cb": cb},
    )
    super_session.commit()

    return {
        "school_a": sa, "school_b": sb,
        "class_a": ca, "class_b": cb,
        "student_a": sta, "student_b": stb,
        "token_a": issue_token(str(sa), str(ta), "teacher"),
        "token_b": issue_token(str(sb), str(tb), "teacher"),
    }

@pytest.fixture
def client():
    return TestClient(app)
'''

def main():
    p = ROOT / "tests" / "conftest.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(FILES["tests/conftest.py"], encoding="utf-8")
    print("conftest.py fixed! class_a and class_b are now available.")

if __name__ == "__main__":
    main()