"""Two real loopback HTTP servers. Only the paid Agnes service is simulated."""
import base64
import hashlib
import json
import os
import random
import struct
import sys
import threading
import zlib
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

folder = Path(sys.argv[1]).resolve()
sys.path.insert(0,str(folder))
import serveur_inkforge as app


def png(seed, width=960, view=None, wall=None):
    pixels = random.Random(seed).randbytes(width*width*3)
    if wall:
        pixels=bytes(wall)*(width*width//2)+pixels[width*width*3//2:]
    if view:
        # A recognizable orientation marker in the test raster: eyes, hair and profile nose.
        pixels=bytearray(pixels)
        def box(x,y,w,h,color):
            for row in range(y,y+h):
                start=3*(row*width+x)
                pixels[start:start+3*w]=bytes(color)*w
        box(0,0,100,100,(255,255,255))
        box(25,20,50,65,(55,32,20) if view=='back' else (220,170,120))
        if view in ('left','right'):
            box(15 if view=='left' else 75,50,10,10,(220,170,120))
        if view in ('front','left'):box(32,40,6,6,(0,0,0))
        if view in ('front','right'):box(62,40,6,6,(0,0,0))
    def chunk(name,data):
        return struct.pack('>I',len(data))+name+data+struct.pack('>I',zlib.crc32(name+data))
    scanlines = b''.join(b'\0'+pixels[i:i+width*3] for i in range(0,len(pixels),width*3))
    return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,width,8,2,0,0,0))
            +chunk(b'IDAT',zlib.compress(scanlines,1))+chunk(b'IEND',b''))


class Provider(BaseHTTPRequestHandler):
    def log_message(self,*args):
        pass

    def reply(self,data,status=200):
        body=json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        assert self.path=='/v1/models'
        self.reply({'data':[{'id':'agnes-image-2.5-flash'}]})

    def do_POST(self):
        assert self.path=='/v1/images/generations'
        assert self.headers.get('Authorization')=='Bearer test-secret-never-save'
        req=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        assert req['model']=='agnes-image-2.5-flash' and req['size']=='1K'
        assert req['ratio'] in ('1:1','3:4','4:3') and 'response_format' not in req
        extra=req.get('extra_body',{})
        images=extra.get('image',[])
        assert (images and extra['response_format']=='b64_json') or req.get('return_base64') is True
        assert len(images)<=5
        for image in images:
            assert image.startswith('data:image/jpeg;base64,')
            assert base64.b64decode(image.split(',',1)[1],validate=True).startswith(b'\xff\xd8\xff')
        prompt=req['prompt']
        with (folder/'metrics.jsonl').open('a',encoding='utf-8') as output:
            print(json.dumps({'refs':len(images),'prompt':prompt,'size':len(json.dumps(req))}),file=output)
        if prompt.startswith('quota-fournisseur'):
            return self.reply({},429)
        if prompt.startswith('image-incomplete'):
            raw=b'\x89PNG\r\n\x1a\n'
        else:
            digest=hashlib.sha256((prompt+''.join(images)).encode()).hexdigest()
            raw=png(digest)
        if prompt.startswith('Vue '):
            # Build the fake scene from the camera instruction, independently of the button label.
            directions={'axe principal du lieu (0°)':0,'pivote de 180°':1,'90° vers la gauche':2,'90° vers la droite':3}
            orientation,= [code for cue,code in directions.items() if cue in prompt]
            wall = [(180,30,30),(30,170,30),(40,40,180),(190,160,30)][orientation]
            if 'Nuit :' in prompt: wall=tuple(value//2 for value in wall)
            raw=png(digest,width=240,wall=wall)
            echo=folder/'repeat-place'
            if echo.exists():
                if echo.read_bytes()==b'jpeg':
                    raw=base64.b64decode(images[0].split(',',1)[1])
                else:
                    raw=echo.read_bytes()
                echo.unlink()
        if prompt.startswith('Angle demandé'):
            orientations={'devant le personnage':'front','gauche anatomique':'left','droit anatomique':'right','derrière le personnage':'back'}
            matches=[v for cue,v in orientations.items() if cue in prompt.split('Dessine une seule vue')[0]]
            assert len(matches)==1
            raw=png(digest+uuid.uuid4().hex,view=matches[0])
            duplicate=folder/'repeat-view.png'
            if duplicate.exists():
                raw=duplicate.read_bytes()
                duplicate.unlink()
            with (folder/'views.jsonl').open('a',encoding='utf-8') as log:
                print(json.dumps({'prompt':prompt,'refs':len(images),'sha':hashlib.sha256(raw).hexdigest()}),file=log)
        self.reply({'data':[{'b64_json':base64.b64encode(raw).decode()}]})


if __name__=='__main__':
    app.PORT=int(os.getenv('INKFORGE_TEST_PORT','18765'))
    app.LOCAL_3D=folder/'test-runtime'
    app.update_status=lambda:{'current_version':app.BOOT_VERSION,'available':False,'remote_configured':True}
    provider=ThreadingHTTPServer(('127.0.0.1',0),Provider)
    app.AGNES=f'http://127.0.0.1:{provider.server_port}/v1/models'
    app.AGNES_GENERATE=app.AGNES.replace('/models','/images/generations')
    threading.Thread(target=provider.serve_forever,daemon=True).start()
    app.recovery_tools()
    if not (folder/'reference0.png').exists():
        for i in range(5):
            (folder/f'reference{i}.png').write_bytes(png(i))
    app.ThreadingHTTPServer((app.HOST,app.PORT),app.Handler).serve_forever()
