// Onglet Style : exemples dessinés une fois, style appliqué à toutes les générations et sauvegardé avec le projet.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { once } = require('node:events');

const repo = path.resolve(__dirname, '..');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'inkforge-style-'));
const folder = path.join(tmp,'studio');
fs.mkdirSync(folder);
for(const name of ['INKFORGE.html','serveur_inkforge.py','version.json','LANCER_INKFORGE.cmd','LISEZ_MOI.txt'])fs.copyFileSync(path.join(repo,name),path.join(folder,name));
const port = process.env.INKFORGE_STYLE_PORT || '18767';
const address = 'http://127.0.0.1:'+port;
const delay = ms=>new Promise(r=>setTimeout(r,ms));
let server,browser;
const calls=()=>fs.readFileSync(path.join(folder,'metrics.jsonl'),'utf8').trim().split('\n').map(JSON.parse);


const keys=async p=>{await p.locator('#apiToggle').click();for(const name of ['a','b']){await p.locator('#apiSecret').fill('test-secret-'+name);await p.locator('#addApiKey').click()}await p.locator('#apiToggle').click()};
const lastPrompt=()=>calls().at(-1).prompt;
async function preview(p,button){
 await button.click();
 await p.waitForFunction(()=>aiBusy,null,{timeout:5000}).catch(()=>{});
 await p.waitForFunction(()=>!aiBusy,null,{timeout:60000});
 const title=await p.locator('#aiDialogTitle').textContent();
 assert.ok(/^(Référence de |Aperçu)/.test(title),title+' — '+await p.locator('#aiDialogStep').textContent());
}
(async()=>{
 try{
  server=spawn(process.env.PYTHON || 'python',[path.join(__dirname,'studio_fixture.py'),folder],{stdio:'inherit',env:{...process.env,INKFORGE_TEST_PORT:port}});
  for(let i=0;i<150;i++){try{const r=await fetch(address+'/health');await r.arrayBuffer();if(r.ok)break}catch{}await delay(100)}
  browser=await chromium.launchPersistentContext(path.join(tmp,'browser'),{headless:true,executablePath:process.env.CHROME_BIN||undefined});
  let p=await browser.newPage();p.setDefaultTimeout(15000);p.on('pageerror',e=>console.error('JS:',e.message));
  await p.goto(address);await p.waitForFunction(()=>typeof workspaceReady!=='undefined'&&workspaceReady);
  const nav=await p.locator('.nav [data-tab]').evaluateAll(b=>b.map(x=>x.dataset.tab));
  assert.equal(nav[0],'style','L’onglet Style est en premier');
  assert.ok(nav.indexOf('style')<nav.indexOf('characters')&&nav.indexOf('style')<nav.indexOf('places'));
  await p.evaluate(()=>change(()=>{project.title='Projet style'}));

  // 1. Huit cartes, chacune avec un exemple dessiné via les clés Agnes.
  await keys(p);
  await p.locator('[data-tab=style]').click();
  assert.equal(await p.locator('#styleGrid [data-style]').count(),8);
  await p.waitForFunction(()=>document.querySelectorAll('#styleGrid [data-style] img').length===8,null,{timeout:60000});
  const examples=calls().length;assert.equal(examples,8,'Un dessin par style');
  assert.equal(new Set(calls().map(c=>c.key)).size,2,'Exemples répartis sur les clés');
  assert.ok(calls().every(c=>c.prompt.includes('Style graphique imposé')));
  await p.evaluate(()=>flushWorkspace());
  await p.locator('[data-tab=characters]').click();await p.locator('[data-tab=style]').click();
  assert.equal(calls().length,examples,'Pas de nouveau dessin à la réouverture de l’onglet');
  const before=await p.locator('[data-style=chibi] img').getAttribute('src');
  await p.getByRole('button',{name:'Regénérer l’exemple · Chibi / comédie',exact:true}).click();
  await p.waitForFunction(old=>{const i=document.querySelector('[data-style=chibi] img');return i&&i.getAttribute('src')!==old},before,{timeout:60000});
  assert.equal(calls().length,examples+1);

  // 2. Shōnen : personnage et décor reçoivent le même style.
  await p.getByRole('button',{name:'Choisir ce style · Shōnen',exact:true}).click();
  await p.waitForFunction(()=>project.style==='shonen');
  assert.ok((await p.locator('[data-style=shonen] h3').textContent()).includes('Style actif'));
  await p.locator('[data-tab=characters]').click();await p.locator('#addChar').click();
  await p.locator('#memoryName').fill('Héros');await p.locator('#memoryAppearance').fill('cheveux en pointe, veste orange');
  await p.locator('#memorySave').click();
  await preview(p,p.locator('#characterGrid').getByRole('button',{name:'Générer · Face',exact:true}));
  assert.ok(lastPrompt().includes('Style graphique imposé (« Shōnen »)'));
  await p.locator('#aiAcceptImage').click();await p.waitForFunction(()=>project.characters[0].views?.front);
  await p.locator('[data-tab=places]').click();await p.locator('#addPlace').click();
  await p.getByLabel('Nom du décor').fill('Ruelle');await p.getByLabel('Description détaillée du lieu').fill('Ruelle étroite, néons');
  await p.locator('#memorySave').click();
  await p.locator('#placeGrid').getByRole('button',{name:'Revenir aux vues IA'}).click();
  await preview(p,p.locator('#placeGrid').getByRole('button',{name:'Générer · Vue principale',exact:true}));
  assert.ok(lastPrompt().startsWith('Style graphique imposé (« Shōnen »)')&&lastPrompt().split('\n\n')[1].startsWith('Vue '));
  await p.locator('#aiAcceptImage').click();await p.waitForFunction(()=>project.places[0].placeViews?.day?.main);

  // 3. Changement de style sur un projet déjà dessiné : on demande quoi faire.
  await p.locator('[data-tab=style]').click();
  await p.getByRole('button',{name:'Choisir ce style · Noir et blanc à trames',exact:true}).click();
  const ask=p.locator('#styleAskDialog');await ask.waitFor({state:'visible'});
  assert.ok((await p.locator('#styleAskText').textContent()).includes('1 personnage et 1 décor'));
  await p.locator('#styleCancel').click();await ask.waitFor({state:'hidden'});
  assert.equal(await p.evaluate(()=>project.style),'shonen','Annuler ne change rien');
  await p.getByRole('button',{name:'Choisir ce style · Noir et blanc à trames',exact:true}).click();
  await p.locator('#styleRedo').click();await p.waitForFunction(()=>project.style==='trames');
  assert.ok(await p.evaluate(()=>project.characters[0].styleOutdated&&project.places[0].styleOutdated));
  await p.locator('[data-tab=characters]').click();
  assert.equal(await p.locator('#characterGrid [data-style-outdated]').count(),1,'La fiche signale l’ancien style');

  // Une case générée suit le nouveau style.
  await p.locator('[data-tab=ai]').click();
  await p.locator('#aiPrompt').fill('Le héros court dans la ruelle');
  await p.locator('#generate').click();
  await p.waitForFunction(()=>aiBusy,null,{timeout:5000}).catch(()=>{});
  await p.waitForFunction(()=>!aiBusy,null,{timeout:60000});
  assert.ok(lastPrompt().includes('Le héros court dans la ruelle')&&lastPrompt().includes('Style graphique imposé (« Noir et blanc à trames »)'),lastPrompt());
  await p.locator('#aiCloseDialog').click();
  await p.evaluate(()=>flushWorkspace());

  // 4. Fermeture et réouverture : le style et les exemples sont conservés.
  await p.close();p=await browser.newPage();p.setDefaultTimeout(15000);
  await p.goto(address);await p.waitForFunction(()=>workspaceReady);
  assert.equal(await p.evaluate(()=>project.style),'trames');
  await p.locator('[data-tab=style]').click();
  assert.equal(await p.locator('#styleGrid [data-style] img').count(),8);
  assert.ok((await p.locator('[data-style=trames] h3').textContent()).includes('Style actif'));
  assert.equal(calls().length,examples+4,'Aucun nouveau dessin d’exemple après réouverture');

  // Un projet sans style garde ses consignes d’origine.
  await p.evaluate(()=>{change(()=>{delete project.style})});
  assert.equal(await p.evaluate(()=>withStyle('Consigne')),'Consigne');
  console.log('PASS onglet Style : 8 exemples gardés, style appliqué aux fiches, décors et cases, changement demandé, conservé après réouverture');
 }catch(error){console.error(error);process.exitCode=1}
 finally{if(browser)await browser.close();if(server){const done=once(server,'exit');server.kill();await done}}
})();
