// Bouton « Générer les 4 vues » : vue de base puis trois vues en même temps, réparties sur plusieurs clés.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { once } = require('node:events');

const repo = path.resolve(__dirname, '..');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'inkforge-batch-'));
const folder = path.join(tmp,'studio');
fs.mkdirSync(folder);
for(const name of ['INKFORGE.html','serveur_inkforge.py','version.json','LANCER_INKFORGE.cmd','LISEZ_MOI.txt'])fs.copyFileSync(path.join(repo,name),path.join(folder,name));
const port = process.env.INKFORGE_BATCH_PORT || '18766';
const address = 'http://127.0.0.1:'+port;
const delay = ms=>new Promise(r=>setTimeout(r,ms));
let server,browser;
const calls=()=>fs.readFileSync(path.join(folder,'metrics.jsonl'),'utf8').trim().split('\n').map(JSON.parse);

async function runBatch(p,grid,labels){
 const before=fs.existsSync(path.join(folder,'metrics.jsonl'))?calls().length:0;
 await p.locator(grid).getByRole('button',{name:'Générer les 4 vues',exact:true}).click();
 const dialog=p.locator('#viewBatchDialog');
 await p.waitForFunction(()=>viewBatch.style.display==='flex'||aiDialog.style.display==='flex');
 if(await p.evaluate(()=>viewBatch.style.display!=='flex'))throw Error('Fenêtre des 4 vues non ouverte : '+await p.locator('#aiDialogTitle').textContent()+' — '+await p.locator('#aiDialogStep').textContent());
 // Tant que les quatre vues ne sont pas prêtes, aucune image n'est affichée.
 let sawWaiting=false;
 for(let i=0;i<200;i++){
  const state=await p.evaluate(()=>({revealed:currentBatch?.revealed,images:document.querySelectorAll('#viewBatchGrid img').length}));
  if(state.revealed)break;
  assert.equal(state.images,0,'Aucune image avant la fin des quatre vues');sawWaiting=true;await delay(100);
 }
 assert.ok(sawWaiting);
 await p.waitForFunction(()=>currentBatch?.revealed&&!batchBusy,null,{timeout:60000});
 const sources=await dialog.locator('#viewBatchGrid img').evaluateAll(imgs=>imgs.map(i=>i.getAttribute('src')));
 assert.equal(sources.length,4,'Les quatre vues apparaissent ensemble');
 assert.equal(new Set(sources).size,4);
 const made=calls().slice(before);
 assert.equal(made.length,4);
 const [first,...others]=made;
 assert.ok(first.prompt.includes(labels[0]));
 // La vue de base est terminée avant que les trois autres commencent, et les trois autres tournent en même temps.
 assert.ok(others.every(c=>c.start>=first.end-0.05));
 assert.ok(Math.max(...others.map(c=>c.start))<Math.min(...others.map(c=>c.end)),'Les trois vues sont créées en parallèle');
 assert.equal(new Set(made.map(c=>c.key)).size,3,'Les générations sont réparties sur les trois clés');
 return sources;
}

(async()=>{
 try{
  server=spawn(process.env.PYTHON || 'python',[path.join(__dirname,'studio_fixture.py'),folder],{stdio:'inherit',env:{...process.env,INKFORGE_TEST_PORT:port}});
  for(let i=0;i<150;i++){try{const r=await fetch(address+'/health');await r.arrayBuffer();if(r.ok)break}catch{}await delay(100)}
  browser=await chromium.launchPersistentContext(path.join(tmp,'browser'),{headless:true,executablePath:process.env.CHROME_BIN||undefined});
  const p=await browser.newPage();p.setDefaultTimeout(15000);p.on('pageerror',e=>console.error('JS:',e.message));
  await p.goto(address);await p.waitForFunction(()=>typeof workspaceReady!=='undefined'&&workspaceReady);

  await p.locator('#apiToggle').click();
  for(const name of ['a','b','c']){await p.locator('#apiSecret').fill('test-secret-'+name);await p.locator('#addApiKey').click()}
  await p.locator('#apiToggle').click();
  assert.equal((await p.evaluate(()=>window.inkforgeAgnesKeys())).length,3);

  await p.locator('[data-tab=characters]').click();await p.locator('#addChar').click();
  await p.locator('#memoryName').fill('Sujet parallèle');await p.locator('#memoryAppearance').fill('cheveux courts, veste rouge');
  await p.locator('#memorySave').click();await p.evaluate(()=>flushWorkspace());

  const sources=await runBatch(p,'#characterGrid',['devant le personnage']);
  const views=fs.readFileSync(path.join(folder,'views.jsonl'),'utf8').trim().split('\n').map(JSON.parse).slice(-4);
  assert.ok(views.slice(1).every(v=>v.refs===1),'Profils et dos partent de la nouvelle face');
  const dialog=p.locator('#viewBatchDialog');
  assert.ok(await dialog.getByRole('button',{name:'Valider · Profil gauche',exact:true}).isDisabled(),'La face se valide en premier');
  assert.equal(await p.evaluate(()=>project.characters[0].views?.front||''),'');

  await dialog.getByRole('button',{name:'Valider · Face',exact:true}).click();
  await p.waitForFunction(()=>currentBatch.cards.front.validated&&!batchBusy);
  assert.equal(await p.evaluate(()=>project.characters[0].views.front),sources[0]);
  assert.equal(await p.evaluate(()=>project.characters[0].portrait),sources[0]);

  const oldBack=await p.evaluate(()=>currentBatch.cards.back.image);
  await dialog.getByRole('button',{name:'Refaire · Dos',exact:true}).click();
  await p.waitForFunction(()=>!batchBusy&&currentBatch.cards.back.status==='done',null,{timeout:60000});
  const newBack=await p.evaluate(()=>currentBatch.cards.back.image);
  assert.ok(newBack&&newBack!==oldBack);
  await dialog.getByRole('button',{name:'Valider · Dos',exact:true}).click();
  await p.waitForFunction(()=>currentBatch.cards.back.validated&&!batchBusy);
  await p.evaluate(()=>flushWorkspace());
  assert.deepEqual(await p.evaluate(()=>project.characters[0].views),{front:sources[0],back:newBack});
  await dialog.getByRole('button',{name:'Fermer',exact:true}).click();await dialog.waitFor({state:'hidden'});
  console.log('PASS quatre vues du personnage en parallèle, validées une par une');

  await p.locator('[data-tab=places]').click();await p.locator('#addPlace').click();
  await p.getByLabel('Nom du décor').fill('Lieu parallèle');await p.getByLabel('Description détaillée du lieu').fill('Façade en briques');
  await p.locator('#memorySave').click();await p.evaluate(()=>flushWorkspace());
  await p.locator('#placeGrid').getByRole('button',{name:'Revenir aux vues IA'}).click();await p.evaluate(()=>flushWorkspace());
  const places=await runBatch(p,'#placeGrid',['Vue principale']);
  assert.ok(await dialog.getByRole('button',{name:'Valider · Vue gauche',exact:true}).isDisabled());
  await dialog.getByRole('button',{name:'Valider · Vue principale',exact:true}).click();
  await p.waitForFunction(()=>currentBatch.cards.main.validated&&!batchBusy);
  await dialog.getByRole('button',{name:'Valider · Vue gauche',exact:true}).click();
  await p.waitForFunction(()=>currentBatch.cards.left.validated&&!batchBusy);
  await p.evaluate(()=>flushWorkspace());
  assert.deepEqual(await p.evaluate(()=>project.places[0].placeViews),{day:{main:places[0],left:places[2]}});
  console.log('PASS quatre vues du décor en parallèle');
  assert.ok(!fs.readFileSync(path.join(folder,'_inkforge_travail','state.json'),'utf8').includes('test-secret-'));
 }catch(error){console.error(error);process.exitCode=1}
 finally{if(browser)await browser.close();if(server){const done=once(server,'exit');server.kill();await done}}
})();
