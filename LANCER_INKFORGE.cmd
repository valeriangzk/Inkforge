@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (py -3 serveur_inkforge.py) else (python serveur_inkforge.py)
if errorlevel 1 (echo Python 3 est necessaire. Installez-le depuis python.org puis relancez.&pause)
