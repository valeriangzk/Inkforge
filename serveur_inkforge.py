from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from contextlib import contextmanager
import subprocess, sys, uuid, atexit
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

def install_zip(data, expected_version=None, legacy_browser=None):
    with WORK_LOCK, zipfile.ZipFile(io.BytesIO(data)) as archive:
        reject_busy()
        if LEGACY_BACKUP.exists() and legacy_browser is None:
            raise ValueError('Ouvre le studio dans ton navigateur habituel pour terminer la sauvegarde précédente.')
        names = archive.namelist()
        members = {Path(n).name:n for n in names if not n.endswith('/')}
        if (len(names)>30 or len(members)!=len([n for n in names if not n.endswith('/')]) or
                any(i.file_size>2_000_000 for i in archive.infolist()) or not set(PROGRAM).issubset(members)):
            raise ValueError('ZIP incompatible ou trop volumineux.')
        target = json.loads(archive.read(members['version.json'])).get('version','')
        if not isinstance(target,str) or not re.fullmatch(r'\d+\.\d+\.\d+',target) or expected_version and target!=expected_version:
            raise ValueError('Version du ZIP invalide.')
        if tuple(map(int,target.split('.'))) <= tuple(map(int,BOOT_VERSION.split('.'))):
            raise ValueError('Choisissez une version plus récente.')
        if b'inkforge-installed-version' not in archive.read(members[PROGRAM[0]]) or b'/validate-keys' not in archive.read(members[PROGRAM[1]]):
            raise ValueError('ZIP incompatible avec le studio.')
        with tempfile.TemporaryDirectory(prefix='.inkforge-install-',dir=BASE) as tmp:
            stage=Path(tmp)/'stage'
            new=stage/'new'
            new.mkdir(parents=True)
            names = [n for n in PROGRAM+('LANCER_INKFORGE.cmd','LISEZ_MOI.txt') if n in members]
            for name in names:
                write_atomic(new/name,archive.read(members[name]))
            compile((new/'serveur_inkforge.py').read_bytes(),'serveur_inkforge.py','exec')
            create_rescue(stage/'secours.zip', BASE, WORK, legacy_browser, LOCAL_3D/'models' if legacy_browser is not None else None)
            names.extend([WORK.name,LEGACY_BROWSER.name])
            if legacy_browser is not None:
                names.append(LEGACY_BACKUP.name)
            commit_files(stage,names,True)
        return target
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
    payload=read_json(handler,max_bytes)
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
        messages={402:'Quota ou solde Agnes AI insuffisant.',400:'Requête refusée par Agnes AI (format ou paramètres du modèle).',401:'Clé API Agnes AI invalide.',403:'Accès refusé par Agnes AI : vérifie tes droits ou ton forfait.',404:'Modèle ou point d’accès introuvable chez Agnes AI.',422:'Paramètres d’image non acceptés par ce modèle.',429:'Limite de demandes ou crédit Agnes AI atteint.',500:'Erreur du service Agnes AI.',502:'Service Agnes AI temporairement indisponible.',503:'Service Agnes AI indisponible.'}
        error=ClientFailure(messages.get(exc.code,'Agnes AI a retourné une erreur HTTP '+str(exc.code)),502)
        error.provider_status=exc.code
        delay=exc.headers.get('Retry-After','')
        if delay.isdigit():
            error.retry_after=int(delay)
        elif delay:
            from email.utils import parsedate_to_datetime
            try:error.retry_after=max(0,int(parsedate_to_datetime(delay).timestamp()-time.time())+1)
            except (TypeError,ValueError,OverflowError):pass
        raise error
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
    for field,label in [('name','Nom'),('description','Description'),('appearance','Apparence'),('colors','Couleurs'),('proportions','Proportions'),('clothing','Vêtements'),('accessories','Accessoires'),('notes','Notes'),('lighting','Éclairage')]:
        value=entity.get(field)
        if isinstance(value,str) and value.strip(): text.append(label+': '+value[:(8000 if which=='Décor' and field=='description' else 450)])
    refs=[]
    sources=list(entity.get('references') or []) if isinstance(entity.get('references'),list) else []
    if not sources and entity.get('img'):sources=[entity['img']]
    if entity.get('portrait'):
        sources.insert(0, entity['portrait'])
    ident=entity.get('model3d')
    if isinstance(ident,str) and re.fullmatch('[a-f0-9]{64}',ident):
        for index in (0,1,2):
            view=WORK/'models'/ident/f'view-{index}.jpg'
            if view.is_file():
                refs.append('data:image/jpeg;base64,'+base64.b64encode(view.read_bytes()).decode('ascii'))
    for image in dict.fromkeys(sources):
        if len(refs) >= 5:
            break
        if isinstance(image,str) and len(image) <= 800_000 and re.fullmatch(r'data:image/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=]+',image):
            refs.append(image)
        elif isinstance(image,str) and len(image)<2000 and image.startswith('https://') and trusted_image_url(image):
            refs.append(image)
        else:
            raise ClientFailure('Une référence est illisible. Ouvre la fiche et remplace cette image.')
    return which+' : '+' ; '.join(text),refs

def trusted_image_url(url):
    parsed = urlparse(url)
    known_host=parsed.hostname in ('apihub.agnes-ai.com','platform-outputs.agnes-ai.space')
    agnes_bucket=parsed.hostname=='storage.googleapis.com' and parsed.path.startswith('/agnes-aigc/')
    return parsed.scheme=='https' and (known_host or agnes_bucket) and parsed.username is None and parsed.port in (None,443)


class ImageRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not trusted_image_url(newurl):
            raise ClientFailure('Redirection de l’image vers un domaine inconnu.', 502)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def local_image(record):
    inline = record.get('b64_json')
    url = record.get('url')
    if inline:
        try:
            return decode_image_value(inline)
        except ClientFailure:
            if not url or url == inline:
                raise
    return decode_image_value(url)


def decode_image_value(value):
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
        if images and k=='place':
            refs=refs[:max(1,5-min(2,len(images)))]
        refs.extend(images)
    full_prompt=prompt.strip()
    if descriptions: full_prompt+='\n\nRéférences de continuité à respecter :\n'+'\n'.join(descriptions)
    frame=payload.get('frame') if isinstance(payload.get('frame'),dict) else {}
    try: ratio=float(frame.get('w',1))/max(0.1,float(frame.get('h',1)))
    except (ValueError,TypeError,ZeroDivisionError):ratio=1.0
    size='1024x768' if ratio>1.2 else ('768x1024' if ratio<0.8 else '1024x1024')
    # Raw HTTP contract: https://agnes-ai.com/en/docs/agnes-image-25-flash
    req={'model':model,'prompt':full_prompt,'n':1,'size':size}
    if model.startswith('agnes-image-2.5'):
        req.update(size='1K', ratio='16:9' if frame.get('panorama') is True else '4:3' if ratio>1.2 else ('3:4' if ratio<0.8 else '1:1'))
    if refs:
        req['extra_body']={'image':list(dict.fromkeys(refs))[:5],'response_format':'b64_json'}
    else:
        req['return_base64']=True
    result=agnes_request(AGNES_GENERATE,key,req,max_bytes=14_000_000,timeout=110)
    if not isinstance(result,dict) or not isinstance(result.get('data'),list) or not result['data']:
        raise ClientFailure('Réponse de génération sans image. Vérifie le modèle.',502)
    record=result['data'][0]
    if not isinstance(record,dict):raise ClientFailure('Format d’image renvoyé non reconnu.',502)
    image=local_image(record)
    data=base64.b64decode(image.split(',',1)[1],validate=True)
    local=store_media(data,image[5:image.index(';')])
    # Fingerprint the final provider payload only. Credentials travel in a separate header.
    request_hash=hashlib.sha256(json.dumps(req,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {'request_hash':request_hash,'response_count':len(result['data']),'image':local,'input_copy':image in req.get('extra_body',{}).get('image',[]),'references_used':len(req.get('extra_body',{}).get('image',[])),'model':model}

# Keep the optional GPU runtime and weights across studio updates.
LOCAL_3D = Path(os.getenv('LOCALAPPDATA') or Path.home() / '.local' / 'share') / 'INKFORGE' / 'TripoSR'
GPU_LOCK = threading.Lock()
SOURCE_REV = '107cefdc244c39106fa830359024f6a2f1c78871'
WEIGHTS_REV = '5b521936b01fbe1890f6f9baed0254ab6351c04a'


def engine_python():
    return LOCAL_3D / 'runtime-v1' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


ENGINE_STEP = ''

def install_engine():
    global ENGINE_STEP
    if os.name != 'nt':
        raise ClientFailure('L’installation automatique TripoSR est prévue pour Windows.')
    if (LOCAL_3D / 'ready-v1').is_file() and engine_python().is_file():
        return
    LOCAL_3D.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, '-m', 'venv', str(LOCAL_3D / 'bootstrap')], check=True)
    ENGINE_STEP='Préparation de Python.'
    scripts = LOCAL_3D / 'bootstrap' / 'Scripts'
    subprocess.run([str(scripts / 'python'), '-m', 'pip', 'install', 'uv==0.8.22'], check=True)
    uv = str(scripts / 'uv.exe')
    subprocess.run([uv,'python','install','3.11'],check=True)
    if not engine_python().exists():
        subprocess.run([uv,'venv','--python','3.11',str(engine_python().parents[1])],check=True)
    pip = [uv,'pip','install','--python',str(engine_python())]
    ENGINE_STEP='Téléchargement des composants du moteur.'
    subprocess.run(pip+['--index-url','https://download.pytorch.org/whl/cu124','torch==2.6.0'],check=True)
    subprocess.run(pip+['numpy==1.26.4','opencv-python-headless==4.10.0.84','scikit-image==0.24.0',
        'transformers==4.35.0','omegaconf==2.3.0','einops==0.7.0','trimesh==4.0.5',
        'rembg==2.0.61','onnxruntime==1.20.1','imageio==2.36.1','pillow==10.4.0'],check=True)
    ENGINE_STEP='Installation des sources TripoSR.'
    url = 'https://api.github.com/repos/VAST-AI-Research/TripoSR/zipball/' + SOURCE_REV
    with urlopen(Request(url, headers={'User-Agent':'INKFORGE'}),timeout=120) as response:
        data = response.read(64_000_001)
    if hashlib.sha256(data).hexdigest() != 'a3db2d0d01c543611395a290029de1984b1cc6694f75440617bb87a7da1395d8':
        raise ClientFailure('La vérification du téléchargement TripoSR a échoué.')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in archive.namelist():
            relative = Path(*Path(name).parts[1:])
            if relative.parts and (relative.parts[0]=='tsr' or relative.name=='LICENSE') and not name.endswith('/'):
                target = LOCAL_3D / 'source' / relative
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(archive.read(name))
    ENGINE_STEP='Vérification des composants installés.'
    subprocess.run([str(engine_python()),str(Path(__file__).resolve()),'--check-3d'],check=True)
    (LOCAL_3D / 'ready-v1').touch()


def load_engine(check_only=False):
    import types
    import numpy as np
    import torch
    from skimage.measure import marching_cubes
    from PIL import Image
    import rembg
    from huggingface_hub import hf_hub_download
    # TripoSR expects X,Y,Z vertices from torchmcubes; skimage returns array-axis order.
    def surface(volume, level):
        verts, faces, _, _ = marching_cubes(volume.detach().cpu().numpy(), level, gradient_direction='ascent')
        return torch.from_numpy(verts[:, ::-1].copy()), torch.from_numpy(faces.copy().astype('int64'))
    adapter = types.ModuleType('torchmcubes')
    adapter.marching_cubes = surface
    sys.modules['torchmcubes'] = adapter
    sys.path.insert(0,str(LOCAL_3D / 'source'))
    from tsr.system import TSR
    from tsr.utils import remove_background, resize_foreground
    if check_only:
        return
    if not torch.cuda.is_available():
        raise ClientFailure('CUDA indisponible. Mets à jour le pilote NVIDIA puis relance INKFORGE.')
    free,total=torch.cuda.mem_get_info()
    budget=min(int(total*0.90),free-256*1024**2)
    if budget<=0:raise ClientFailure('Mémoire vidéo disponible insuffisante.')
    torch.cuda.set_per_process_memory_fraction(budget/total)
    for name in ('config.yaml','model.ckpt'):
        path = hf_hub_download('stabilityai/TripoSR',name,revision=WEIGHTS_REV)
    model = TSR.from_pretrained(str(Path(path).parent),'config.yaml','model.ckpt').eval().to('cuda')
    model.renderer.set_chunk_size(2048)
    background = rembg.new_session('u2netp',providers=['CPUExecutionProvider'])
    def reconstruct(folder,quality):
        torch.cuda.reset_peak_memory_stats()
        image=remove_background(Image.open(folder/'input').convert('RGBA'),background)
        image=resize_foreground(image,0.85)
        bg=Image.new('RGB',image.size,(128,128,128))
        bg.paste(image,mask=image.getchannel('A'))
        with torch.inference_mode():
            scene=model([bg],device='cuda')
            mesh=model.extract_mesh(scene,True,resolution=96 if quality=='preview' else 160)[0]
            mesh.export(str(folder/'model.glb'))
            if quality=='final':
                for i,view in enumerate(model.render(scene,4,height=256,width=256)[0]):
                    view.convert('RGB').save(folder/f'view-{i}.jpg',quality=88)
        torch.cuda.synchronize()
        return round(torch.cuda.max_memory_reserved()/1048576)
    return reconstruct


def engine_loop(reader,writer,loader):
    reconstruct=None
    for line in reader:
        try:
            job=json.loads(line)
            cold=reconstruct is None
            if cold:reconstruct=loader()
            peak=reconstruct(Path(job['folder']),job['quality'])
            reply={'cold':cold,'gpu_mib':peak}
        except Exception as exc:
            print(str(exc),file=sys.stderr)
            reply={'error':str(exc) if isinstance(exc,ClientFailure) else 'Reconstruction interrompue. Vérifie le pilote et la mémoire vidéo disponible.'}
        print(json.dumps(reply),file=writer,flush=True)
        if 'error' in reply:return


class WarmEngine:
    def __init__(self,idle=300):
        self.lock=threading.Lock()
        self.process=None
        self.timer=None
        self.idle=idle

    def _stop(self):
        if self.timer:
            self.timer.cancel()
            self.timer=None
        if self.process:
            self.process.kill()
            self.process.wait()
            self.process.stdin.close()
            self.process.stdout.close()
            self.process=None

    def stop(self):
        with self.lock:self._stop()

    def expire(self):
        with self.lock:
            if self.timer is threading.current_thread():self._stop()

    def run(self,folder,quality):
        with self.lock:
            if self.timer:self.timer.cancel()
            self.timer=None
            start=time.monotonic()
            try:
                if self.process is None or self.process.poll() is not None:
                    self._stop()
                    self.process=subprocess.Popen([str(engine_python()),str(Path(__file__).resolve()),'--worker-3d'],
                        stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,encoding='utf-8')
                self.process.stdin.write(json.dumps({'folder':str(folder.resolve()),'quality':quality})+'\n')
                self.process.stdin.flush()
                result=json.loads(self.process.stdout.readline())
                if 'error' in result:raise ClientFailure(result['error'])
            except BaseException:
                self._stop()
                raise
            self.timer=threading.Timer(self.idle,self.expire)
            self.timer.daemon=True
            self.timer.start()
            return {**result,'seconds':round(time.monotonic()-start,2)}

warm_engine=WarmEngine()
atexit.register(warm_engine.stop)


def build_character_model(payload):
    global ENGINE_STEP
    image = payload.get('image')
    if isinstance(image,str) and media_pattern.fullmatch(image):
        path,kind=media_path(image)
        if not path.is_file():
            raise ClientFailure('La référence du personnage est introuvable.')
        data=path.read_bytes()
    else:
        if not isinstance(image,str) or not re.fullmatch(r'data:image/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=]+',image):
            raise ClientFailure('Enregistre une référence PNG, JPEG ou WebP dans la fiche.')
        data=base64.b64decode(image.split(',',1)[1],validate=True)
    quality=payload.get('quality','final')
    if quality not in ('preview','final'):raise ClientFailure('Qualité 3D inconnue.')
    ident = hashlib.sha256(data if quality=='final' else b'preview-96:'+data).hexdigest()
    metrics={'cached':True}
    models = WORK / 'models'
    target = models / ident
    if not (target/'model.glb').exists():
        if not (LOCAL_3D/'ready-v1').is_file():
            raise ClientFailure('Installe le moteur TripoSR dans le Studio 3D.')
        models.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=models) as temporary:
            stage = Path(temporary)/'result'
            stage.mkdir()
            (stage/'input').write_bytes(data)
            ENGINE_STEP='Reconstruction du modèle et préparation des vues. Au premier essai, les poids du moteur sont téléchargés.'
            metrics=warm_engine.run(stage,quality)
            (stage/'input').unlink()
            stage.rename(target)
    return {'id':ident,**metrics}



# The portable studio keeps all project data under one directory on the PC.
# The TripoSR environment and downloaded weights have their own lifetime.
BASE = HTML.resolve().parent
WORK = BASE / '_inkforge_travail'
RESCUE = BASE / '_secours_inkforge.zip'
TRANSACTION = BASE / '.inkforge-transaction'
LEGACY_BACKUP = BASE / '_backup_version_precedente'
LEGACY_BROWSER = BASE / '.inkforge-navigateur.json'
PROGRAM = ('INKFORGE.html', 'serveur_inkforge.py', 'version.json')
OPTIONAL_PROGRAM = ('LANCER_INKFORGE.cmd', 'LISEZ_MOI.txt', 'update_source.json')
def installed_version():
    try:
        return version_data()['version']
    except (OSError,ValueError,KeyError):
        return None

BOOT_VERSION = installed_version()
WORK_LOCK = threading.RLock()
pending_operations = 0
MEDIA_LIMIT = 64 * 1024 * 1024
media_pattern = re.compile(r'/media/([a-f0-9]{64})\.([a-z0-9]+)')
media_types = {'png':'image/png','jpg':'image/jpeg','webp':'image/webp','gif':'image/gif',
               'svg':'image/svg+xml','bmp':'image/bmp','avif':'image/avif','ico':'image/x-icon',
               'tif':'image/tiff','heic':'image/heic','jfif':'image/pjpeg','apng':'image/apng',
               'heif':'image/heif','jxl':'image/jxl'}
EMPTY_WORK = {'revision':'0', 'active':'', 'projects':{}, 'histories':{}, 'settings':{}}


def write_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as out:
        tmp = Path(out.name)
    try:
        with tmp.open('wb') as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def json_bytes(data):
    return json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def read_workspace():
    path = WORK / 'state.json'
    return json.loads(path.read_bytes()) if path.exists() else dict(EMPTY_WORK)


def require_live():
    if TRANSACTION.exists() or version_data()['version'] != BOOT_VERSION:
        raise ClientFailure('La version du studio a changé. Ferme la fenêtre noire et relance INKFORGE.', 409)


def request_epoch(handler):
    require_same_origin(handler.headers)
    require_live()
    if handler.headers.get('X-Inkforge-Version') != BOOT_VERSION:
        raise ClientFailure('Recharge INKFORGE avant de continuer.', 409)


def read_body(handler, maximum):
    try:
        size = int(handler.headers.get('Content-Length', ''))
    except ValueError:
        raise ClientFailure('Taille de la requête manquante.')
    if not 0 < size <= maximum:
        raise ClientFailure('La demande dépasse la taille acceptée.', 413)
    data = handler.rfile.read(size)
    if len(data) != size:
        raise ClientFailure('Transfert interrompu avant la fin.')
    return data


def read_json(handler, maximum):
    if handler.headers.get_content_type() != 'application/json':
        raise ClientFailure('Format JSON attendu.', 415)
    value = json.loads(read_body(handler, maximum))
    if not isinstance(value, dict):
        raise ClientFailure('Demande JSON invalide.')
    return value


def store_media(raw, mime):
    ext = next((k for k, v in media_types.items() if v == mime), None)
    if not ext:
        raise ClientFailure('Format d’image inconnu. Utilise une image PNG, JPEG ou WebP.', 415)
    name = hashlib.sha256(raw).hexdigest() + '.' + ext
    path = WORK / 'media' / name
    if not path.exists():
        write_atomic(path, raw)
    return '/media/' + name


def media_path(url):
    match = media_pattern.fullmatch(url) if isinstance(url, str) else None
    if not match or match[2] not in media_types:
        raise ClientFailure('Adresse de média local invalide.')
    return WORK / 'media' / (match[1] + '.' + match[2]), media_types[match[2]]


def save_workspace(data):
    current = read_workspace()
    if data.get('revision') != current['revision']:
        raise ClientFailure('Le projet a été modifié dans un autre onglet. Exporte ton travail puis recharge INKFORGE.', 409)
    if not isinstance(data.get('projects'),dict) or not isinstance(data.get('histories'),dict) or not isinstance(data.get('active'),str):
        raise ClientFailure('Projet incomplet. La sauvegarde précédente est conservée.')
    state = {k:data.get(k,{}) for k in EMPTY_WORK}
    state['revision'] = uuid.uuid4().hex
    write_atomic(WORK / 'state.json', json_bytes(state))
    return {'revision':state['revision']}


@contextmanager
def working_operation():
    global pending_operations
    with WORK_LOCK:
        require_live()
        pending_operations += 1
    try:
        yield
    finally:
        with WORK_LOCK:
            pending_operations -= 1


def reject_busy():
    require_live()
    if pending_operations:
        raise ClientFailure('Une génération ou une opération 3D est en cours. Attends sa fin.',409)


# Assign the ticket before calling Agnes. A lost browser connection can only poll this
# ticket. It never repeats the paid request.
generation_jobs = {}
generation_keys=set()
generation_starts=[]
generation_pause_until=0
MIN_QUOTA_PAUSE=60
IMAGE_RPM=20  # Shared local ceiling for 1K images, independent of the number of keys.


def generation_ticket(payload, key):
    global pending_operations
    key_id=hashlib.sha256(key.encode()).digest()
    ticket = payload.get('requestId')
    if not isinstance(ticket,str) or not re.fullmatch(r'[0-9a-f-]{36}',ticket):
        raise ClientFailure('Identifiant de génération invalide.')
    with WORK_LOCK:
        require_live()
        now = time.monotonic()
        for ident,job in list(generation_jobs.items()):
            if job.get('ended',now) < now-3600:
                del generation_jobs[ident]
        if ticket in generation_jobs:
            return {'ticket':ticket}
        if sum('ended' not in j for j in generation_jobs.values())>=4:
            return {'ticket':ticket,'deferred':1}
        generation_starts[:]=[stamp for stamp in generation_starts if stamp>now-60]
        wait=generation_pause_until-now
        if len(generation_starts)>=IMAGE_RPM:
            wait=max(wait,60+generation_starts[0]-now)
        if wait>0 or key_id in generation_keys:
            return {'ticket':ticket,'deferred':max(1,int(wait)+1)}
        generation_starts.append(now)
        generation_keys.add(key_id)
        generation_jobs[ticket]={'pending':True}
        pending_operations += 1
    def run():
        global pending_operations,generation_pause_until
        try:
            result=send_generate(payload,key)
        except ClientFailure as exc:
            status=getattr(exc,'provider_status',None)
            delay=getattr(exc,'retry_after',MIN_QUOTA_PAUSE)
            result={'error':str(exc),'provider_status':status,'retry_after':max(MIN_QUOTA_PAUSE,delay),'uncertain':status is None and 'délai' in str(exc)}
            if status in (402,429):
                with WORK_LOCK:
                    generation_pause_until=max(generation_pause_until,time.monotonic()+max(MIN_QUOTA_PAUSE,delay))
        except Exception:
            result={'error':'Le relais n’a pas pu enregistrer le résultat. Vérifie l’espace disque et la fenêtre noire.'}
        finally:
            with WORK_LOCK:
                generation_keys.discard(key_id)
                generation_jobs[ticket]={**result,'ended':time.monotonic()}
                pending_operations-=1
    try:
        threading.Thread(target=run,daemon=True).start()
    except RuntimeError:
        with WORK_LOCK:
            del generation_jobs[ticket]
            generation_keys.discard(key_id)
            pending_operations-=1
        raise
    return {'ticket':ticket}


def backup_files(program_dir, work, legacy_models=None):
    for name in PROGRAM + OPTIONAL_PROGRAM:
        source = program_dir / name
        if not source.exists() and name in OPTIONAL_PROGRAM:
            source = BASE / name
        if source.is_file():
            yield 'app/' + name, source
        elif name in PROGRAM:
            raise ValueError('La version à sauvegarder est incomplète.')
    for prefix, folder in [('travail', work), ('anciens-modeles', legacy_models)]:
        if folder and folder.is_dir():
            for source in sorted(folder.rglob('*')):
                if source.is_file() and not source.is_symlink():
                    yield prefix + '/' + source.relative_to(folder).as_posix(), source


def copy_digest(source, target=None):
    digest = hashlib.sha256()
    for block in iter(lambda:source.read(1024*1024), b''):
        digest.update(block)
        if target is not None:
            target.write(block)
    return digest.hexdigest()


def inspect_rescue(archive, extract=None):
    manifest = json.loads(archive.read('manifest.json'))
    entries = manifest['files']
    names = archive.namelist()
    if (len(names) != len(set(names)) or set(entries) | {'manifest.json'} != set(names)
            or not all('app/'+name in entries for name in PROGRAM)):
        raise ValueError('Sauvegarde incomplète.')
    for name, checksum in entries.items():
        parts = name.split('/')
        allowed = (name in {'app/'+n for n in PROGRAM+OPTIONAL_PROGRAM}
                   or name == 'navigateur.json' or parts[0] in ('travail','anciens-modeles'))
        if not allowed or any(not re.fullmatch(r'[A-Za-z0-9_.-]+', p) or p in ('.','..') for p in parts):
            raise ValueError('Fichier de sauvegarde inattendu.')
        with archive.open(name) as source:
            if extract:
                dest = extract.joinpath(*parts)
                dest.parent.mkdir(parents=True, exist_ok=True)
                with dest.open('wb') as target:
                    actual = copy_digest(source, target)
            else:
                actual = copy_digest(source)
        if actual != checksum:
            raise ValueError('Sauvegarde endommagée. Les données actuelles sont conservées.')
    version = json.loads(archive.read('app/version.json'))['version']
    if version != manifest['version'] or not re.fullmatch(r'\d+\.\d+\.\d+',version):
        raise ValueError('Version de sauvegarde incohérente.')
    return manifest


def create_rescue(path, program_dir, work, browser=None, legacy_models=None):
    version = json.loads((program_dir/'version.json').read_bytes())['version']
    hashes = {}
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for name, src in backup_files(program_dir, work, legacy_models):
            with src.open('rb') as source, archive.open(name, 'w', force_zip64=True) as dest:
                hashes[name] = copy_digest(source, dest)
        if browser is not None:
            data = json_bytes(browser)
            archive.writestr('navigateur.json',data)
            hashes['navigateur.json'] = hashlib.sha256(data).hexdigest()
        archive.writestr('manifest.json', json_bytes({'version':version,'files':hashes}))
    with path.open('r+b') as saved:
        os.fsync(saved.fileno())
    with zipfile.ZipFile(path) as archive:
        inspect_rescue(archive)


def backup_version():
    if not RESCUE.is_file():
        return None
    try:
        with zipfile.ZipFile(RESCUE) as archive:
            return json.loads(archive.read('manifest.json'))['version']
    except (OSError,ValueError,KeyError,zipfile.BadZipFile):
        return None


def remove_path(path):
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def finish_transaction():
    # Take the journal out of the recovery path before removing its contents.
    finished = BASE / ('.inkforge-fini-' + uuid.uuid4().hex)
    TRANSACTION.rename(finished)
    shutil.rmtree(finished, ignore_errors=True)


def recover_transaction():
    if not TRANSACTION.is_dir():
        return
    journal = json.loads((TRANSACTION/'journal.json').read_bytes())
    candidate = TRANSACTION / 'secours.zip'
    committed = ((journal['update'] and not candidate.exists()) or (TRANSACTION/'valide').exists())
    if not committed:
        for name, existed in reversed(list(journal['paths'].items())):
            original = TRANSACTION/'old'/name
            target = BASE/name
            if original.exists():
                remove_path(target)
                os.replace(original,target)
            elif not existed:
                remove_path(target)
        if journal['update'] and not RESCUE.exists():
            # No earlier rescue exists. Keep the already verified copy of the current work.
            os.replace(candidate,RESCUE)
    finish_transaction()


def commit_files(stage, names, update):
    (stage/'old').mkdir()
    paths = {n:(BASE/n).exists() for n in names}
    write_atomic(stage/'journal.json',json_bytes({'paths':paths,'update':update}))
    stage.rename(TRANSACTION)
    try:
        for name, existed in paths.items():
            target = BASE/name
            incoming = TRANSACTION/'new'/name
            # cmd.exe can keep the launcher open while Python serves an update.
            if name=='LANCER_INKFORGE.cmd' and existed and incoming.is_file() and target.read_bytes()==incoming.read_bytes():
                continue
            if existed:
                os.replace(target, TRANSACTION/'old'/name)
            if incoming.exists():
                os.replace(incoming, target)
        if update:
            os.replace(TRANSACTION/'secours.zip', RESCUE)
        else:
            write_atomic(TRANSACTION/'valide',b'1')
    except BaseException:
        recover_transaction()
        raise
    try:
        finish_transaction()
    except OSError:
        # The commit is durable. Next launch can finish removing the previous files.
        pass


def valid_legacy_key(key, version):
    prefix = 'inkforge-experiments/'+version+'/'
    return (key in (prefix+'projects',prefix+'active','inkforge-tooltips-enabled','inkforge-ai-model')
            or key.startswith(prefix+'versions/') and bool(re.fullmatch(r'[A-Za-z0-9_-]+',key[len(prefix+'versions/'):])))


def bootstrap_workspace(data):
    # 2.4.2 can copy only three program files. Complete this rescue before clearing its browser records.
    previous = None
    legacy_version = LEGACY_BACKUP / 'version.json'
    if legacy_version.is_file():
        previous = json.loads(legacy_version.read_bytes())['version']
    browser = data.get('legacy',{})
    if not isinstance(browser,dict):
        raise ValueError('Sauvegarde du navigateur illisible.')
    if previous and previous != BOOT_VERSION:
        if not all(valid_legacy_key(k,previous) and isinstance(v,str) for k,v in browser.items()):
            raise ValueError('Données de migration inattendues.')
        marker = WORK / 'migration.json'
        if not marker.exists():
            models = LOCAL_3D/'models'
            if backup_version()==previous:
                # A power cut may have happened after replacement and before the marker.
                with zipfile.ZipFile(RESCUE) as saved:
                    inspect_rescue(saved)
                    existing=json.loads(saved.read('navigateur.json'))
                if not all(existing.get(k)==v for k,v in browser.items()):
                    raise ClientFailure('Le projet du navigateur diffère de la sauvegarde. Rouvre le profil utilisé pour la mise à jour.')
            else:
                with tempfile.TemporaryDirectory(dir=BASE) as tmp:
                    archive=Path(tmp)/'secours.zip'
                    create_rescue(archive,LEGACY_BACKUP,None,browser,models)
                    os.replace(archive,RESCUE)
            write_atomic(marker,json_bytes({'previous':previous}))
        # A validated rescue now exists. Retry this housekeeping on a later launch if necessary.
        if backup_version() != previous:
            raise ValueError('La copie de secours de la version précédente est indisponible.')
        shutil.rmtree(LOCAL_3D/'models', ignore_errors=True)
        shutil.rmtree(LEGACY_BACKUP, ignore_errors=True)
        return {'state':read_workspace(), 'cleared':list(browser), 'previous':previous}
    marker=WORK/'migration.json'
    if marker.is_file() and browser:
        previous=json.loads(marker.read_bytes())['previous']
        with zipfile.ZipFile(RESCUE) as saved:
            records=json.loads(saved.read('navigateur.json'))
        if not all(records.get(k)==v for k,v in browser.items()):
            raise ValueError('Le navigateur contient un autre projet ancien. Ses données restent sur ce PC.')
        return {'state':read_workspace(),'cleared':list(browser),'previous':previous}
    return {'state':read_workspace(),'cleared':[]}


def restore_backup(offline=False):
    with WORK_LOCK:
        if not offline:
            reject_busy()
        if not RESCUE.is_file():
            raise ValueError('Aucune version de secours disponible.')
        with tempfile.TemporaryDirectory(dir=BASE) as tmp:
            stage = Path(tmp)/'stage'
            stage.mkdir()
            files = Path(tmp)/'extracted'
            with zipfile.ZipFile(RESCUE) as archive:
                info = inspect_rescue(archive,files)
            if not offline and info['version'] == BOOT_VERSION:
                raise ValueError('Cette version est déjà installée.')
            new = stage/'new'
            (files/'app').rename(new)
            names = [n for n in PROGRAM+OPTIONAL_PROGRAM if (new/n).exists() or n=='update_source.json']
            if (files/'travail').exists():
                (files/'travail').rename(new/WORK.name)
            if (files/'navigateur.json').exists():
                (files/'navigateur.json').rename(new/LEGACY_BROWSER.name)
                # Legacy models are immutable and content addressed. An interrupted copy is retryable.
                for src in (files/'anciens-modeles').rglob('*'):
                    if src.is_file():
                        dest = LOCAL_3D/'models'/src.relative_to(files/'anciens-modeles')
                        write_atomic(dest,src.read_bytes())
            commit_files(stage,names+[WORK.name,LEGACY_BROWSER.name],False)
        return {'version':info['version'], 'legacy':LEGACY_BROWSER.exists()}


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
        if kind.startswith('image/'):
            self.send_header("Content-Security-Policy","sandbox; default-src 'none'; style-src 'unsafe-inline'")
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):
            pass

    def do_GET(self):
        if media_pattern.fullmatch(self.path):
            path, mime = media_path(self.path)
            try:
                return self.send_data(200,path.read_bytes(),mime)
            except FileNotFoundError:
                return self.send_data(404,{'error':'Image absente du projet.'})
        if self.path == '/work/status':
            previous = LEGACY_BACKUP / 'version.json'
            marker=WORK/'migration.json'
            old=(json.loads(previous.read_bytes())['version'] if previous.is_file() else
                 json.loads(marker.read_bytes())['previous'] if marker.is_file() else None)
            return self.send_data(200,{'version':BOOT_VERSION,'previous':old,'rescue':backup_version()})
        if self.path in ("/", "/INKFORGE.html"):
            version = version_data()['version']
            html = re.sub(rb'(<meta name="inkforge-version" content=")[^"]*', lambda match: match[1]+version.encode('ascii'), HTML.read_bytes(), count=1)
            self.send_data(200, html, "text/html; charset=utf-8")
        elif self.path == "/updates/status":
            self.send_data(200, update_status())
        elif self.path == '/3d/status':
            self.send_data(200,{'step':ENGINE_STEP if GPU_LOCK.locked() else '', 'ready':(LOCAL_3D/'ready-v1').is_file() and engine_python().is_file()})
        elif re.fullmatch(r'/3d/models/[a-f0-9]{64}',self.path):
            model=WORK/'models'/self.path.rsplit('/',1)[1]/'model.glb'
            if model.is_file():
                self.send_data(200,model.read_bytes(),'model/gltf-binary')
            else:
                self.send_data(404,{'error':'Modèle absent sur ce PC.'})
        elif self.path == "/health":
            self.send_data(200, {"configured": True, "status": "running"})
        else:
            self.send_data(404, {"error": "Page introuvable"})

    def do_POST(self):
        try:
            if self.path == '/ai/result':
                request_epoch(self)
                data=read_json(self,1024)
                with WORK_LOCK:
                    result=generation_jobs.get(data.get('ticket'))
                if not result:
                    raise ClientFailure('Génération introuvable. Vérifie que le relais est resté ouvert.',404)
                return self.send_data(200,{k:v for k,v in result.items() if k!='ended'})
            if self.path in ('/work/open','/work/save','/work/media','/work/reset-complete','/updates/restore'):
                with WORK_LOCK:
                    request_epoch(self)
                    if self.path == '/work/reset-complete':
                        (WORK/'migration.json').unlink(missing_ok=True)
                        return self.send_data(200,{'ok':True})
                    if self.path == '/work/media':
                        return self.send_data(201,{'url':store_media(read_body(self,MEDIA_LIMIT),self.headers.get_content_type())})
                    if self.path == '/updates/restore':
                        result = restore_backup()
                        if result['legacy']:
                            result['browser'] = json.loads(LEGACY_BROWSER.read_bytes())
                        return self.send_data(200,result)
                    data = read_json(self,32*1024*1024)
                    result = bootstrap_workspace(data) if self.path=='/work/open' else save_workspace(data)
                    return self.send_data(200,result)
            if self.path == '/updates/browser-restored':
                require_same_origin(self.headers)
                LEGACY_BROWSER.unlink(missing_ok=True)
                return self.send_data(200,{'ok':True})
            if self.path in ('/ai/generate','/3d/install','/3d/build'):
                request_epoch(self)
                with working_operation():
                    return self.application_post()
            if self.path == '/updates/config':
                with WORK_LOCK:
                    request_epoch(self)
                    return self.application_post()
            if self.path in ('/updates/auto-install','/updates/install'):
                request_epoch(self)
            return self.application_post()
        except ClientFailure as exc:
            return self.send_data(exc.status,{'error':str(exc)})
        except (OSError,ValueError,KeyError,zipfile.BadZipFile):
            return self.send_data(400,{'error':'Lecture ou écriture impossible sur le PC. Vérifie l’espace disque et les droits du dossier INKFORGE.'})

    def application_post(self):
        if self.path in ('/3d/install','/3d/build'):
            try:
                require_same_origin(self.headers)
                size=int(self.headers.get('Content-Length',0))
                if not 0<size<12_000_000 or self.headers.get_content_type()!='application/json':
                    raise ClientFailure('Demande 3D invalide.')
                payload=json.loads(self.rfile.read(size))
                if not isinstance(payload,dict):raise ClientFailure('Demande 3D invalide.')
                if not GPU_LOCK.acquire(blocking=False):raise ClientFailure('Une opération 3D est déjà en cours.',409)
                try:
                    if self.path=='/3d/install':
                        install_engine()
                        return self.send_data(200,{'ready':True})
                    return self.send_data(200,build_character_model(payload))
                finally:
                    GPU_LOCK.release()
            except ClientFailure as exc:return self.send_data(exc.status,{'error':str(exc)})
            except (ValueError,OSError,subprocess.SubprocessError) as exc:
                print('Erreur moteur 3D :',exc)
                return self.send_data(400,{'error':'Opération 3D interrompue. Consulte la fenêtre noire pour le détail puis réessaie.'})
        if self.path in ('/ai/models','/ai/check','/ai/generate'):
            try:
                payload,key=parse_small_json(self)
                if self.path=='/ai/generate':
                    if 'requestId' in payload:
                        return self.send_data(202,generation_ticket(payload,key))
                    # Older clients expect a synchronous result. Share admission with ticketed clients.
                    ticket=str(uuid.uuid4())
                    admission=generation_ticket({**payload,'requestId':ticket},key)
                    if admission.get('deferred'):
                        raise ClientFailure('Capacité ou quota temporairement atteint. Réessaie plus tard.',429)
                    while True:
                        with WORK_LOCK:
                            result=generation_jobs[ticket]
                        if not result.get('pending'):break
                        time.sleep(0.25)
                    if 'error' in result:raise ClientFailure(result['error'],502)
                    return self.send_data(200,{k:v for k,v in result.items() if k!='ended'})
                models=image_models(agnes_request(AGNES,key,timeout=16))
                if self.path=='/ai/models':return self.send_data(200,{'data':models})
                selected=payload.get('model')
                if selected and selected not in {m['id'] for m in models}:
                    raise ClientFailure('La clé fonctionne, mais le modèle choisi n’est pas disponible pour la génération.')
                return self.send_data(200,{'connected':True,'models':len(models),'message':'Relais accessible, clé Agnes AI valide, '+str(len(models))+' modèle(s) image détecté(s).'+(' Modèle sélectionné accessible.' if selected else ' Sélectionne ensuite un modèle.')})
            except ClientFailure as exc:
                return self.send_data(exc.status,{'error':str(exc),'provider_status':getattr(exc,'provider_status',None),'retry_after':getattr(exc,'retry_after',MIN_QUOTA_PAUSE)})
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
            try:
                image_models(agnes_request(AGNES,key.strip(),timeout=10))
                return self.send_data(200, {"connected": True, "reason": "Liste des modèles accessible"})
            except ClientFailure as exc:
                return self.send_data(200, {"connected": False, "reason": str(exc)})
        except (ValueError, TypeError, KeyError):
            return self.send_data(400, {"connected": None, "reason": "Requête invalide"})

def recovery_tools(code=None):
    # 2.4.2 updates only the original three files. Materialize the independent
    # recovery entry point here as well as in fresh installations.
    helper = BASE/'.inkforge-recuperation.py'
    code = code or (BASE/'serveur_inkforge.py').read_bytes()
    if not helper.exists() or helper.read_bytes()!=code:
        write_atomic(helper,code)
    cmd = BASE/'RESTAURER_INKFORGE.cmd'
    script = b'@echo off\r\ncd /d "%~dp0"\r\nwhere py >nul 2>nul\r\nif %errorlevel%==0 (py -3 .inkforge-recuperation.py --restore) else (python .inkforge-recuperation.py --restore)\r\nif errorlevel 1 pause\r\n'
    if not cmd.exists() or cmd.read_bytes()!=script:
        write_atomic(cmd,script)


def maintenance_server(package=None):
    # The first protected update must read 2.4.2 browser data at its original origin.
    # The same standalone page can finish restoring that data if the studio cannot open.
    restore = package is None
    label = 'Restaurer la version de secours' if restore else 'Installer la mise à jour'
    page_html = """<!doctype html><html lang="fr"><meta charset="utf-8"><title>INKFORGE Studio</title>
<style>body{background:#121824;color:#f7f7fb;font:18px system-ui;max-width:40em;margin:12vh auto;padding:20px}button{font:inherit;background:#aba6ff;padding:12px;border:0;border-radius:8px}p{line-height:1.5}</style>
<h1>INKFORGE Studio</h1><p id="description"></p><button></button><p role="status" id="status"></p>
<script>
const version=VERSION,restore=RESTORE,button=document.querySelector('button'),statusText=document.querySelector('#status');
document.querySelector('#description').textContent=restore?'La restauration remplacera le travail de la version actuelle par sa copie de secours.':'Utilise le navigateur et le profil où tu as créé tes personnages. Le studio va vérifier la copie de tes projets avant l’installation.';
button.textContent=LABEL;
const keyList=()=>Object.fromEntries(Object.entries(localStorage).filter(([k])=>k.startsWith('inkforge-experiments/'+version+'/')||k==='inkforge-tooltips-enabled'));
if(!restore){const projects=JSON.parse(localStorage.getItem('inkforge-experiments/'+version+'/projects')||'{}');const names=Object.values(projects).flatMap(p=>(p.characters||[]).map(c=>c.name)).slice(0,8);
 document.querySelector('#description').append(' Projets enregistrés dans ce profil : '+Object.keys(projects).length+'.'+(names.length?' Personnages : '+names.join(', ')+'.':''));}
async function call(path,data){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const v=await r.json();if(!r.ok)throw Error(v.error);return v}
button.onclick=async()=>{button.disabled=true;try{
 const legacy=keyList();
 if(!restore && !Object.hasOwn(legacy,'inkforge-experiments/'+version+'/projects') && !confirm('Aucun projet 2.4.2 enregistré dans ce profil de navigateur. Continuer avec une sauvegarde vide ?')){button.disabled=false;return}
 const model=sessionStorage.getItem('inkforge-ai-model');if(model!==null)legacy['inkforge-ai-model']=model;
 const r=await call('/maintenance',{legacy});
 if(r.browser){for(const [k,v] of Object.entries(r.browser)){const dest=k==='inkforge-ai-model'?sessionStorage:localStorage;dest.setItem(k,v);if(dest.getItem(k)!==v)throw Error('Restauration du navigateur interrompue. Relance RESTAURER_INKFORGE.cmd.')}}
 for(const k of r.cleared||[]) (k==='inkforge-ai-model'?sessionStorage:localStorage).removeItem(k);
 await call('/maintenance/terminee',{});
 statusText.textContent='Version '+r.version+' prête. Ferme cet onglet et relance LANCER_INKFORGE.cmd dans ton dossier habituel.';
}catch(e){statusText.textContent=e.message;button.disabled=false}};
</script></html>""".replace('RESTORE',json.dumps(restore)).replace('LABEL',json.dumps(label))
    class Maintenance(Handler):
        def do_GET(self):
            if self.path=='/':
                return self.send_data(200,page_html.replace('VERSION',json.dumps(BOOT_VERSION)).encode(),'text/html; charset=utf-8')
            self.send_data(404,{})
        def do_POST(self):
            try:
                require_same_origin(self.headers)
                if self.path=='/maintenance/terminee':
                    LEGACY_BROWSER.unlink(missing_ok=True)
                    self.send_data(200,{'ok':True})
                    threading.Thread(target=self.server.shutdown,daemon=True).start()
                    return
                if self.path!='/maintenance':
                    return self.send_data(404,{})
                data=read_json(self,32*1024*1024)
                with WORK_LOCK:
                    if restore:
                        if LEGACY_BROWSER.exists():
                            result={'version':version_data()['version']}
                        else:
                            result=restore_backup(offline=True)
                        if LEGACY_BROWSER.exists():
                            result['browser']=json.loads(LEGACY_BROWSER.read_bytes())
                    else:
                        if BOOT_VERSION!='2.4.2':
                            raise ValueError('Cet assistant est réservé au premier passage depuis la version 2.4.2.')
                        browser=data.get('legacy')
                        if not isinstance(browser,dict) or not all(valid_legacy_key(k,BOOT_VERSION) and isinstance(v,str) for k,v in browser.items()):
                            raise ValueError('Données du navigateur incompatibles.')
                        with zipfile.ZipFile(io.BytesIO(package)) as files:
                            recovery_tools(files.read('serveur_inkforge.py'))
                        result={'version':install_zip(package,legacy_browser=browser),'cleared':list(browser)}
                        shutil.rmtree(LOCAL_3D/'models',ignore_errors=True)
                    self.send_data(200,result)
            except (OSError,ValueError,ClientFailure,zipfile.BadZipFile) as exc:
                self.send_data(400,{'error':str(exc)})
    serve(Maintenance)


def serve(handler):
    global BOOT_VERSION
    try:
        server = ThreadingHTTPServer((HOST, PORT), handler)
    except OSError:
        print("Le port 8765 est occupé. Ferme la fenêtre noire INKFORGE et relance.")
        raise SystemExit(1)
    with server:
        recover_transaction()
        BOOT_VERSION=installed_version()
        if handler is Handler:
            if not BOOT_VERSION:
                raise SystemExit('Lance RESTAURER_INKFORGE.cmd pour restaurer la version de secours.')
            recovery_tools()
        print(f"INKFORGE est disponible sur http://{HOST}:{PORT}")
        print("Laisse cette fenêtre ouverte pendant l’utilisation.")
        threading.Timer(1, lambda: webbrowser.open(f"http://{HOST}:{PORT}/")).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    if '--check-3d' in sys.argv:
        load_engine(check_only=True)
        sys.exit(0)
    if '--worker-3d' in sys.argv:
        # Native dependencies can print to stdout. Reserve a separate descriptor for replies.
        with os.fdopen(os.dup(sys.stdout.fileno()),'w',encoding='utf-8') as replies:
            os.dup2(sys.stderr.fileno(),sys.stdout.fileno())
            engine_loop(sys.stdin,replies,load_engine)
        sys.exit(0)
    if '--restore' in sys.argv:
        maintenance_server()
    else:
        serve(Handler)
