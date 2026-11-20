import io
import json
import os
import sys
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
import serveur_inkforge as app
folder = Path(sys.argv[2])
mode = os.environ.get('INKFORGE_TEST_MODE', 'good')
release = {'tag_name':'v2.3.2','assets':[{'name':'inkforge-update.json','id':1},{'name':'inkforge-update.zip','id':2}]}
def mock(request, **kwargs):
    url = request.full_url
    if url.endswith('/releases/latest'):
        return io.BytesIO(json.dumps(release).encode())
    if url.endswith('/assets/1'):
        return io.BytesIO((folder/'inkforge-update.json').read_bytes())
    if url.endswith('/assets/2'):
        data=(folder/'inkforge-update.zip').read_bytes()
        return io.BytesIO(data if mode=='good' else data[:70])
    raise RuntimeError('Unexpected URL')
app.urlopen = mock
app.ThreadingHTTPServer((app.HOST,app.PORT),app.Handler).serve_forever()
