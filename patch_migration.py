"""patch_migration.py (v4) — dialect-aware migrations.
v4 fixes: helper now correctly inserted into files that have _pg_only
calls but no definition (0002/0003/0004). Safe to re-run."""
import re, pathlib

VERSIONS = pathlib.Path(__file__).parent / "alembic" / "versions"
PG_KEYWORDS = ("row level security", "create policy", "drop policy",
               "gen_random_uuid", "pgcrypto", "using gin", "using hnsw", "using ivfflat",
               "grant ", "revoke ", "create role", "alter role",
               "create extension", "default privileges",
               "owner to", "comment on", "replica identity",
               "create function", "drop function",
               "create trigger", "drop trigger")

TYPE_FIXES = [
    (r"\bpostgresql\.JSONB\b", "sa.JSON"),
    (r"\bpostgresql\.TSVECTOR\b", "sa.Text"),
    (r"\bpostgresql\.BYTEA\b", "sa.LargeBinary"),
    (r"postgresql\.ARRAY\([^()]*\)", "sa.JSON"),
    (r"postgresql\.ENUM\([^()]*\)", "sa.String"),
    (r"\bVector\(\s*\d+\s*\)", "sa.JSON"),
]

HELPER = '''
def _pg_only(fn):
    """Run a Postgres-only statement only when the target DB is PostgreSQL."""
    from alembic import context as _ctx
    if _ctx.get_bind().dialect.name == "postgresql":
        fn()
'''

def balanced_end(text, start):
    i = text.index("(", start)
    depth, j = 0, i
    while j < len(text):
        if text[j] == "(":
            depth += 1
        elif text[j] == ")":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    raise ValueError("unbalanced parentheses in migration file")

def patch_file(path):
    src = path.read_text(encoding="utf-8")
    type_fixes = 0
    for pat, repl in TYPE_FIXES:
        src, n = re.subn(pat, repl, src)
        type_fixes += n
    out, pos, wrapped = [], 0, 0
    pattern = re.compile(r"op\.execute\(")
    while True:
        m = pattern.search(src, pos)
        if not m:
            out.append(src[pos:]); break
        before = src[:m.start()].rstrip()
        end = balanced_end(src, m.start())
        if before.endswith("_pg_only(lambda:"):
            out.append(src[pos:end]); pos = end; continue
        call = src[m.start():end]
        if any(k in call.lower() for k in PG_KEYWORDS):
            out.append(src[pos:m.start()])
            out.append(f"_pg_only(lambda: {call})")
            wrapped += 1
        else:
            out.append(src[pos:end])
        pos = end
    new_src = "".join(out)
    needs_helper = ("def _pg_only" not in new_src) and ("_pg_only(" in new_src)
    helper_added = False
    if needs_helper:
        if "def upgrade(" in new_src:
            new_src = new_src.replace("def upgrade(", HELPER + "\ndef upgrade(", 1)
        else:
            new_src += "\n" + HELPER
        helper_added = True
    if type_fixes or wrapped or helper_added:
        path.write_text(new_src, encoding="utf-8")
    return type_fixes, wrapped, helper_added

def main():
    tf = wr = 0
    for f in sorted(VERSIONS.glob("*.py")):
        if f.name == "__init__.py":
            continue
        t, w, h = patch_file(f)
        if t or w or h:
            msg = f"{f.name}: {t} type(s) rewritten, {w} statement(s) wrapped"
            if h:
                msg += ", _pg_only helper ADDED"
            print(msg)
        tf += t; wr += w
    print("Done. Now run: python -m alembic upgrade head" if tf or wr
          else "Nothing to patch - files already consistent.")

if __name__ == "__main__":
    main()