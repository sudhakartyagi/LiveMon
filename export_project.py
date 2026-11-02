import os

OUTPUT_FILE = "PROJECT_SNAPSHOT.txt"
IGNORE_DIRS = {".git", "__pycache__", ".pytest_cache", "venv", ".venv", "node_modules"}
IGNORE_FILES = {".env", "config.json", "PROJECT_SNAPSHOT.txt"}
EXTENSIONS = {".py", ".toml", ".yml", ".yaml", ".sql", ".md", ".txt"}

def generate_snapshot():
    with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
        out.write("# CLASSROOM AGENT v6.0 - FULL PROJECT SNAPSHOT\n\n")
        
        for root, dirs, files in os.walk("."):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            
            for file in files:
                if file in IGNORE_FILES:
                    continue
                    
                ext = os.path.splitext(file)[1]
                if ext in EXTENSIONS:
                    filepath = os.path.join(root, file)
                    out.write(f"\n{'='*80}\n")
                    out.write(f"FILE: {filepath}\n")
                    out.write(f"{'='*80}\n\n")
                    try:
                        with open(filepath, "r", encoding="utf-8") as f:
                            out.write(f.read())
                    except Exception as e:
                        out.write(f"Could not read file: {e}")
                    out.write("\n\n")

    print(f"✅ Success! Created {OUTPUT_FILE}")
    print("When starting a new chat, just upload or paste this file.")

if __name__ == "__main__":
    generate_snapshot()