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
async function validateReference(p,trigger,subject,angle){
 await trigger.click();
 const dialog=p.locator('#aiProgressDialog');
 await dialog.waitFor({state:'visible'});
 // The dialog also opens on failure. Its close button is enabled when generation finishes.
 try{
  await p.waitForFunction(()=>!document.getElementById('aiCloseDialog').disabled,null,{timeout:60000});
  assert.equal(await dialog.locator('#aiDialogTitle').textContent(),'Référence de '+subject);
  assert.ok(await dialog.locator('#aiDialogImage').evaluate(img=>img.complete && img.naturalWidth>0));
  await dialog.getByRole('button',{name:'Valider cette vue',exact:true}).click();
  await dialog.waitFor({state:'hidden'});
  await saved(p);
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
  const answers=['Lieu de vérification','Façade en briques'];
  p.on('dialog',async dialog=>{if(dialog.type()==='prompt')await dialog.accept(answers.shift());else await dialog.dismiss()});
  await p.locator('#addPlace').click();await saved(p);
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
  for(const label of ['Profil gauche','Dos']){
   const before=await p.evaluate(()=>({...project.characters[0].views}));
   await validateReference(p,p.getByRole('button',{name:'Générer · '+label,exact:true}),'Sujet de vérification',label);
   const after=await p.evaluate(()=>({...project.characters[0].views}));
   const angle=label==='Dos'?'back':'side';
   assert.ok(after[angle]?.startsWith('/media/'));
   assert.deepEqual(after,{...before,[angle]:after[angle]});
   assert.ok(!Object.values(before).includes(after[angle]));

  }
  const views=await p.evaluate(()=>({...project.characters[0].views}));
  assert.equal(views.front,face);assert.ok(views.side&&views.back);
  await p.getByRole('button',{name:'Régénérer · Profil gauche'}).click();
  await p.waitForFunction(()=>!aiBusy);await p.locator('#aiCloseDialog').click();
  assert.deepEqual(await p.evaluate(()=>project.characters[0].views),views);
  await p.locator('[data-tab=studio3d]').click();
  await p.locator('#studioCharacter').selectOption({label:'Sujet de vérification'});
  assert.equal(await p.locator('#studioSources img').count(),3);
  await p.locator('#studioBuild').click();
  await p.waitForFunction(()=>document.querySelector('#tripoStatus').textContent.includes('Installer Tripo'));
  await p.locator('#studioPlace').selectOption({label:'Lieu de vérification'});
  assert.ok(await p.locator('#studioBuild').isDisabled());
  await validateReference(p,p.locator('#placeReference'),'Lieu de vérification','Décor');
  assert.ok(await p.locator('#studioBuild').isEnabled());
  await p.reload();await p.waitForFunction(()=>workspaceReady);
  assert.deepEqual(await p.evaluate(()=>project.characters[0].views),views);
  assert.ok(await p.evaluate(()=>project.places[0].img));
  console.log('PASS trois vues indépendantes, régénération annulée, sélection et référence du décor, précontrôle local.');
  console.log('PASS génération sans sélection et avec bibliothèques, deux échecs, insertion, export/import, historique, fermeture et réouverture');
 } finally{await browser?.close();if(server)await stop();fs.rmSync(tmp,{recursive:true,force:true,maxRetries:6,retryDelay:150})}
})().catch(e=>{console.error(e);process.exitCode=1});
