import subprocess
import sys

print("1. Building database tables (Alembic)...")
try:
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    print("   -> Tables created successfully.")
except subprocess.CalledProcessError:
    print("   -> Migration failed. Please check the output above.")
    sys.exit(1)

print("\n2. Seeding demo data...")
try:
    subprocess.run([sys.executable, "seed_demo.py"], check=True)
except subprocess.CalledProcessError:
    print("   -> Seeding failed.")