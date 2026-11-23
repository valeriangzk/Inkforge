// Scène : style en premier, meubles non dupliqués, vue opposée large, choix de la vue du décor, rognage d'une case.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { once } = require('node:events');

const repo = path.resolve(__dirname, '..');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'inkforge-scene-'));
const folder = path.join(tmp,'studio');
fs.mkdirSync(folder);
for(const name of ['INKFORGE.html','serveur_inkforge.py','version.json','LANCER_INKFORGE.cmd','LISEZ_MOI.txt'])fs.copyFileSync(path.join(repo,name),path.join(folder,name));
const port = process.env.INKFORGE_SCENE_PORT || '18768';
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
  const p=await browser.newPage();p.setDefaultTimeout(15000);p.on('pageerror',e=>console.error('JS:',e.message));
  await p.goto(address);await p.waitForFunction(()=>typeof workspaceReady!=='undefined'&&workspaceReady);
  await p.locator('#apiToggle').click();await p.locator('#apiSecret').fill('test-secret-never-save');await p.locator('#addApiKey').click();await p.locator('#apiToggle').click();
  await p.evaluate(()=>change(()=>{project.title='Rinko';project.style='seinen'}));

  // 1. Le style passe en premier, avant la description et les consignes.
  await p.locator('[data-tab=characters]').click();await p.locator('#addChar').click();
  await p.locator('#memoryName').fill('Rinko');await p.locator('#memoryAppearance').fill('lycéenne, cheveux noirs mi-longs, gilet bleu');
  await p.locator('#memorySave').click();
  const face=()=>p.locator('#characterGrid').getByRole('button',{name:/^(Générer|Régénérer) · Face$/});
  await preview(p,face());
  const seinen=lastCall().prompt;
  assert.ok(seinen.startsWith('Style graphique imposé (« Seinen »)'),seinen.slice(0,80));
  assert.ok(seinen.indexOf('Angle demandé')>seinen.indexOf('Seinen'));
  await accept(p);
  await p.evaluate(()=>change(()=>{project.style='chibi'}));
  await preview(p,face());
  const chibi=lastCall().prompt;
  assert.ok(chibi.startsWith('Style graphique imposé (« Chibi / comédie »)'));
  assert.equal(seinen.split('\n\n')[1].split('Variante')[0],chibi.split('\n\n')[1].split('Variante')[0],'Même description, seul le style change');
  await p.locator('#aiCloseDialog').click();
  console.log('PASS style placé en premier dans chaque génération');

  // 3. Vue opposée : même cadrage large que la vue principale, pas de gros plan.
  await p.locator('[data-tab=places]').click();await p.locator('#addPlace').click();
  await p.getByLabel('Nom du décor').fill('chambre de Rinko');await p.getByLabel('Description détaillée du lieu').fill('Chambre avec un bureau, un PC, une lampe et un lit');
  await p.locator('#memorySave').click();
  await p.locator('#placeGrid').getByRole('button',{name:'Revenir aux vues IA'}).click();
  await preview(p,p.locator('#placeGrid').getByRole('button',{name:'Générer · Vue principale',exact:true}));await accept(p);
  await preview(p,p.locator('#placeGrid').getByRole('button',{name:'Générer · Vue opposée',exact:true}));
  const opposite=lastCall().prompt;
  assert.ok(opposite.includes('pivote de 180°')&&opposite.includes('même cadrage large')&&opposite.includes('Aucun gros plan'),opposite);
  await accept(p);
  console.log('PASS vue opposée large et cohérente');

  // 4. Choix de la vue du décor, puis 2. consignes contre les meubles dupliqués.
  await p.locator('[data-tab=ai]').click();
  await p.locator('#aiCharacter').selectOption({label:'Rinko'});
  await p.locator('#aiPlace').selectOption({label:'chambre de Rinko'});
  const ask=p.locator('#placeViewDialog');await ask.waitFor({state:'visible'});
  assert.equal(await ask.locator('#placeViewGrid button').count(),2,'Un aperçu par vue enregistrée');
  assert.equal(await ask.locator('#placeViewGrid img').count(),2);
  await p.getByRole('button',{name:'Choisir la vue · Vue opposée',exact:true}).click();await ask.waitFor({state:'hidden'});
  assert.ok((await p.locator('#aiPlaceView').textContent()).includes('Vue opposée'));
  await p.locator('#aiPrompt').fill('Rinko assise à son bureau, regardant son PC en souriant');
  await preview(p,p.locator('#generate'));
  const panel=lastCall();
  assert.ok(panel.prompt.startsWith('Style graphique imposé (« Chibi / comédie »)'));
  const order=['Style graphique imposé','Rinko assise à son bureau','Consignes d’intégration'].map(t=>panel.prompt.indexOf(t));
  assert.ok(order.every(i=>i>=0)&&order[0]<order[1]&&order[1]<order[2],'Style, puis description, puis intégration');
  assert.ok(panel.prompt.includes('n’en double aucun')&&panel.prompt.includes('c’est le meuble déjà visible dans le décor qui est utilisé'));
  assert.ok(panel.prompt.includes('Vue choisie pour la case : Vue opposée'));
  assert.equal(panel.refs,2,'Seule la vue choisie part comme décor (plus la face de Rinko)');
  await accept(p);
  console.log('PASS choix de la vue du décor et consignes contre les meubles dupliqués');

  // 5. Rogner l’image d’une case.
  await p.locator('[data-tab=editor]').click();
  const frame=p.locator('#page .frame').first();
  const before=await p.evaluate(()=>project.pages[page][0]);
  assert.ok(before.img);
  await frame.click({button:'right'});
  const menuCrop=p.getByRole('button',{name:'Rogner l’image',exact:true});
  assert.ok(await menuCrop.isVisible());
  assert.ok(await p.getByRole('button',{name:'Effacer la case',exact:true}).isVisible(),'Le reste du menu est conservé');
  await menuCrop.click();
  const dialog=p.locator('#cropDialog');await dialog.waitFor({state:'visible'});
  await p.locator('#cropCancel').click();await dialog.waitFor({state:'hidden'});
  assert.equal(await p.evaluate(()=>project.pages[page][0].img),before.img,'Annuler ne change rien');
  await frame.click({button:'right'});await menuCrop.click();await dialog.waitFor({state:'visible'});
  await p.locator('#cropZoom').evaluate(el=>{el.value='2';el.dispatchEvent(new Event('input'))});
  const box=await p.locator('#cropView').boundingBox();
  await p.mouse.move(box.x+box.width/2,box.y+box.height/2);await p.mouse.down();await p.mouse.move(box.x+box.width/2+60,box.y+box.height/2+30,{steps:5});await p.mouse.up();
  await p.locator('#cropApply').click();await dialog.waitFor({state:'hidden'});
  await p.evaluate(()=>flushWorkspace());
  const after=await p.evaluate(()=>project.pages[page][0]);
  assert.notEqual(after.img,before.img);assert.ok(/^\/media\//.test(after.img));
  assert.deepEqual(after.crop,{from:before.img,result:after.img});
  const ratio=await p.evaluate(async url=>{const i=new Image();i.src=url;await i.decode();return i.naturalWidth/i.naturalHeight},after.img);
  const expected=(after.w*600)/(after.h*820);
  assert.ok(Math.abs(ratio-expected)/expected<0.01,'Proportions exactes de la case : '+ratio+' / '+expected);
  assert.equal(await frame.locator('img').getAttribute('src'),after.img,'L’image rognée remplit la case');
  // Une case vide ne propose pas le rognage.
  await p.evaluate(()=>change(()=>{project.pages[page][1].img=''}));
  await p.locator('#page .frame').nth(1).click({button:'right'});
  assert.ok(!(await menuCrop.isVisible()));
  console.log('PASS rognage d’une case aux proportions exactes, annulable');
 }catch(error){console.error(error);process.exitCode=1}
 finally{if(browser)await browser.close();if(server){const done=once(server,'exit');server.kill();await done}}
})();
