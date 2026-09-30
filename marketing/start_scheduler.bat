@echo off
REM Marketing KORTEX - lance le planificateur (scheduler_marketing.py) en boucle persistante.
REM A appeler par la tache Windows planifiee (voir marketing/README.md pour la config Task
REM Scheduler) - NE PAS planifier cette tache a "08:00 tous les jours" : scheduler_marketing.py
REM contient deja sa propre boucle interne qui declenche la publication a 08:00 chaque jour ;
REM ce script ne doit etre (re)lance que via un declencheur "Au demarrage"/"A l'ouverture de
REM session" (une seule instance persistante, pas un nouveau run quotidien).

cd /d "%~dp0.."
call venv\Scripts\activate.bat
REM -u : sortie non bufferisee - sans ce flag, stdout redirige vers un fichier est bufferise par
REM bloc sur Windows et scheduler_windows.log resterait vide pendant toute la duree du process.
python -u marketing\scheduler_marketing.py >> marketing\logs\scheduler_windows.log 2>&1
