import psycopg
from pathlib import Path

print("1. Resetting database schema...")
try:
    # Connect as superuser to drop and recreate the schema
    with psycopg.connect("postgresql://postgres:postgres@localhost:5432/copilot", autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA public CASCADE;")
            cur.execute("CREATE SCHEMA public;")
            cur.execute("GRANT ALL ON SCHEMA public TO app_user;")
            cur.execute("GRANT ALL ON SCHEMA public TO public;")
    print("   -> Database wiped clean.")
except Exception as e:
    print(f"   -> Failed to reset DB: {e}")

print("2. Fixing 0002_week2.py...")
mig_0002 = '''"""Week 2: Policies, Audit, Disputes"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"

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
    
    # Add columns to existing agent_actions table
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
    
    # ONLY apply RLS to the NEW tables created in this migration!
    NEW_TENANT_TABLES = ["policies", "audit_logs", "disputes"]
    for t in NEW_TENANT_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING (school_id = current_setting('app.current_tenant_id', true)::uuid) WITH CHECK (school_id = current_setting('app.current_tenant_id', true)::uuid)")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO app_user")

def downgrade():
    for t in reversed(["policies", "audit_logs", "disputes"]):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    op.drop_column("agent_actions", "principal_notified")
    op.drop_column("agent_actions", "status")
    op.drop_column("agent_actions", "target_id")
    op.drop_column("agent_actions", "target_type")
'''
Path("alembic/versions/0002_week2.py").write_text(mig_0002, encoding="utf-8")
print("   -> Migration file fixed.")