// 20 vues de décor en arrière-plan, et style imposé aux personnages malgré leurs images de référence.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { once } = require('node:events');

const repo = path.resolve(__dirname, '..');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'inkforge-extra-'));
const folder = path.join(tmp,'studio');
fs.mkdirSync(folder);
for(const name of ['INKFORGE.html','serveur_inkforge.py','version.json','LANCER_INKFORGE.cmd','LISEZ_MOI.txt'])fs.copyFileSync(path.join(repo,name),path.join(folder,name));
const port = process.env.INKFORGE_EXTRA_PORT || '18769';
const address = 'http://127.0.0.1:'+port;
const delay = ms=>new Promise(r=>setTimeout(r,ms));
let server,browser;
const calls=()=>fs.readFileSync(path.join(folder,'metrics.jsonl'),'utf8').trim().split('\n').map(JSON.parse);




const lastCall=()=>calls().at(-1);
async function preview(p,button){
 await button.click();
 await p.waitForFunction(()=>aiBusy,null,{timeout:5000}).catch(()=>{});
 await p.waitForFunction(()=>!aiBusy,null,{timeout:60000});
 const title=await p.locator('#aiDialogTitle').textContent();
 assert.ok(/^(Référence de |Aperçu)/.test(title),title+' — '+await p.locator('#aiDialogStep').textContent());
}
async function accept(p){await p.locator('#aiAcceptImage').click();await p.waitForFunction(()=>aiDialog.style.display==='none');await p.evaluate(()=>flushWorkspace())}
(async()=>{
 try{
  server=spawn(process.env.PYTHON || 'python',[path.join(__dirname,'studio_fixture.py'),folder],{stdio:'inherit',env:{...process.env,INKFORGE_TEST_PORT:port}});
  for(let i=0;i<150;i++){try{const r=await fetch(address+'/health');await r.arrayBuffer();if(r.ok)break}catch{}await delay(100)}
  browser=await chromium.launchPersistentContext(path.join(tmp,'browser'),{headless:true,executablePath:process.env.CHROME_BIN||undefined});
  let p=await browser.newPage();p.setDefaultTimeout(15000);p.on('pageerror',e=>console.error('JS:',e.message));
  await p.goto(address);await p.waitForFunction(()=>typeof workspaceReady!=='undefined'&&workspaceReady);
  await p.locator('#apiToggle').click();for(const k of ['a','b','c']){await p.locator('#apiSecret').fill('test-secret-'+k);await p.locator('#addApiKey').click()}await p.locator('#apiToggle').click();
  await p.evaluate(()=>change(()=>{project.title='Rinko';project.style='seinen'}));

  // Point 2 : un personnage avec une image de référence reçoit quand même le style imposé.
  const ref=await p.evaluate(async()=>{const c=document.createElement('canvas');c.width=300;c.height=400;const x=c.getContext('2d');x.fillStyle='#e9a';x.fillRect(0,0,300,400);const blob=await new Promise(r=>c.toBlob(r,'image/png'));return fileData(new File([blob],'rinko.png',{type:'image/png'}))});
  for(const [style,name] of [['seinen','Rinko Seinen'],['chibi','Rinko Chibi']]){
   await p.evaluate(([style,name,ref])=>change(()=>{project.style=style;project.characters.push({id:crypto.randomUUID(),name,appearance:'lycéenne, cheveux noirs mi-longs, gilet bleu',references:[ref]})}),[style,name,ref]);
   await p.locator('[data-tab=characters]').click();
   await preview(p,p.locator('#characterGrid .item').filter({hasText:name}).getByRole('button',{name:'Générer · Face',exact:true}));
   const call=lastCall();
   assert.ok(call.refs>=1,'L’image de référence part bien');
   assert.ok(call.prompt.startsWith('Style graphique imposé (« '+(style==='seinen'?'Seinen':'Chibi / comédie')+' »)'));
   assert.ok(call.prompt.includes('indépendamment de leur orientation et de leur style de dessin'));
   assert.ok(call.prompt.includes('Ne reprends jamais leur style de dessin'));
   await p.locator('#aiCloseDialog').click();
  }
  console.log('PASS style imposé aux personnages malgré leurs images de référence');

  // Point 1 : 20 vues en arrière-plan.
  await p.evaluate(()=>change(()=>{project.style='seinen'}));
  await p.locator('[data-tab=places]').click();await p.locator('#addPlace').click();
  await p.getByLabel('Nom du décor').fill('chambre de Rinko');await p.getByLabel('Description détaillée du lieu').fill('Chambre avec un bureau, un PC, une lampe et un lit');
  await p.locator('#memorySave').click();
  await p.locator('#placeGrid').getByRole('button',{name:'Revenir aux vues IA'}).click();
  await preview(p,p.locator('#placeGrid').getByRole('button',{name:'Générer · Vue principale',exact:true}));await accept(p);
  const before=calls().length;
  let failOnce=true;
  await p.route('**/ai/generate',route=>{if(failOnce){failOnce=false;return route.fulfill({status:502,contentType:'application/json',body:JSON.stringify({error:'Panne simulée pendant le test.'})})}return route.continue()});
  await p.getByRole('button',{name:'Générer 20 vues · chambre de Rinko',exact:true}).click();
  await p.waitForFunction(()=>Object.values(extraJobs).some(j=>j.done>=1),null,{timeout:30000});
  // Le logiciel reste utilisable pendant la génération.
  assert.equal(await p.evaluate(()=>aiBusy),false);
  await p.locator('[data-tab=editor]').click();
  const pages=await p.evaluate(()=>project.pages.length);
  await p.locator('#addPage').click();
  assert.equal(await p.evaluate(()=>project.pages.length),pages+1,'Une planche se crée pendant la génération');
  assert.match(await p.locator('#extraViewsBadge').textContent(),/chambre de Rinko » : \d+\/20/);
  await p.waitForFunction(()=>Object.values(extraJobs).every(j=>j.finished),null,{timeout:120000});
  const place=await p.evaluate(()=>project.places[0]);
  assert.equal(place.extraViews.length,20,'Les 20 vues arrivent (avec un échec retenté)');
  assert.equal(new Set(place.extraViews.map(v=>v.url)).size,20);
  assert.equal(new Set(place.extraViews.map(v=>v.angle)).size,20,'Vingt angles différents');
  assert.ok(!place.extraViews.some(v=>Object.values(place.placeViews.day).includes(v.url)));
  const made=calls().slice(before);
  assert.equal(made.length,20);
  assert.ok(made.every(c=>c.prompt.startsWith('Style graphique imposé (« Seinen »)')&&c.prompt.includes('Nouvelle vue du lieu')&&c.prompt.includes('jamais un simple mur vide')&&c.refs===1));
  assert.equal(new Set(made.map(c=>c.key)).size,3,'Réparties sur les trois clés');
  await p.unroute('**/ai/generate');
  console.log('PASS 20 vues en arrière-plan, logiciel utilisable, échec retenté, clés réparties');

  // Annulation.
  await p.locator('[data-tab=places]').click();
  await p.getByRole('button',{name:'Générer 20 vues · chambre de Rinko',exact:true}).click();
  await p.waitForFunction(()=>extraJobs[project.places[0].id]?.done>=1&&!extraJobs[project.places[0].id].finished,null,{timeout:30000});
  await p.getByRole('button',{name:'Annuler les vues de chambre de Rinko',exact:true}).click();
  await p.waitForFunction(()=>extraJobs[project.places[0].id].finished,null,{timeout:30000});
  const kept=await p.evaluate(()=>project.places[0].extraViews.length);
  assert.ok(kept>20&&kept<40,'Annuler arrête la génération : '+kept);
  await delay(2500);
  assert.equal(await p.evaluate(()=>project.places[0].extraViews.length),kept);
  await p.evaluate(()=>flushWorkspace());

  // Fermeture et réouverture : les vues restent, et sont proposées pour une case.
  await p.close();p=await browser.newPage();p.setDefaultTimeout(15000);
  await p.goto(address);await p.waitForFunction(()=>workspaceReady);
  assert.equal(await p.evaluate(()=>project.places[0].extraViews.length),kept);
  await p.locator('[data-tab=places]').click();
  assert.equal(await p.locator('#placeGrid [data-extra-views] img').count(),kept);
  await p.locator('#apiToggle').click();await p.locator('#apiSecret').fill('test-secret-never-save');await p.locator('#addApiKey').click();await p.locator('#apiToggle').click();
  await p.locator('[data-tab=ai]').click();await p.locator('#listAgnesModels').click();await p.waitForFunction(()=>document.querySelector('#agnesModel').value);
  await p.locator('#aiPlace').selectOption({label:'chambre de Rinko'});
  const ask=p.locator('#placeViewDialog');await ask.waitFor({state:'visible'});
  assert.equal(await ask.locator('#placeViewGrid button').count(),kept+1,'Vue principale + vues en plus, en grille');
  const third=await p.evaluate(()=>project.places[0].extraViews[2]);
  await p.getByRole('button',{name:'Choisir la vue · Vue 3 : '+third.angle,exact:true}).click();
  await p.locator('#aiPrompt').fill('Rinko lit dans sa chambre');
  await preview(p,p.locator('#generate'));
  assert.ok(lastCall().prompt.includes('Vue choisie pour la case : Vue 3 : '+third.angle));
  console.log('PASS vues conservées après réouverture et proposées pour une case');
 }catch(error){console.error(error);process.exitCode=1}
 finally{if(browser)await browser.close();if(server){const done=once(server,'exit');server.kill();await done}}
})();
