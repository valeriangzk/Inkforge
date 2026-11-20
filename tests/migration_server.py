"""Run an isolated installed version, its ordinary UI, or the same recovery runner used on Windows."""
import os
import sys
from pathlib import Path

folder=Path(sys.argv[1]).resolve()
mode=sys.argv[2]
code=(Path(__file__).resolve().parents[1]/'serveur_inkforge.py') if mode in ('prepare','rescue') else (folder/'serveur_inkforge.py')
if mode=='rescue':code=folder/'.inkforge-recuperation.py'
ns={'__file__':str(folder/code.name),'__name__':'test_migration'}
exec(compile(code.read_bytes(),str(code),'exec'),ns)
ns['PORT']=int(os.getenv('INKFORGE_MIGRATION_PORT','18766'))
ns['LOCAL_3D']=folder/'test-local'/'INKFORGE'/'TripoSR'
ns['webbrowser'].open=lambda *args:True
ns['update_status']=lambda:{'available':False,'current_version':ns['version_data']()['version']}
if mode=='prepare':
    ns['maintenance_server'](Path(sys.argv[3]).read_bytes())
elif mode=='rescue':
    ns['maintenance_server']()
elif 'serve' in ns:
    ns['serve'](ns['Handler'])
else:
    ns['ThreadingHTTPServer']((ns['HOST'],ns['PORT']),ns['Handler']).serve_forever()
