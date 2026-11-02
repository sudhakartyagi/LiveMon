from pathlib import Path

compose_content = '''services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: copilot
      POSTGRES_HOST_AUTH_METHOD: trust
    ports: ["5432:5432"]
    volumes:
      - ./init.sql:/docker-entrypoint-initdb.d/init.sql
      - pgdata:/var/lib/postgresql/data
volumes:
  pgdata:
'''

Path("docker-compose.yml").write_text(compose_content, encoding="utf-8")
print("docker-compose.yml updated to use pgvector/pgvector:pg16!")