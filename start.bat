@echo off
cd /d %~dp0
python -m uvicorn demo_backend.app:app --reload --host 0.0.0.0 --port 8080
