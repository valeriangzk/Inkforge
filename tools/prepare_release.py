"""Build the regular update and the one-time Windows migration from 2.4.2."""
import base64
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
version = json.loads((root/'version.json').read_bytes())['version']
payload = out/'inkforge-update.zip'
with zipfile.ZipFile(payload, 'w', zipfile.ZIP_DEFLATED) as archive:
    for name in ('INKFORGE.html','serveur_inkforge.py','version.json','LISEZ_MOI.txt','LANCER_INKFORGE.cmd'):
        archive.write(root/name,name)
(out/'inkforge-update.json').write_text(json.dumps({'version':version,'sha256':hashlib.sha256(payload.read_bytes()).hexdigest()}),encoding='utf-8')

# Opening the assistant never writes into the chosen studio before the browser confirms.
entry = """import os, sys, zipfile
from pathlib import Path
import tkinter as tk
from tkinter import filedialog
with zipfile.ZipFile(sys.argv[0]) as archive:
    code=archive.read('serveur_inkforge.py')
    package=archive.read('inkforge-update.zip')
if len(sys.argv)>1:
    folder=Path(sys.argv[1]).resolve()
else:
    win=tk.Tk();win.withdraw()
    selected=filedialog.askopenfilename(title='Choisis LANCER_INKFORGE.cmd dans ton dossier INKFORGE',filetypes=[('Lanceur INKFORGE','LANCER_INKFORGE.cmd')])
    if not selected:sys.exit()
    folder=Path(selected).parent
filename=folder/'serveur_inkforge.py'
if not filename.is_file():sys.exit('Dossier INKFORGE introuvable.')
studio={'__file__':str(filename),'__name__':'migration_inkforge'}
exec(compile(code,str(filename),'exec'),studio)
studio['maintenance_server'](package)
"""
bundle = io.BytesIO()
with zipfile.ZipFile(bundle,'w',zipfile.ZIP_DEFLATED) as archive:
    archive.writestr('__main__.py',entry)
    archive.write(root/'serveur_inkforge.py','serveur_inkforge.py')
    archive.write(payload,payload.name)
# A .cmd opens even if .pyz files are not associated with Python on this PC.
cmd = r'''@echo off
setlocal
set "INKFORGE_ASSISTANT_SOURCE=%~f0"
set "INKFORGE_ASSISTANT_TEMP=%TEMP%\inkforge-migration-%RANDOM%-%RANDOM%.pyz"
powershell -NoProfile -Command "$tag='#INKFORGE#';$s=[IO.File]::ReadAllText($env:INKFORGE_ASSISTANT_SOURCE);[IO.File]::WriteAllBytes($env:INKFORGE_ASSISTANT_TEMP,[Convert]::FromBase64String($s.Substring($s.LastIndexOf($tag)+$tag.Length).Trim()))"
if errorlevel 1 goto :failed
where py >nul 2>nul
if errorlevel 1 (python "%INKFORGE_ASSISTANT_TEMP%" %*) else (py -3 "%INKFORGE_ASSISTANT_TEMP%" %*)
if errorlevel 1 goto :failed
del "%INKFORGE_ASSISTANT_TEMP%"
exit /b 0
:failed
echo Fermez l'ancien INKFORGE, verifiez que Python est installe, puis relancez cet assistant.
pause
exit /b 1
#INKFORGE#
'''
(out/'MISE_A_JOUR_INKFORGE.cmd').write_bytes((cmd+base64.b64encode(bundle.getvalue()).decode()+'\n').replace('\n','\r\n').encode('ascii'))
