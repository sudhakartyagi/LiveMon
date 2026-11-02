@echo off
echo Starting Classroom Agent v5.6...

:: Start Docker
echo [1/3] Starting Database...
start "Database" cmd /c "docker compose up -d"

:: Wait for DB to boot
timeout /t 3 /nobreak > NUL

:: Start API
echo [2/3] Starting API...
start "API" cmd /c "python -m uvicorn app.main:app --reload"

:: Start UI
echo [3/3] Starting Streamlit UI...
start "UI" cmd /c "python -m streamlit run ui/app.py"

:: Start Mic
echo.
echo All services launched! Close the popup windows to stop them.
timeout /t 2 > NUL
start "Microphone" cmd /c "python mic_listener.py"