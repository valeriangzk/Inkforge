// File de générations en arrière-plan, ordre des onglets et onglet « Images ».
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { once } = require('node:events');

const repo = path.resolve(__dirname, '..');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'inkforge-queue-'));
const folder = path.join(tmp,'studio');
fs.mkdirSync(folder);
for(const name of ['INKFORGE.html','serveur_inkforge.py','version.json','LANCER_INKFORGE.cmd','LISEZ_MOI.txt'])fs.copyFileSync(path.join(repo,name),path.join(folder,name));
const port = process.env.INKFORGE_QUEUE_PORT || '18770';
const address = 'http://127.0.0.1:'+port;
const delay = ms=>new Promise(r=>setTimeout(r,ms));
let server,browser;
const calls=()=>fs.readFileSync(path.join(folder,'metrics.jsonl'),'utf8').trim().split('\n').map(JSON.parse);





const { settle } = require('./queue_helpers.cjs');
(async()=>{
 try{
  server=spawn(process.env.PYTHON || 'python',[path.join(__dirname,'studio_fixture.py'),folder],{stdio:'inherit',env:{...process.env,INKFORGE_TEST_PORT:port}});
  for(let i=0;i<150;i++){try{const r=await fetch(address+'/health');await r.arrayBuffer();if(r.ok)break}catch{}await delay(100)}
  browser=await chromium.launchPersistentContext(path.join(tmp,'browser'),{headless:true,executablePath:process.env.CHROME_BIN||undefined});
  let p=await browser.newPage();p.setDefaultTimeout(15000);p.on('pageerror',e=>console.error('JS:',e.message));
  await p.goto(address);await p.waitForFunction(()=>typeof workspaceReady!=='undefined'&&workspaceReady);

  // 6. Ordre des onglets.
  const nav=await p.locator('.nav [data-tab]').evaluateAll(b=>b.map(x=>x.dataset.tab));
  assert.deepEqual(nav,['projects','style','editor','characters','places','ai','studio3d','images']);

  await p.locator('#apiToggle').click();for(const k of ['a','b']){await p.locator('#apiSecret').fill('test-secret-'+k);await p.locator('#addApiKey').click()}await p.locator('#apiToggle').click();
  await p.evaluate(()=>change(()=>{project.title='File'}));
  await p.locator('[data-tab=ai]').click();await p.locator('#listAgnesModels').click();await p.waitForFunction(()=>document.querySelector('#agnesModel').value);

  // 1. Trois cases d’affilée, on change d’onglet pendant qu’elles tournent.
  const before=calls().length;
  for(const text of ['Case une','Case deux','Case trois']){await p.locator('#aiPrompt').fill(text);await p.locator('#generate').click()}
  assert.equal(await p.evaluate(()=>generationQueue.length),3);
  await p.locator('[data-tab=editor]').click();
  const pages=await p.evaluate(()=>project.pages.length);
  await p.locator('#addPage').click();
  assert.equal(await p.evaluate(()=>project.pages.length),pages+1,'Le logiciel reste utilisable');
  assert.ok(await p.locator('#queuePanel').isVisible());
  assert.match(await p.locator('#queueSummary').textContent(),/Générations : \d\/3/);
  assert.equal(await p.locator('#aiProgressDialog').isVisible(),false,'Aucune fenêtre ne bloque l’écran');
  // 2. Une 4e génération rejoint la file pendant que les autres tournent.
  await p.locator('[data-tab=ai]').click();
  await p.locator('#aiPrompt').fill('Case quatre');await p.locator('#generate').click();
  assert.equal(await p.evaluate(()=>generationQueue.length),4);
  assert.ok(await p.evaluate(()=>generationQueue.slice(0,3).some(j=>j.status!=='done')),'La 4e arrive avant la fin des autres');
  await p.waitForFunction(()=>generationQueue.every(j=>j.status==='done'),null,{timeout:60000});
  const made=calls().slice(before);
  assert.equal(made.length,4);assert.equal(new Set(made.map(c=>c.key)).size,2,'Réparties sur les deux clés');
  // 3. Les images arrivent dans « Images », pas dans les cases.
  await p.evaluate(()=>flushWorkspace());
  const images=await p.evaluate(()=>project.images.map(i=>({url:i.url,prompt:i.prompt})));
  assert.deepEqual(images.map(i=>i.prompt).sort(),['Case deux','Case quatre','Case trois','Case une']);
  assert.ok(await p.evaluate(()=>project.pages.flat().every(f=>!f.img)),'Aucune case remplie automatiquement');
  await p.locator('[data-tab=images]').click();
  assert.equal(await p.locator('#imageGrid [data-stored-image] img').count(),4);
  console.log('PASS file en arrière-plan : 4 cases générées sans bloquer, rangées dans « Images »');

  // 4. Placer puis supprimer : la case garde son image.
  await p.getByRole('button',{name:'Placer dans une case · image 2',exact:true}).click();
  await p.locator('#imagePage').selectOption('0');await p.locator('#imageFrame').selectOption('1');
  await p.locator('#imageConfirm').click();await p.locator('#imageDialog').waitFor({state:'hidden'});
  assert.equal(await p.evaluate(()=>project.pages[0][1].img),images[1].url);
  await p.getByRole('button',{name:'Supprimer · image 2',exact:true}).click();
  assert.ok((await p.locator('#imageAskText').textContent()).includes('gardent'));
  await p.locator('#imageConfirm').click();await p.locator('#imageDialog').waitFor({state:'hidden'});
  assert.equal(await p.evaluate(()=>project.images.length),3);
  assert.equal(await p.evaluate(()=>project.pages[0][1].img),images[1].url,'La case garde son image');
  await p.locator('[data-tab=editor]').click();await p.evaluate(()=>{page=0;renderAll()});
  await p.locator('#page .frame').nth(1).click({button:'right'});
  assert.ok(await p.getByRole('button',{name:'Rogner l’image',exact:true}).isVisible(),'Une image placée peut être rognée');
  await p.keyboard.press('Escape');await p.mouse.click(5,5);
  console.log('PASS placer une image, la supprimer du stockage sans toucher la case');

  // Échec : nouvel essai automatique, puis « Réessayer ».
  await p.route('**/ai/generate',r=>r.fulfill({status:502,contentType:'application/json',body:JSON.stringify({error:'Panne simulée.'})}));
  await p.locator('[data-tab=ai]').click();await p.locator('#aiPrompt').fill('Case en panne');
  const failed=await settle(p,p.locator('#generate'));
  assert.equal(failed.status,'failed');
  assert.equal(await p.evaluate(id=>generationQueue.find(j=>j.id===id).tries,failed.id),2,'Une nouvelle tentative automatique');
  await p.unroute('**/ai/generate');
  await p.locator('[data-queue-job="'+failed.id+'"]').getByRole('button',{name:/^Réessayer/}).click();
  await p.waitForFunction(id=>generationQueue.find(j=>j.id===id).status==='done',failed.id,{timeout:60000});
  // Annuler une tâche en attente.
  await p.evaluate(()=>{window.__hold=true});
  await p.route('**/ai/generate',async r=>{while(await p.evaluate(()=>window.__hold).catch(()=>false))await delay(100);return r.continue()});
  for(const text of ['Attente un','Attente deux','Attente trois']){await p.locator('#aiPrompt').fill(text);await p.locator('#generate').click()}
  const last=await p.evaluate(()=>generationQueue.at(-1).id);
  assert.equal(await p.evaluate(id=>generationQueue.find(j=>j.id===id).status,last),'waiting');
  await p.locator('[data-queue-job="'+last+'"]').getByRole('button',{name:/^Annuler/}).click();
  assert.equal(await p.evaluate(id=>generationQueue.find(j=>j.id===id).status,last),'cancelled');
  await p.evaluate(()=>{window.__hold=false});
  await p.waitForFunction(()=>generationQueue.every(j=>['done','cancelled'].includes(j.status)),null,{timeout:60000});
  await p.unroute('**/ai/generate');
  assert.ok(!(await p.evaluate(()=>project.images.map(i=>i.prompt))).includes('Attente trois'));
  // Le panneau se réduit.
  await p.locator('#queuePanel').getByRole('button',{name:'Réduire',exact:true}).click();
  assert.ok(await p.locator('#queueList').isHidden());
  await p.locator('#queuePanel').getByRole('button',{name:'Afficher',exact:true}).click();
  console.log('PASS échec retenté puis « Réessayer », annulation, panneau réductible');

  // 5. Les 4 vues d’un personnage restent dans sa bibliothèque.
  const stored=await p.evaluate(()=>project.images.length);
  await p.locator('[data-tab=characters]').click();await p.locator('#addChar').click();
  await p.locator('#memoryName').fill('Rinko');await p.locator('#memoryAppearance').fill('cheveux noirs');await p.locator('#memorySave').click();
  await p.locator('#characterGrid').getByRole('button',{name:'Générer les 4 vues',exact:true}).click();
  await p.locator('#viewBatchClose').click();
  assert.ok(await p.locator('#viewBatchDialog').isHidden(),'La fenêtre des 4 vues se ferme pendant la génération');
  await p.waitForFunction(()=>currentBatch?.revealed,null,{timeout:60000});
  await p.locator('#queuePanel').getByRole('button',{name:'Voir · 4 vues de « Rinko »',exact:true}).click();
  await p.locator('#viewBatchDialog').waitFor({state:'visible'});
  assert.equal(await p.locator('#viewBatchGrid img').count(),4);
  await p.getByRole('button',{name:'Valider · Face',exact:true}).click();await p.waitForFunction(()=>currentBatch.cards.front.validated);
  await p.locator('#viewBatchClose').click();await p.evaluate(()=>flushWorkspace());
  assert.equal(await p.evaluate(()=>project.images.length),stored,'Rien dans « Images »');
  assert.ok(await p.evaluate(()=>project.characters[0].views.front));
  // Le stockage est sauvegardé avec le projet.
  await p.close();p=await browser.newPage();p.setDefaultTimeout(15000);
  await p.goto(address);await p.waitForFunction(()=>workspaceReady);
  assert.equal(await p.evaluate(()=>project.images.length),stored);
  console.log('PASS 4 vues dans la bibliothèque seulement, stockage conservé après réouverture');
 }catch(error){console.error(error);process.exitCode=1}
 finally{if(browser)await browser.close();if(server){const done=once(server,'exit');server.kill();await done}}
})();
