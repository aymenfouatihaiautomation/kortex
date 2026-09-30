@echo off
chcp 65001 > nul
title KORTEX — Nouveau Cours
cd /d "C:\Users\hp\ai-edu-platform"
call venv\Scripts\activate.bat
set PYTHONIOENCODING=utf-8
python lancer_cours.py
pause
