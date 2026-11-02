from pathlib import Path

ROOT = Path(".")

# 1. Fix models.py completely (adding Boolean import)
models_content = '''import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, func, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

def _uuid():
    return uuid.uuid4()

class School(Base):
    __tablename__ = "schools"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

class Teacher(Base):
    __tablename__ = "teachers"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("schools.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

class Principal(Base):
    __tablename__ = "principals"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("schools.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

class Classroom(Base):
    __tablename__ = "classes"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("schools.id"), nullable=False)
    grade: Mapped[int] = mapped_column(nullable=False)
    section: Mapped[str] = mapped_column(String(10), nullable=False)
    subject: Mapped[str] = mapped_column(String(50), nullable=False)
    teacher_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("teachers.id"), nullable=False)

class Student(Base):
    __tablename__ = "students"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("schools.id"), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("classes.id"), nullable=False)
    pseudonym: Mapped[str] = mapped_column(String(100), nullable=False)

class Lesson(Base):
    __tablename__ = "lessons"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("schools.id"), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("classes.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    mode: Mapped[str] = mapped_column(String(20), default="normal")

class Policy(Base):
    __tablename__ = "policies"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("schools.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("schools.id"), nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource: Mapped[str] = mapped_column(String(200), nullable=False)
    is_cross_tenant_attempt: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class AgentAction(Base):
    __tablename__ = "agent_actions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("schools.id"), nullable=False)
    lesson_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("lessons.id"), nullable=False)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    tier: Mapped[int] = mapped_column(nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    target_type: Mapped[str] = mapped_column(String(50), nullable=True)
    target_id: Mapped[str] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="logged")
    principal_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class Dispute(Base):
    __tablename__ = "disputes"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("schools.id"), nullable=False)
    agent_action_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_actions.id"), nullable=False)
    teacher_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    flag_reason: Mapped[str] = mapped_column(String(500), nullable=False)
    resolution: Mapped[str] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class ClassState(Base):
    __tablename__ = "class_states"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("schools.id"), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("classes.id"), nullable=False)
    is_paused: Mapped[bool] = mapped_column(Boolean, default=False)
    paused_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
'''

# 2. Recreate 0002
mig_0002 = '''"""Week 2: Policies, Audit, Disputes"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"

TENANT_TABLES = ["policies", "audit_logs", "agent_actions", "disputes"]

def upgrade():
    op.create_table("policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("school_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("config", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_table("audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("school_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource", sa.String(200), nullable=False),
        sa.Column("is_cross_tenant_attempt", sa.Boolean, server_default="false"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.add_column("agent_actions", sa.Column("target_type", sa.String(50), nullable=True))
    op.add_column("agent_actions", sa.Column("target_id", sa.String(100), nullable=True))
    op.add_column("agent_actions", sa.Column("status", sa.String(50), server_default="logged"))
    op.add_column("agent_actions", sa.Column("principal_notified", sa.Boolean, server_default="false"))
    op.create_table("disputes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("school_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("agent_action_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_actions.id"), nullable=False),
        sa.Column("teacher_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("flag_reason", sa.String(500), nullable=False),
        sa.Column("resolution", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    for t in TENANT_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING (school_id = current_setting('app.current_tenant_id', true)::uuid) WITH CHECK (school_id = current_setting('app.current_tenant_id', true)::uuid)")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO app_user")

def downgrade():
    for t in reversed(TENANT_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    op.drop_column("agent_actions", "principal_notified")
    op.drop_column("agent_actions", "status")
    op.drop_column("agent_actions", "target_id")
    op.drop_column("agent_actions", "target_type")
'''

# 3. Recreate 0003
mig_0003 = '''"""Week 4: Audio State & Kill Switch"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"

def upgrade():
    op.create_table(
        "class_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("school_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("class_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("classes.id"), nullable=False),
        sa.Column("is_paused", sa.Boolean, server_default="false"),
        sa.Column("paused_at", sa.DateTime, nullable=True),
    )
    op.execute("ALTER TABLE class_states ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE class_states FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tenant_isolation ON class_states USING (school_id = current_setting('app.current_tenant_id', true)::uuid) WITH CHECK (school_id = current_setting('app.current_tenant_id', true)::uuid)")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON class_states TO app_user")

def downgrade():
    op.execute("DROP TABLE IF EXISTS class_states CASCADE")
'''

def main():
    (ROOT / "app" / "models.py").write_text(models_content, encoding="utf-8")
    (ROOT / "alembic" / "versions" / "0002_week2.py").write_text(mig_0002, encoding="utf-8")
    (ROOT / "alembic" / "versions" / "0003_week4.py").write_text(mig_0003, encoding="utf-8")
    print("Repaired models.py, 0002_week2.py, and 0003_week4.py!")

if __name__ == "__main__":
    main()