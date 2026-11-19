from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import json, webbrowser, threading, time, socket, zipfile, io, os, shutil, tempfile, re, hashlib, base64, mimetypes
from urllib.request import build_opener, HTTPRedirectHandler
from urllib.parse import urlparse

HOST = "127.0.0.1"
PORT = 8765
HTML = Path(__file__).with_name("INKFORGE.html")
AGNES = "https://apihub.agnes-ai.com/v1/models"
AGNES_GENERATE = "https://apihub.agnes-ai.com/v1/images/generations"
VERSION_FILE = Path(__file__).with_name('version.json')
SOURCE_FILE = Path(__file__).with_name('update_source.json')
UPDATE_LOCK = threading.Lock()
def version_data():
    return json.loads(VERSION_FILE.read_text(encoding='utf-8'))
def fetch_json(url, max_bytes=65536):
    with urlopen(Request(url, headers={'Accept':'application/vnd.github+json','User-Agent':'INKFORGE-Updater/2.2'}), timeout=10) as response:
        data=response.read(max_bytes+1)
        if len(data)>max_bytes: raise ValueError('Réponse distante trop grande')
        return json.loads(data)

def repo_config():
    if not SOURCE_FILE.exists(): return 'valeriangzk/Inkforge'
    try:
        repo=json.loads(SOURCE_FILE.read_text(encoding='utf-8')).get('repo','')
        return repo if isinstance(repo,str) and re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo) else ''
    except (ValueError,OSError): return ''

def release_data():
    repo=repo_config()
    if not repo: return None
    release=fetch_json('https://api.github.com/repos/'+repo+'/releases/latest')
    tag=str(release.get('tag_name','')).lstrip('v')
    if not re.fullmatch(r'\d+\.\d+\.\d+',tag): raise ValueError('Version distante invalide')
    assets={a.get('name'):a for a in release.get('assets',[]) if isinstance(a,dict)}
    manifest=assets.get('inkforge-update.json')
    archive=assets.get('inkforge-update.zip')
    if not manifest or not archive: raise ValueError('Fichiers de mise à jour absents de la release')
    # Download the manifest through GitHub's asset endpoint, never an arbitrary third-party URL.
    req=Request('https://api.github.com/repos/'+repo+'/releases/assets/'+str(manifest['id']),headers={'Accept':'application/octet-stream','User-Agent':'INKFORGE-Updater/2.2'})
    with urlopen(req,timeout=10) as response:
        payload=response.read(16385)
    if len(payload)>16384: raise ValueError('Manifeste trop grand')
    # Some GitHub responses return JSON metadata instead of binary; detect and refuse.
    manifest_data=json.loads(payload)
    if manifest_data.get('version')!=tag or not re.fullmatch('[a-f0-9]{64}',str(manifest_data.get('sha256',''))):
        raise ValueError('Manifeste de mise à jour invalide')
    return {'version':tag,'notes':str(release.get('body',''))[:1200], 'sha256':manifest_data['sha256'], 'asset_id':archive['id'], 'repo':repo}

def update_status():
    current=version_data()['version']; repo=repo_config()
    result={'version':current,'current_version':current,'available':False,'remote_configured':bool(repo),'repo':repo,'auto_installable':False}
    if not repo: return result
    try:
        remote=release_data()
        if tuple(map(int,remote['version'].split('.')))>tuple(map(int,current.split('.'))):
            result.update(available=True,auto_installable=True,version=remote['version'],notes=remote['notes'])
    except Exception as exc:
        result['error']='Impossible de vérifier la dernière release GitHub : '+str(exc)[:150]
    return result

def auto_install(expected_version=None):
    remote=release_data()
    if not remote: raise ValueError('Dépôt GitHub non configuré')
    if expected_version is not None and remote['version'] != expected_version:
        raise ValueError('La version disponible a changé. Rechargez INKFORGE pour vérifier de nouveau.')
    current=version_data()['version']
    if tuple(map(int,remote['version'].split('.')))<=tuple(map(int,current.split('.'))):
        raise ValueError('Aucune mise à jour disponible')
    url='https://api.github.com/repos/'+remote['repo']+'/releases/assets/'+str(remote['asset_id'])
    req=Request(url,headers={'Accept':'application/octet-stream','User-Agent':'INKFORGE-Updater/2.2'})
    with urlopen(req,timeout=30) as response:
        payload=response.read(8_000_001)
    if len(payload)>8_000_000: raise ValueError('Mise à jour trop volumineuse')
    if hashlib.sha256(payload).hexdigest()!=remote['sha256']:
        raise ValueError('Échec du contrôle SHA-256')
    return install_zip(payload, expected_version=remote['version'])

def install_zip(data, expected_version=None):
    with UPDATE_LOCK, zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = {Path(n).name: n for n in archive.namelist() if not n.endswith('/')}
        allowed = ('INKFORGE.html', 'serveur_inkforge.py', 'version.json')
        if not set(allowed).issubset(members):
            raise ValueError('ZIP incompatible : fichiers INKFORGE manquants')
        if len(archive.namelist()) > 30 or any(i.file_size > 2_000_000 for i in archive.infolist()):
            raise ValueError('ZIP trop volumineux')
        incoming = json.loads(archive.read(members['version.json']))
        target_version = incoming.get('version', '')
        if not re.fullmatch(r'\d+\.\d+\.\d+', str(target_version)):
            raise ValueError('Version invalide')
        if expected_version is not None and target_version != expected_version:
            raise ValueError('Le ZIP ne correspond pas à la version publiée')
        current = version_data()['version']
        if tuple(map(int,target_version.split('.'))) <= tuple(map(int,current.split('.'))):
            raise ValueError('Choisissez une version plus récente')
        new_html = archive.read(members['INKFORGE.html'])
        new_server = archive.read(members['serveur_inkforge.py'])
        if b'inkforge-installed-version' not in new_html or b'/validate-keys' not in new_server:
            raise ValueError('ZIP non compatible avec le studio')
        base = Path(__file__).resolve().parent
        backup = base / '_backup_version_precedente'
        backup.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.inkforge-update-', dir=base) as staging:
            staging = Path(staging)
            for name in allowed:
                (staging / name).write_bytes(archive.read(members[name]))
                shutil.copy2(base / name, backup / name)
                shutil.copy2(base / name, staging / (name + '.previous'))
            replaced = []
            try:
                for name in allowed:
                    os.replace(staging / name, base / name)
                    replaced.append(name)
            except OSError:
                for name in reversed(replaced):
                    os.replace(staging / (name + '.previous'), base / name)
                raise
        return target_version



# Agnes AI: the key is sent by the browser only for an explicit action; never persisted or logged.
class ClientFailure(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status=status

def require_same_origin(headers):
    origin=headers.get('Origin')
    if origin not in (f'http://{HOST}:{PORT}',f'http://localhost:{PORT}'):
        raise ClientFailure('Requête refusée : ouvrez INKFORGE via LANCER_INKFORGE.cmd.',403)

def parse_small_json(handler, max_bytes=12_000_000):
    require_same_origin(handler.headers)
    if handler.headers.get('Content-Type','').split(';')[0].strip()!='application/json':
        raise ClientFailure('Format JSON attendu',415)
    try: size=int(handler.headers.get('Content-Length','0'))
    except ValueError: raise ClientFailure('Taille de la requête invalide')
    if not 0<size<=max_bytes: raise ClientFailure('Données trop volumineuses ou absentes')
    try: payload=json.loads(handler.rfile.read(size))
    except (ValueError,UnicodeError): raise ClientFailure('Requête JSON invalide')
    if not isinstance(payload,dict): raise ClientFailure('Requête invalide')
    key=payload.get('apiKey')
    if not isinstance(key,str) or not key.strip() or len(key)>1200:
        raise ClientFailure('Clé Agnes AI manquante ou invalide')
    return payload,key.strip()

def agnes_request(url, key, data=None, max_bytes=12_000_000, timeout=70):
    headers={'Authorization':'Bearer '+key,'Accept':'application/json','User-Agent':'INKFORGE-Studio/2.3'}
    if data is not None:
        data=json.dumps(data,ensure_ascii=False,separators=(',',':')).encode('utf-8')
        headers['Content-Type']='application/json'
    req=Request(url,data=data,headers=headers)
    try:
        with urlopen(req,timeout=timeout) as response:
            raw=response.read(max_bytes+1)
        if len(raw)>max_bytes: raise ClientFailure('Réponse Agnes AI trop volumineuse',502)
        return json.loads(raw)
    except HTTPError as exc:
        # Do not include raw upstream responses, which might echo private data.
        messages={400:'Requête refusée par Agnes AI (format ou paramètres du modèle).',401:'Clé API Agnes AI invalide.',403:'Accès refusé par Agnes AI : vérifie tes droits ou ton forfait.',404:'Modèle ou point d’accès introuvable chez Agnes AI.',422:'Paramètres d’image non acceptés par ce modèle.',429:'Limite de demandes ou crédit Agnes AI atteint.',500:'Erreur du service Agnes AI.',502:'Service Agnes AI temporairement indisponible.',503:'Service Agnes AI indisponible.'}
        raise ClientFailure(messages.get(exc.code,'Agnes AI a retourné une erreur HTTP '+str(exc.code)),502)
    except (URLError,TimeoutError,OSError):
        raise ClientFailure('Agnes AI ne répond pas (réseau ou délai dépassé). Réessaie plus tard.',502)
    except (ValueError,UnicodeDecodeError): raise ClientFailure('Réponse Agnes AI illisible.',502)

def image_models(data):
    if not isinstance(data,dict) or not isinstance(data.get('data'),list):
        raise ClientFailure('Agnes AI a retourné une liste de modèles inattendue.',502)
    ids=[]
    for item in data['data']:
        if not isinstance(item,dict): continue
        ident=item.get('id')
        if isinstance(ident,str) and re.fullmatch(r'[a-zA-Z0-9._:-]{3,120}',ident) and 'image' in ident.lower():
            ids.append({'id':ident,'name':ident})
    ids.sort(key=lambda m:(not m['id'].endswith('2.5-flash'),m['id']))
    return ids

def describe_reference(entity,which):
    if not isinstance(entity,dict): return '',[]
    text=[]
    for field,label in [('name','Nom'),('description','Description'),('appearance','Apparence'),('clothing','Vêtements'),('accessories','Accessoires'),('notes','Notes')]:
        value=entity.get(field)
        if isinstance(value,str) and value.strip(): text.append(label+': '+value[:450])
    refs=[]
    sources=list(entity.get('references') or []) if isinstance(entity.get('references'),list) else []
    if not sources and entity.get('img'):sources=[entity['img']]
    for image in sources[:4]:
        if not isinstance(image,str):continue
        if re.fullmatch(r'data:image/(?:png|jpe?g|webp);base64,[A-Za-z0-9+/=]+',image,re.I):
            b64=image.split(',',1)[1]
            if len(b64)<2_000_000: refs.append(b64)
        elif image.startswith('https://') and len(image)<2000 and urlparse(image).hostname in ('apihub.agnes-ai.com','platform-outputs.agnes-ai.space'):
            refs.append(image)
    return which+' : '+' ; '.join(text),refs

def trusted_image_url(url):
    parsed = urlparse(url)
    return (parsed.scheme == 'https' and parsed.hostname in
            ('apihub.agnes-ai.com', 'platform-outputs.agnes-ai.space')
            and parsed.username is None and parsed.port in (None, 443))


class ImageRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not trusted_image_url(newurl):
            raise ClientFailure('Redirection de l’image vers un domaine inconnu.', 502)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def local_image(record):
    value = record.get('b64_json') or record.get('url')
    if not isinstance(value, str) or not value:
        raise ClientFailure('Agnes AI a retourné une réponse sans image.', 502)
    try:
        if value.startswith('https://'):
            if not trusted_image_url(value):
                raise ClientFailure('Adresse de téléchargement Agnes AI inconnue.', 502)
            with build_opener(ImageRedirect()).open(value, timeout=30) as response:
                data = response.read(9_000_001)
        else:
            if value.startswith('data:'):
                value = value.split(',', 1)[-1]
            data = base64.b64decode(''.join(value.split()), validate=True)
    except (ValueError, OSError) as exc:
        raise ClientFailure('Image Agnes AI illisible ou lien expiré.', 502) from exc
    if len(data) > 9_000_000:
        raise ClientFailure('Image Agnes AI trop volumineuse.', 502)
    if data.startswith(bytes.fromhex('89504e470d0a1a0a')):
        kind = 'png'
    elif data.startswith(bytes.fromhex('ffd8ff')):
        kind = 'jpeg'
    elif data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        kind = 'webp'
    else:
        raise ClientFailure('Format illisible : PNG, JPEG ou WebP attendu.', 502)
    return 'data:image/' + kind + ';base64,' + base64.b64encode(data).decode('ascii')


def send_generate(payload,key):
    model=payload.get('model'); prompt=payload.get('prompt')
    if not isinstance(model,str) or not re.fullmatch(r'[A-Za-z0-9._:-]{3,120}',model) or 'image' not in model.lower():
        raise ClientFailure('Sélectionne un modèle image Agnes AI valide.')
    if not isinstance(prompt,str) or not 1<=len(prompt.strip())<=8000:
        raise ClientFailure('Décris la scène en 1 à 8000 caractères.')
    # Verify accessible model before a billable request.
    available=image_models(agnes_request(AGNES,key,timeout=12))
    if model not in {m['id'] for m in available}:
        raise ClientFailure('Le modèle image choisi n’apparaît pas dans les modèles accessibles avec ta clé.')
    descriptions,refs=[],[]
    for k,kind in [('character','Personnage'),('place','Décor')]:
        text,images=describe_reference(payload.get(k),kind)
        if text:descriptions.append(text)
        refs.extend(images)
    full_prompt=prompt.strip()
    if descriptions: full_prompt+='\n\nRéférences de continuité à respecter :\n'+'\n'.join(descriptions)
    frame=payload.get('frame') if isinstance(payload.get('frame'),dict) else {}
    try: ratio=float(frame.get('w',1))/max(0.1,float(frame.get('h',1)))
    except (ValueError,TypeError,ZeroDivisionError):ratio=1.0
    size='1024x768' if ratio>1.2 else ('768x1024' if ratio<0.8 else '1024x1024')
    req={'model':model,'prompt':full_prompt,'n':1,'size':size}
    if refs:
        # Reference input format documented by Agnes AI. Raw base64 strings (without data URI prefix).
        req['extra_body']={'image':refs[:5],'response_format':'b64_json'}
    result=agnes_request(AGNES_GENERATE,key,req,max_bytes=14_000_000,timeout=110)
    if not isinstance(result,dict) or not isinstance(result.get('data'),list) or not result['data']:
        raise ClientFailure('Réponse de génération sans image. Vérifie le modèle.',502)
    record=result['data'][0]
    if not isinstance(record,dict):raise ClientFailure('Format d’image renvoyé non reconnu.',502)
    image=local_image(record)
    return {'image':image,'references_used':len(refs[:5]),'model':model}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Do not log API keys or request bodies.
        return

    def send_data(self, status, data, kind="application/json; charset=utf-8"):
        payload = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path in ("/", "/INKFORGE.html"):
            self.send_data(200, HTML.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/updates/status":
            self.send_data(200, update_status())
        elif self.path == "/health":
            self.send_data(200, {"configured": True, "status": "running"})
        else:
            self.send_data(404, {"error": "Page introuvable"})

    def do_POST(self):
        if self.path in ('/ai/models','/ai/check','/ai/generate'):
            try:
                payload,key=parse_small_json(self)
                if self.path=='/ai/generate':
                    return self.send_data(200,send_generate(payload,key))
                models=image_models(agnes_request(AGNES,key,timeout=16))
                if self.path=='/ai/models':return self.send_data(200,{'data':models})
                selected=payload.get('model')
                if selected and selected not in {m['id'] for m in models}:
                    raise ClientFailure('La clé fonctionne, mais le modèle choisi n’est pas disponible pour la génération.')
                return self.send_data(200,{'connected':True,'models':len(models),'message':'Relais accessible, clé Agnes AI valide, '+str(len(models))+' modèle(s) image détecté(s).'+(' Modèle sélectionné accessible.' if selected else ' Sélectionne ensuite un modèle.')})
            except ClientFailure as exc:return self.send_data(exc.status,{'error':str(exc)})
            except Exception:return self.send_data(500,{'error':'Erreur interne du relais local. Redémarre le studio.'})
        if self.path == '/updates/config':
            if self.headers.get('Origin') not in (f'http://{HOST}:{PORT}', f'http://localhost:{PORT}'):
                return self.send_data(403,{'error':'Origine refusée'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<1024: raise ValueError('Configuration invalide')
                repo=json.loads(self.rfile.read(size)).get('repo','').strip()
                if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo): raise ValueError('Format attendu : propriétaire/dépôt')
                SOURCE_FILE.write_text(json.dumps({'repo':repo}),encoding='utf-8')
                return self.send_data(200,{'saved':True,'repo':repo})
            except (ValueError,TypeError,AttributeError) as exc:
                return self.send_data(400,{'error':str(exc)})
        if self.path == '/updates/auto-install':
            if self.headers.get('Origin') not in (f'http://{HOST}:{PORT}', f'http://localhost:{PORT}'):
                return self.send_data(403,{'error':'Origine refusée'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size < 1024:
                    raise ValueError('Demande de mise à jour invalide')
                expected = json.loads(self.rfile.read(size)).get('version')
                if expected is not None and (not isinstance(expected, str) or not re.fullmatch(r'\d+\.\d+\.\d+', expected)):
                    raise ValueError('Version demandée invalide')
                version=auto_install(expected)
                return self.send_data(200,{'version':version,'installed':True})
            except Exception as exc:
                return self.send_data(400,{'error':str(exc)[:180]})
        if self.path == '/updates/install':
            if self.headers.get('Origin') not in (f'http://{HOST}:{PORT}', f'http://localhost:{PORT}'):
                return self.send_data(403, {'error':'Origine refusée'})
            if self.headers.get('Content-Type','').split(';')[0] != 'application/zip':
                return self.send_data(415, {'error':'ZIP attendu'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0 < size <= 8_000_000:
                    raise ValueError('Fichier trop volumineux')
                version=install_zip(self.rfile.read(size))
                return self.send_data(200, {'version':version, 'installed':True})
            except (ValueError,zipfile.BadZipFile,KeyError,OSError) as exc:
                return self.send_data(400, {'error':str(exc)})
        if self.path != "/validate-keys":
            return self.send_data(404, {"error": "Route introuvable"})
        if self.headers.get("Origin") not in (None, f"http://{HOST}:{PORT}", f"http://localhost:{PORT}"):
            return self.send_data(403, {"connected": None, "reason": "Origine refusée"})
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self.send_data(415, {"connected": None, "reason": "JSON attendu"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 16384:
                return self.send_data(400, {"connected": None, "reason": "Taille invalide"})
            data = json.loads(self.rfile.read(size))
            provider = str(data.get("provider", "")).strip().lower()
            key = data.get("apiKey")
            if provider not in ("agnes ai", "agnes", "agnès ai", "agnès"):
                return self.send_data(200, {"connected": None, "reason": "Seul Agnes AI est pris en charge"})
            if not isinstance(key, str) or not key.strip():
                return self.send_data(200, {"connected": False, "reason": "Clé manquante"})
            request = Request(AGNES, headers={"Authorization": "Bearer " + key.strip(), "Accept": "application/json", "User-Agent": "INKFORGE-Studio/2"})
            try:
                with urlopen(request, timeout=10) as response:
                    body = response.read(1024 * 1024)
                    try:
                        parsed = json.loads(body)
                    except ValueError:
                        return self.send_data(200, {"connected": None, "reason": "Réponse API inattendue"})
                    if isinstance(parsed, dict) and isinstance(parsed.get("data"), list):
                        return self.send_data(200, {"connected": True, "reason": "Liste des modèles accessible"})
                    return self.send_data(200, {"connected": None, "reason": "Réponse API non reconnue"})
            except HTTPError as exc:
                if exc.code in (401, 403):
                    return self.send_data(200, {"connected": False, "reason": "Accès refusé (HTTP %s)" % exc.code})
                return self.send_data(200, {"connected": None, "reason": "Service API HTTP %s" % exc.code})
            except (URLError, TimeoutError, OSError):
                return self.send_data(200, {"connected": None, "reason": "Réseau ou service indisponible"})
        except (ValueError, TypeError, KeyError):
            return self.send_data(400, {"connected": None, "reason": "Requête invalide"})

if __name__ == "__main__":
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError:
        print("Port 8765 occupé. Fermez l'ancien INKFORGE puis relancez.")
        input("Appuyez sur Entrée pour fermer...")
        raise SystemExit(1)
    print("INKFORGE est disponible sur http://127.0.0.1:8765")
    print("Laissez cette fenêtre ouverte pendant l'utilisation.")
    threading.Timer(1, lambda: webbrowser.open(f"http://{HOST}:{PORT}/")).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
