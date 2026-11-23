// « Régénérer » donne toujours une nouvelle image (personnages, décors IA, décors en panorama) et accepte une correction ponctuelle.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { once } = require('node:events');

const repo = path.resolve(__dirname, '..');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'inkforge-regen-'));
const folder = path.join(tmp,'studio');
fs.mkdirSync(folder);
for(const name of ['INKFORGE.html','serveur_inkforge.py','version.json','LANCER_INKFORGE.cmd','LISEZ_MOI.txt'])fs.copyFileSync(path.join(repo,name),path.join(folder,name));
const port = process.env.INKFORGE_REGEN_PORT || '18767';
const address = 'http://127.0.0.1:'+port;
const delay = ms=>new Promise(r=>setTimeout(r,ms));
let server,browser;
const metrics=()=>{const file=path.join(folder,'metrics.jsonl');return fs.existsSync(file)?fs.readFileSync(file,'utf8').trim().split('\n').map(JSON.parse):[]};

// Clique, attend la fin de la génération et renvoie {image, calls} sans valider.
async function preview(p,grid,label){
 const before=metrics().length;
 await p.locator(grid).getByRole('button',{name:new RegExp('^(Générer|Régénérer) · '+label+'$')}).click();
 await p.locator('#aiProgressDialog').waitFor({state:'visible'});
 await p.waitForFunction(()=>!aiBusy,null,{timeout:60000});
 const image=await p.locator('#aiDialogImage').getAttribute('src');
 const error=await p.locator('#aiAcceptImage').isHidden();
 assert.ok(!error,label+' : '+await p.locator('#aiDialogStep').textContent());
 return {image,calls:metrics().slice(before)};
}
async function accept(p){
 await p.locator('#aiAcceptImage').click();
 await p.waitForFunction(()=>aiDialog.style.display==='none');
 await p.evaluate(()=>flushWorkspace());
}

(async()=>{
 try{
  server=spawn(process.env.PYTHON || 'python',[path.join(__dirname,'studio_fixture.py'),folder],{stdio:'inherit',env:{...process.env,INKFORGE_TEST_PORT:port}});
  for(let i=0;i<150;i++){try{const r=await fetch(address+'/health');await r.arrayBuffer();if(r.ok)break}catch{}await delay(100)}
  browser=await chromium.launchPersistentContext(path.join(tmp,'browser'),{headless:true,executablePath:process.env.CHROME_BIN||undefined});
  const p=await browser.newPage();p.setDefaultTimeout(15000);p.on('pageerror',e=>console.error('JS:',e.message));
  await p.goto(address);await p.waitForFunction(()=>typeof workspaceReady!=='undefined'&&workspaceReady);
  await p.locator('#apiToggle').click();await p.locator('#apiSecret').fill('test-secret-never-save');await p.locator('#addApiKey').click();await p.locator('#apiToggle').click();

  // Personnage : la régénération ne peut pas rendre la même image, même si Agnes répond à l'identique.
  await p.locator('[data-tab=characters]').click();await p.locator('#addChar').click();
  await p.locator('#memoryName').fill('Sujet régénéré');await p.locator('#memoryAppearance').fill('cheveux courts, veste rouge');
  await p.locator('#memorySave').click();await p.evaluate(()=>flushWorkspace());
  const face=(await preview(p,'#characterGrid','Face')).image;await accept(p);
  const media=path.join(folder,'_inkforge_travail','media');
  fs.copyFileSync(path.join(media,path.basename(face)),path.join(folder,'repeat-view.png'));
  const second=await preview(p,'#characterGrid','Face');
  assert.notEqual(second.image,face,'Nouvelle image du personnage');
  assert.equal(second.calls.length,2,'Réponse identique : une seconde variante est demandée');
  assert.ok(second.calls.every(c=>c.prompt.includes('variante')));
  assert.notEqual(second.calls[0].prompt,second.calls[1].prompt);
  await accept(p);

  // Correction ponctuelle : ajoutée à la consigne, puis le champ se vide.
  const field=p.locator('#characterGrid').getByLabel('Correction · Face',{exact:true});
  await field.fill('plus de lumière');
  const corrected=await preview(p,'#characterGrid','Face');
  assert.ok(corrected.calls.at(-1).prompt.includes('Correction demandée pour cette version : plus de lumière'));
  assert.equal(await field.inputValue(),'');
  await p.locator('#aiCloseDialog').click();
  const next=await preview(p,'#characterGrid','Face');
  assert.ok(!next.calls.at(-1).prompt.includes('plus de lumière'),'La correction ne sert qu’une fois');
  await p.locator('#aiCloseDialog').click();
  console.log('PASS personnage : nouvelle image à chaque régénération, correction ponctuelle');

  // Décor en vues IA : deux régénérations, deux images différentes.
  await p.locator('[data-tab=places]').click();await p.locator('#addPlace').click();
  await p.getByLabel('Nom du décor').fill('Lieu régénéré');await p.getByLabel('Description détaillée du lieu').fill('Façade en briques');
  await p.locator('#memorySave').click();await p.evaluate(()=>flushWorkspace());
  await p.locator('#placeGrid').getByRole('button',{name:'Revenir aux vues IA'}).click();await p.evaluate(()=>flushWorkspace());
  const main=(await preview(p,'#placeGrid','Vue principale')).image;await accept(p);
  const r1=await preview(p,'#placeGrid','Vue principale');await accept(p);
  const r2=await preview(p,'#placeGrid','Vue principale');await accept(p);
  assert.equal(new Set([main,r1.image,r2.image]).size,3,'Chaque régénération du décor donne une nouvelle image');
  assert.equal(r1.calls.length,1);assert.ok(r1.calls[0].prompt.includes('variante'));
  console.log('PASS décor en vues IA : nouvelle image à chaque régénération');

  // Décor en panorama : « Générer » cadre le panorama sur le PC ; « Régénérer » lance une vraie génération Agnes.
  const panorama=await p.evaluate(()=>{
   const c=document.createElement('canvas');c.width=1024;c.height=512;const ctx=c.getContext('2d');
   for(const [x,w,color] of [[0,128,'#cc2200'],[128,256,'#00bb22'],[384,256,'#2233ee'],[640,256,'#ffcc00'],[896,128,'#cc2200']]){ctx.fillStyle=color;ctx.fillRect(x,0,w,512)}
   return c.toDataURL().split(',')[1];
  });
  await p.evaluate(()=>change(()=>{project.places[0].placeViews={}}));
  await p.locator('#placeGrid input[type=file]').setInputFiles({name:'sphere.png',mimeType:'image/png',buffer:Buffer.from(panorama,'base64')});
  await p.waitForFunction(()=>Boolean(project.places[0].panorama));await p.evaluate(()=>flushWorkspace());
  const crop=await preview(p,'#placeGrid','Vue gauche');
  assert.equal(crop.calls.length,0,'Première vue : cadrage local du panorama');
  await accept(p);
  const regen1=await preview(p,'#placeGrid','Vue gauche');
  assert.equal(regen1.calls.length,1,'Régénérer lance une génération Agnes');
  assert.equal(regen1.calls[0].refs,1,'Le cadrage du panorama sert de référence');
  assert.notEqual(regen1.image,crop.image);
  await accept(p);
  const regen2=await preview(p,'#placeGrid','Vue gauche');
  assert.notEqual(regen2.image,regen1.image,'Deux régénérations, deux images');
  await accept(p);
  console.log('PASS décor en panorama : Régénérer lance une vraie génération');
 }catch(error){console.error(error);process.exitCode=1}
 finally{if(browser)await browser.close();if(server){const done=once(server,'exit');server.kill();await done}}
})();
