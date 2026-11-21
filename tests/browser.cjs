const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { once } = require('node:events');

const repo = path.resolve(__dirname, '..');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'inkforge-test-'));
const folder = path.join(tmp,'studio');
fs.mkdirSync(folder);
for(const name of ['INKFORGE.html','serveur_inkforge.py','version.json','LANCER_INKFORGE.cmd','LISEZ_MOI.txt'])fs.copyFileSync(path.join(repo,name),path.join(folder,name));
const address = 'http://127.0.0.1:'+(process.env.INKFORGE_TEST_PORT || '18765');
const delay = ms=>new Promise(r=>setTimeout(r,ms));
let server,browser;
async function start(){
 server=spawn(process.env.PYTHON || 'python',[path.join(__dirname,'studio_fixture.py'),folder],{stdio:'inherit'});
 for(let i=0;i<150;i++){try{const r=await fetch(address+'/health');await r.arrayBuffer();if(r.ok)return}catch{}await delay(100)}
 throw Error('Le studio de test ne démarre pas.');
}
async function stop(){const done=once(server,'exit');server.kill();await done;server=null}
async function open(){
 browser=await chromium.launchPersistentContext(path.join(tmp,'browser'),{headless:true,executablePath:process.env.CHROME_BIN||undefined});
 const p=await browser.newPage();p.setDefaultTimeout(15000);p.on('pageerror',e=>console.error('JS:',e.message));
 await p.goto(address);await p.waitForFunction(()=>typeof workspaceReady!=='undefined'&&workspaceReady);
 return p;
}
const saved=p=>p.evaluate(()=>flushWorkspace());
async function key(p){
 await p.locator('#apiToggle').click();
 await p.locator('#apiSecret').fill('test-secret-never-save');
 await p.locator('#addApiKey').click();await p.locator('#apiToggle').click();
}
async function validateReference(p,trigger,subject,angle,providerCalls=1){
 const metrics=path.join(folder,'metrics.jsonl');
 const countCalls=()=>fs.existsSync(metrics)?fs.readFileSync(metrics,'utf8').trim().split('\n').length:0;
 const before=countCalls();
 await trigger.click();
 const dialog=p.locator('#aiProgressDialog');
 await dialog.waitFor({state:'visible'});
 // The dialog also opens on failure. Its close button is enabled when generation finishes.
 try{
  await p.waitForFunction(()=>!document.getElementById('aiCloseDialog').disabled,null,{timeout:60000});
  assert.equal(await dialog.locator('#aiDialogTitle').textContent(),'Référence de '+subject+' · '+angle);
  assert.ok(await dialog.locator('#aiDialogImage').evaluate(img=>img.complete && img.naturalWidth>0));
  assert.equal(countCalls(),before+providerCalls,'Nombre exact de générations Agnes');
  assert.equal(await dialog.locator('img:visible').count(),1);
  const preview=await dialog.locator('#aiDialogImage').getAttribute('src');
  if(!angle.startsWith('Vue ')){
   const request=JSON.parse(fs.readFileSync(path.join(folder,'views.jsonl'),'utf8').trim().split('\n').pop());
   const cues={'Face':'Les deux épaules','Profil gauche':'bord gauche','Profil droit':'bord droit','Dos':'Le visage entier est caché'};
   assert.ok(request.prompt.startsWith('Angle demandé — '+angle+'.')&&request.prompt.includes(cues[angle]));
   assert.equal(request.prompt.includes('Si des mèches longues sont libres'),angle==='Dos');
   if(angle!=='Face')assert.equal(request.refs,1);
   assert.equal(preview,'/media/'+request.sha+'.png');
   const raster=await dialog.locator('#aiDialogImage').evaluate(img=>{
    const canvas=document.createElement('canvas');canvas.width=canvas.height=100;
    const ctx=canvas.getContext('2d');ctx.drawImage(img,0,0);
    return [[35,42],[65,42],[18,55],[80,55],[50,50]].map(([x,y])=>ctx.getImageData(x,y,1,1).data[0]);
   });
   const expected={'Face':[0,0,255,255,220],'Profil gauche':[0,220,220,255,220],
    'Profil droit':[220,0,255,220,220],'Dos':[55,55,255,255,55]};
   assert.deepEqual(raster,expected[angle]);
  }
  await dialog.getByRole('button',{name:'Valider cette vue',exact:true}).click();
  await dialog.waitFor({state:'hidden'});
  await saved(p);
  const grid=p.locator(angle.startsWith('Vue ')?'#placeGrid':'#characterGrid');
  const slot=grid.getByAltText(angle+' validé',{exact:true});
  assert.equal(await slot.getAttribute('src'),preview);
  assert.equal(await grid.locator('img').evaluateAll((imgs,url)=>imgs.filter(i=>i.getAttribute('src')===url).length,preview),1,'Le résultat validé apparaît une seule fois sur la fiche');
  return preview;
 }catch(error){
  throw new Error(angle+' — '+await dialog.locator('#aiDialogTitle').textContent()+' — '+await dialog.locator('#aiDialogStep').textContent(),{cause:error});
 }
}
async function generate(p,prompt,accept=true){
 await p.locator('#aiPrompt').fill(prompt);
 await p.locator('#generate').click();
 await p.waitForFunction(()=>!aiBusy);
 if(accept){
   assert.ok(await p.locator('#aiDialogImage').evaluate(el=>el.naturalWidth>0));
   await p.locator('#aiAcceptImage').click();await p.waitForFunction(()=>aiDialog.style.display==='none');await saved(p);
 }
}
(async()=>{
 try{
  await start();let p=await open();assert.equal(await p.locator('#page .empty').first().textContent(),'Case 1');
  assert.equal(await p.evaluate(()=>Object.keys(workspace.projects).length),0);
  await p.locator('[data-tab=characters]').click();await p.locator('#addChar').click();
  await p.locator('#memoryName').fill('Sujet de vérification');await p.locator('#memoryAppearance').fill('cheveux courts');
  await p.locator('#memoryFiles').setInputFiles(Array.from({length:5},(_,i)=>path.join(folder,'reference'+i+'.png')));
  await p.waitForFunction(()=>document.querySelector('#memoryCount').textContent.startsWith('5 '));
  await p.locator('#memorySave').click();await saved(p);await key(p);
  await p.route('**/ai/result',r=>r.abort('connectionreset'),{times:1});
  await validateReference(p,p.getByRole('button',{name:'Générer · Face',exact:true}),'Sujet de vérification','Face');
  assert.ok(await p.locator('#aiDialogImage').evaluate(el=>el.naturalWidth===960));
  console.log('PASS cinq originaux de 13 Mo, portrait généré et décodé, sauvegarde');
  await p.locator('[data-tab=places]').click();
  await p.locator('#addPlace').click();
  await p.getByLabel('Nom du décor').fill('Lieu de vérification');
  await p.getByLabel('Description détaillée du lieu').fill('Façade en briques');
  assert.ok(await p.locator('#memoryClothing').isHidden());
  await p.locator('#memorySave').click();await saved(p);
  await p.locator('[data-tab=ai]').click();await p.locator('#listAgnesModels').click();
  await p.waitForFunction(()=>document.querySelector('#agnesModel').value);
  await generate(p,'Scène avec une description seule');
  const original=await p.evaluate(()=>current().img);
  await p.locator('#aiCharacter').selectOption({label:'Sujet de vérification'});
  await p.locator('#aiPlace').selectOption({label:'Lieu de vérification'});
  await generate(p,'Scène avec personnage et décor',false);
  await p.route('**/work/save',r=>r.fulfill({status:507,contentType:'application/json',body:JSON.stringify({error:'Disque plein pendant le test.'})}),{times:1});
  await p.locator('#aiAcceptImage').click();await p.waitForFunction(()=>document.querySelector('#aiDialogTitle').textContent==='Image non enregistrée');
  assert.equal(await p.evaluate(()=>current().img),original);
  await p.getByRole('button',{name:'Réessayer l’enregistrement'}).click();await p.waitForFunction(()=>aiDialog.style.display==='none');await saved(p);
  const scene=await p.evaluate(()=>current().img);assert.notEqual(original,scene);
  for(const prompt of ['image-incomplete','quota-fournisseur']){
    await generate(p,prompt,false);assert.ok((await p.locator('#aiDialogStep').textContent()).includes('conservée'));
    assert.equal(await p.evaluate(()=>current().img),scene);await p.locator('#aiCloseDialog').click();
  }
  await p.locator('[data-tab=editor]').click();await p.locator('#selectedLabel').selectOption('1');
  await p.locator('#imageInput').setInputFiles(path.join(folder,'reference4.png'));
  await p.waitForFunction(()=>current().img.startsWith('/media/'));await saved(p);
  assert.equal((await p.evaluate(()=>JSON.stringify(localStorage))).includes('data:image'),false);
  // Imported original + generated results exceed even a fresh browser's localStorage quota.
  const media=path.join(folder,'_inkforge_travail','media');
  assert.ok(fs.readdirSync(media).reduce((n,f)=>n+fs.statSync(path.join(media,f)).size,0)>15_000_000);
  await p.locator('[data-tab=projects]').click();await p.locator('#saveVersion').click();await saved(p);
  const download=p.waitForEvent('download');await p.locator('#saveJSON2').click();
  const exported=path.join(tmp,'project.json');await (await download).saveAs(exported);
  const data=fs.readFileSync(exported,'utf8');assert.ok(!data.includes('/media/')&&!data.includes('test-secret-never-save'));
  assert.equal(JSON.parse(data).characters[0].references.length,5);
  await browser.close();browser=null;await stop();await start();p=await open();
  assert.ok(await p.evaluate(()=>project.pages[0][0].img && project.characters[0].portrait));
  await p.waitForFunction(()=>[...document.querySelectorAll('#page .frame img')].filter(i=>i.naturalWidth>0).length===2);
  assert.equal(await p.evaluate(()=>window.inkforgeAgnesKey()),'');
  await p.locator('[data-tab=projects]').click();assert.equal(await p.locator('#versionList .item').count(),1);
  await p.locator('#importJSON').setInputFiles(exported);
  await p.waitForFunction(()=>Object.keys(workspace.projects).length===2);await saved(p);
  assert.ok(!fs.readFileSync(path.join(folder,'_inkforge_travail','state.json'),'utf8').includes('data:image'));
  const calls=fs.readFileSync(path.join(folder,'metrics.jsonl'),'utf8').trim().split('\n').map(JSON.parse);
  assert.equal(calls.length,5);assert.equal(calls[0].refs,5);assert.equal(calls[1].refs,0);
  assert.ok(calls[2].prompt.includes('Façade en briques')&&calls[2].prompt.includes('cheveux courts'));
  assert.ok(calls.every(c=>c.size<4_000_000));
  await key(p);await p.locator('[data-tab=characters]').click();
  const face=await p.evaluate(()=>project.characters[0].views.front);
  for(const [angle,label] of [['side','Profil gauche'],['right','Profil droit'],['back','Dos']]){
   const before=await p.evaluate(()=>({...project.characters[0].views}));
   const preview=await validateReference(p,p.getByRole('button',{name:'Générer · '+label,exact:true}),'Sujet de vérification',label);
   const after=await p.evaluate(()=>({...project.characters[0].views}));
   assert.equal(after[angle],preview);
   assert.ok(after[angle]?.startsWith('/media/'));
   assert.deepEqual(after,{...before,[angle]:after[angle]});
   assert.ok(!Object.values(before).includes(after[angle]));

  }
  for(const [angle,label] of [['front','Face'],['side','Profil gauche'],['right','Profil droit'],['back','Dos']]){
   const before=await p.evaluate(()=>({...project.characters[0].views}));
   const preview=await validateReference(p,p.getByRole('button',{name:'Régénérer · '+label,exact:true}),'Sujet de vérification',label);
   assert.notEqual(before[angle],preview);
   assert.deepEqual(await p.evaluate(()=>project.characters[0].views),{...before,[angle]:preview});
  }
  for(const [appearance,clothing,accessories] of [
   ['Cheveux longs cuivrés et ondulés, libres jusqu’à la taille','Veste en jean','Boucles d’oreilles'],
   ['Cheveux argentés en chignon','Manteau à capuche relevée','Épingle noire']
  ]){
   await p.getByRole('button',{name:'Ouvrir la mémoire'}).click();
   await p.locator('#memoryAppearance').fill(appearance);
   await p.locator('#memoryClothing').fill(clothing);
   await p.locator('#memoryAccessories').fill(accessories);
   await p.locator('#memorySave').click();await saved(p);
   await validateReference(p,p.getByRole('button',{name:'Régénérer · Dos'}),'Sujet de vérification','Dos');
   const request=JSON.parse(fs.readFileSync(path.join(folder,'views.jsonl'),'utf8').trim().split('\n').pop());
   for(const detail of [appearance,clothing,accessories,'face extérieure du vêtement','respecte ce placement']){
    assert.ok(request.prompt.includes(detail),detail);
   }
  }
  const views=await p.evaluate(()=>({...project.characters[0].views}));
  assert.notEqual(views.front,face);assert.equal(await p.evaluate(()=>project.characters[0].portrait),views.front);
  await p.getByRole('button',{name:'Régénérer · Profil gauche'}).click();
  await p.waitForFunction(()=>!aiBusy);await p.locator('#aiCloseDialog').click();
  assert.deepEqual(await p.evaluate(()=>project.characters[0].views),views);
  fs.copyFileSync(path.join(media,path.basename(views.front)),path.join(folder,'repeat-view.png'));
  await p.getByRole('button',{name:'Régénérer · Dos'}).click();await p.waitForFunction(()=>!aiBusy);
  assert.ok((await p.locator('#aiDialogStep').textContent()).includes('copie exacte'));
  assert.ok(await p.locator('#aiAcceptImage').isHidden());await p.locator('#aiCloseDialog').click();
  assert.deepEqual(await p.evaluate(()=>project.characters[0].views),views);
  await p.locator('[data-tab=studio3d]').click();
  await p.locator('#studioCharacter').selectOption({label:'Sujet de vérification'});
  assert.equal(await p.locator('#studioSources img').count(),4);
  await p.locator('#studioBuild').click();
  await p.waitForFunction(()=>document.querySelector('#tripoStatus').textContent.includes('Installer Tripo'));
  await p.locator('#studioPlace').selectOption({label:'Lieu de vérification'});
  assert.ok(await p.locator('#studioBuild').isDisabled());
  await p.locator('[data-tab=places]').click();await p.getByRole('button',{name:'Revenir aux vues IA'}).click();
  await p.locator('[data-tab=studio3d]').click();
  await validateReference(p,p.locator('#placeReference'),'Lieu de vérification','Vue principale');
  assert.ok(await p.locator('#studioBuild').isEnabled());
  await p.locator('[data-tab=places]').click();
  await p.locator('#placeGrid').getByRole('button',{name:'Ouvrir la fiche'}).click();
  await p.locator('#memoryFiles').setInputFiles([0,1].map(i=>path.join(folder,'reference'+i+'.png')));
  await p.waitForFunction(()=>document.querySelector('#memoryCount').textContent.startsWith('2 '));
  await p.locator('#memorySave').click();await saved(p);
  const labels={main:'Vue principale',opposite:'Vue opposée',left:'Vue gauche',right:'Vue droite'};
  for(const light of ['day','night']){
   await p.locator('#placeGrid select').selectOption(light);
   for(const [key,label] of Object.entries(labels)){
    const before=await p.evaluate(()=>project.places[0].placeViews);
    const trigger=p.locator('#placeGrid').getByRole('button',{name:(before[light]?.[key]?'Régénérer':'Générer')+' · '+label,exact:true});
    const preview=await validateReference(p,trigger,'Lieu de vérification',label);
    const call=JSON.parse(fs.readFileSync(path.join(folder,'metrics.jsonl'),'utf8').trim().split('\n').pop());
    assert.ok(call.prompt.startsWith(label+'.')&&call.prompt.includes(light==='day'?'Jour :':'Nuit :'));
    assert.ok(call.prompt.includes('Façade en briques')&&call.refs>0);
    const colors={main:[180,30,30],opposite:[30,170,30],left:[40,40,180],right:[190,160,30]};
    const shown=await p.evaluate(async url=>{
     const image=new Image();image.src=url;await image.decode();
     const canvas=document.createElement('canvas'),ctx=canvas.getContext('2d');ctx.drawImage(image,0,0);
     return [...ctx.getImageData(10,10,1,1).data].slice(0,3);
    },preview);
    assert.deepEqual(shown,colors[key].map(v=>light==='night'?Math.floor(v/2):v));
    if(light==='day'&&key!=='main'){
     assert.equal(call.refs,1);assert.ok(call.prompt.includes('Image 1 : Vue principale (jour)'));
     assert.ok(call.prompt.includes('nouvelle composition')&&!call.prompt.includes('Reprends le cadrage'));
    }
    if(light==='night')assert.ok(call.prompt.includes('Image 1 : '+label+' (jour)'));
    assert.deepEqual(await p.evaluate(()=>project.places[0].placeViews),{...before,[light]:{...before[light],[key]:preview}});
   }
  }
  await p.locator('#placeGrid select').selectOption('day');
  const beforeEcho=await p.evaluate(()=>project.places[0].placeViews);
  const mainPicture=fs.readFileSync(path.join(media,path.basename(beforeEcho.day.main)));
  const reencoded=await p.evaluate(async url=>{
   const img=new Image();img.src=url;await img.decode();
   const canvas=document.createElement('canvas');canvas.width=img.naturalWidth;canvas.height=img.naturalHeight;
   canvas.getContext('2d').drawImage(img,0,0);return canvas.toDataURL('image/png').split(',')[1];
  },beforeEcho.day.main);
  assert.ok(!mainPicture.equals(Buffer.from(reencoded,'base64')));
  const brighter=await p.evaluate(async url=>{
   const img=new Image();img.src=url;await img.decode();
   const canvas=document.createElement('canvas');canvas.width=img.width;canvas.height=img.height;
   const ctx=canvas.getContext('2d');ctx.drawImage(img,0,0);
   const raster=ctx.getImageData(0,0,img.width,img.height);
   for(let i=0;i<raster.data.length;i+=4)for(let c=0;c<3;c++)raster.data[i+c]+=7;
   ctx.putImageData(raster,0,0);return canvas.toDataURL().split(',')[1];
  },beforeEcho.day.main);
  for(const response of [mainPicture,Buffer.from(reencoded,'base64'),'jpeg',Buffer.from(brighter,'base64')]){
   fs.writeFileSync(path.join(folder,'repeat-place'),response);
   await p.locator('#placeGrid').getByRole('button',{name:'Régénérer · Vue gauche'}).click();
   await p.waitForFunction(()=>!aiBusy);
   assert.ok(await p.locator('#aiAcceptImage').isHidden());
   assert.match(await p.locator('#aiDialogStep').textContent(),/copie exacte|reproduit une référence|même image/);
   await p.locator('#aiCloseDialog').click();
   assert.deepEqual(await p.evaluate(()=>project.places[0].placeViews),beforeEcho);
  }
  const details=p.locator('#placeGrid details');
  await details.locator('summary').click();
  await p.waitForFunction(()=>document.querySelector('#placeGrid details pre').textContent.includes('Opération'));
  const report=await details.innerText();
  assert.ok(!report.includes('test-secret-never-save'));
  const traces=await p.evaluate(()=>viewAttempts.filter(a=>a.mode==='day'&&a.status==='Validée'));
  assert.equal(new Set(traces.map(a=>a.ticket)).size,traces.length);
  assert.equal(new Set(traces.map(a=>a.request)).size,traces.length);
  for(const trace of traces){
   assert.match(trace.request,/^[a-f0-9]{64}$/);
   assert.equal(trace.received,trace.preview);assert.equal(trace.preview,trace.stored);
   assert.ok(report.includes(trace.request)&&report.includes(trace.received));
  }
  assert.ok(report.includes('Résultats reçus 2'));
  assert.ok(report.includes('demandes différentes, fichier identique reçu'));
  await p.locator('#placeGrid select').selectOption('night');
  const placeViews=await p.evaluate(()=>project.places[0].placeViews);
  await p.locator('#placeGrid').getByRole('button',{name:'Régénérer · Vue gauche'}).click();
  await p.waitForFunction(()=>!aiBusy);await p.locator('#aiCloseDialog').click();
  await p.locator('[data-tab=studio3d]').click();
  await p.locator('#studioPlace').selectOption({label:'Lieu de vérification'});
  assert.equal(await p.locator('#studioSources img').first().getAttribute('src'),placeViews.night.main);
  await p.locator('[data-tab=ai]').click();
  await p.locator('#aiPlace').selectOption({label:'Lieu de vérification'});
  await generate(p,'Paysage de nuit');
  const sceneCall=JSON.parse(fs.readFileSync(path.join(folder,'metrics.jsonl'),'utf8').trim().split('\n').pop());
  assert.ok(sceneCall.prompt.includes('Éclairage: Nuit')&&sceneCall.refs>0);
  await p.reload();await p.waitForFunction(()=>workspaceReady);
  assert.deepEqual(await p.evaluate(()=>project.characters[0].views),views);
  assert.deepEqual(await p.evaluate(()=>project.places[0].placeViews),placeViews);
  assert.equal(await p.evaluate(()=>project.places[0].references.length),2);
  await p.locator('[data-tab=places]').click();
  await key(p);
  await p.getByRole('button',{name:'Créer le panorama avec Agnes'}).click();
  await p.waitForFunction(()=>!aiBusy);
  assert.ok((await p.locator('#aiDialogTitle').textContent()).includes('Panorama 360°'));
  await p.locator('#aiAcceptImage').click();await saved(p);
  assert.ok(await p.evaluate(()=>project.places[0].panorama.startsWith('/media/')));
  // Cardinal landmarks around a single equirectangular raster, with the rear wall across its seam.
  const panorama=await p.evaluate(()=>{
   const c=document.createElement('canvas');c.width=1024;c.height=512;
   const ctx=c.getContext('2d');
   for(const [x,w,color] of [[0,128,'#cc2200'],[128,256,'#00bb22'],[384,256,'#2233ee'],[640,256,'#ffcc00'],[896,128,'#cc2200']]){
    ctx.fillStyle=color;ctx.fillRect(x,0,w,512);
   }
   return c.toDataURL().split(',')[1];
  });
  const oldPanorama=await p.evaluate(()=>project.places[0].panorama);
  await p.locator('#placeGrid input[type=file]').setInputFiles({name:'sphere.png',mimeType:'image/png',buffer:Buffer.from(panorama,'base64')});
  await p.waitForFunction(old=>project.places[0].panorama!==old,oldPanorama);await saved(p);
  await p.reload();await p.waitForFunction(()=>workspaceReady);
  await p.locator('[data-tab=places]').click();
  for(const light of ['day','night']){
   await p.locator('#placeGrid select').selectOption(light);
   for(const [angle,label] of Object.entries(labels)){
    const old=await p.evaluate(()=>project.places[0].placeViews);
    const url=await validateReference(p,p.getByRole('button',{name:'Régénérer · '+label,exact:true}),'Lieu de vérification',label,0);
    const rgb=await p.evaluate(async uri=>{
     const img=new Image();img.src=uri;await img.decode();
     const c=document.createElement('canvas'),ctx=c.getContext('2d');ctx.drawImage(img,-480,-360);
     return [...ctx.getImageData(0,0,1,1).data].slice(0,3);
    },url);
    const expected={main:[34,51,238],left:[0,187,34],right:[255,204,0],opposite:[204,34,0]}[angle];
    assert.deepEqual(rgb,expected.map((n,c)=>Math.round(n*(light==='day'?1:[.34,.43,.62][c]))));
    assert.deepEqual(await p.evaluate(()=>project.places[0].placeViews),{...old,[light]:{...old[light],[angle]:url}});
   }
  }
  await p.locator('[data-tab=studio3d]').click();await p.locator('#studioPlace').selectOption({label:'Lieu de vérification'});
  await p.route('**/3d/status',r=>r.fulfill({json:{ready:true}}));
  const qualities=[],modelId='1'.repeat(64);
  await p.route('**/3d/build',r=>{qualities.push(r.request().postDataJSON().quality);return r.fulfill({json:{id:modelId,cold:true,seconds:1,gpu_mib:100}})});
  await p.route('**/3d/models/*',r=>r.fulfill({body:'test-model'}));
  await p.evaluate(()=>{if(!customElements.get('model-viewer'))customElements.define('model-viewer',class extends HTMLElement{})});
  await p.locator('#studioPreview').click();await p.waitForFunction(()=>document.querySelector('#studioProgress').hidden);
  assert.ok(await p.locator('#modelArea model-viewer[camera-controls]').count());
  assert.equal(await p.evaluate(()=>project.places[0].model3d),undefined);
  await p.locator('#studioBuild').click();await p.waitForFunction(()=>document.querySelector('#studioProgress').hidden);
  assert.equal(await p.evaluate(()=>project.places[0].model3d),modelId);
  await p.locator('#studioOpen').click();await p.waitForFunction(()=>document.querySelector('#studioProgress').hidden);
  assert.deepEqual(qualities,['preview','final']);
  console.log('PASS panorama local, huit orientations/éclairages, aperçu 3D, qualité finale et réouverture sans reconstruction.');
  console.log('PASS quatre vues indépendantes, régénération annulée, sélection et référence du décor, précontrôle local.');
  console.log('PASS génération sans sélection et avec bibliothèques, deux échecs, insertion, export/import, historique, fermeture et réouverture');
 } finally{await browser?.close();if(server)await stop();fs.rmSync(tmp,{recursive:true,force:true,maxRetries:6,retryDelay:150})}
})().catch(e=>{console.error(e);process.exitCode=1});
