// Test both the protected first installation and migration through the already-shipped updater.
const {chromium}=require('playwright'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),cp=require('node:child_process');
const {once}=require('node:events');
const repo=path.resolve(__dirname,'..'),tmp=fs.mkdtempSync(path.join(os.tmpdir(),'inkforge-migration-'));
const python=process.env.PYTHON||'python',dist=path.join(tmp,'dist');
// Playwright owns the browser in this test. Avoid opening a second Edge profile
// through the genuine Windows launcher and leaving it running after the test.
const control=path.join(tmp,'test-browser');
fs.mkdirSync(control);fs.writeFileSync(path.join(control,'sitecustomize.py'),'import webbrowser\nwebbrowser.open = lambda *args, **kwargs: True\n');

const url='http://127.0.0.1:'+(process.env.INKFORGE_MIGRATION_PORT||(process.platform==='win32'?8765:18766));
const wait=ms=>new Promise(r=>setTimeout(r,ms));
let server,closed,context;
async function stop(){
 if(!server)return;
 if(server.exitCode===null && server.signalCode===null){
  if(process.platform==='win32'){
   // A batch file can still have PowerShell and Python running in the fixture directory.
   cp.spawnSync('taskkill',['/PID',String(server.pid),'/T','/F'],{stdio:'ignore'});
  }else server.kill();
 }
 await closed;
 server=null;
}
async function start(folder,mode){
 console.log('Ouverture du service de test',mode);
 const env={...process.env,PYTHONUNBUFFERED:'1',PYTHONPATH:[control,process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),LOCALAPPDATA:path.join(folder,'test-local'),INKFORGE_MIGRATION_PORT:new URL(url).port};
 if(process.platform==='win32'){
  const assistant=mode==='prepare';
  const cmd=assistant?'MISE_A_JOUR_INKFORGE.cmd':mode==='studio'?'LANCER_INKFORGE.cmd':'RESTAURER_INKFORGE.cmd';
  if(assistant)fs.copyFileSync(path.join(dist,cmd),path.join(folder,cmd));
  server=cp.spawn('cmd.exe',['/d','/c',cmd,...(assistant?['.']:[])],{stdio:'inherit',cwd:folder,env});
 }else server=cp.spawn(python,[path.join(__dirname,'migration_server.py'),folder,mode,path.join(dist,'inkforge-update.zip')],{stdio:'inherit',env});
 closed=once(server,'exit');
 const deadline=Date.now()+60000;
 while(Date.now()<deadline){
  if(server.exitCode!==null || server.signalCode!==null)throw Error('Arrêt du service '+mode+' avant son ouverture ('+(server.exitCode??server.signalCode)+').');
  try{
   const r=await fetch(url,{signal:AbortSignal.timeout(1500)});
   await r.arrayBuffer();
   if(r.ok)return;
  }catch{}
  await wait(200);
 }
 throw Error('Le service '+mode+' n’a pas ouvert le port dans le délai de 60 secondes.');
}
async function flow(protectedFirst){
 const folder=path.join(tmp,protectedFirst?'protected':'ordinary');fs.mkdirSync(folder);
 for(const name of ['INKFORGE.html','serveur_inkforge.py','version.json','LANCER_INKFORGE.cmd','LISEZ_MOI.txt']){
  fs.writeFileSync(path.join(folder,name),cp.execFileSync('git',['show','v2.4.2:'+name],{cwd:repo}));
 }
 const model=path.join(folder,'test-local','INKFORGE','TripoSR','models','a'.repeat(64),'model.glb');fs.mkdirSync(path.dirname(model),{recursive:true});fs.writeFileSync(model,'old-model');
 const runtime=path.join(folder,'test-local','INKFORGE','TripoSR','ready-v1');fs.writeFileSync(runtime,'installed');
 await start(folder,'studio');
 context=await chromium.launchPersistentContext(path.join(tmp,'profile'+protectedFirst),{headless:true,executablePath:process.env.CHROME_BIN||undefined});
 const p=await context.newPage();p.on('dialog',d=>d.accept());p.on('pageerror',e=>console.error(e));await p.goto(url);
 const id=await p.evaluate(()=>{
   project.title='Version précédente';const canvas=document.createElement('canvas');canvas.width=canvas.height=4;
   const src=canvas.toDataURL();project.characters.push({id:'old',name:'Fiche précédente',references:[src],img:src,model3d:'a'.repeat(64)});
   project.places.push({id:'old-place',name:'Décor précédent',img:src});project.pages[0][0].img=src;persist(true);document.getElementById('saveVersion').click();
   localStorage.setItem('unrelated','kept');return project.id;
 });
 if(protectedFirst){
   await stop();await start(folder,'prepare');await p.goto(url);await p.getByRole('button',{name:'Installer la mise à jour'}).click();
   await p.waitForFunction(()=>document.querySelector('#status')?.textContent.includes('prête'));
   await closed;server=null;
 }else{
   const old=await p.evaluate(async b64=>{const bytes=Uint8Array.from(atob(b64),c=>c.charCodeAt(0));
     const r=await fetch('/updates/install',{method:'POST',headers:{'Content-Type':'application/zip'},body:bytes});return r.json()
   },fs.readFileSync(path.join(dist,'inkforge-update.zip')).toString('base64'));
   assert.equal(old.version,'2.7.4');await stop();
 }
 await start(folder,'studio');await p.goto(url);await p.waitForFunction(()=>typeof workspaceReady!=='undefined'&&workspaceReady);
 assert.deepEqual(await p.evaluate(()=>[Object.keys(workspace.projects).length,project.characters.length,project.places.length,current().img]),[0,0,0,'']);
 assert.equal(await p.evaluate(()=>Object.keys(localStorage).some(k=>k.startsWith('inkforge-experiments/'))),false);
 assert.equal(await p.evaluate(()=>localStorage.getItem('unrelated')),'kept');
 assert.ok(fs.existsSync(path.join(folder,'_secours_inkforge.zip'))&&fs.existsSync(runtime)&&!fs.existsSync(model));
 await p.reload();await p.waitForFunction(()=>workspaceReady);assert.equal(await p.evaluate(()=>Object.keys(workspace.projects).length),0);
 if(protectedFirst){
   await stop();await start(folder,'rescue');await p.goto(url);await p.getByRole('button',{name:'Restaurer la version de secours'}).click();
   await p.waitForFunction(()=>document.querySelector('#status')?.textContent.includes('prête'));await closed;server=null;
 }else{
   await p.locator('#inkUpdateOpen').click();await p.locator('#inkRestore').click();
   await p.waitForFunction(()=>document.querySelector('#inkUpdateStatus').textContent.includes('prête'));await stop();
 }
 await start(folder,'studio');await p.goto(url);
 assert.equal(await p.evaluate(()=>project.id),id);assert.equal(await p.evaluate(()=>project.title),'Version précédente');
 assert.equal(await p.evaluate(()=>project.characters[0].name),'Fiche précédente');assert.equal(await p.evaluate(()=>project.places[0].name),'Décor précédent');
 assert.ok(await p.evaluate(()=>JSON.parse(localStorage.getItem(versionKey())).length===1));await p.waitForFunction(()=>document.querySelector('.frame img')?.naturalWidth===4);
 assert.equal(fs.readFileSync(model,'utf8'),'old-model');assert.ok(fs.existsSync(runtime));
 await context.close();context=null;await stop();console.log('PASS '+(protectedFirst?'assistant de première installation et secours indépendant':'bouton 2.4.2, protection avant effacement et restauration depuis le studio')+' avec les projets et modèles initiaux');
}
async function blockedStartup(){
 const folder=path.join(tmp,'Studio de vérification');fs.mkdirSync(folder);
 const files=['INKFORGE.html','serveur_inkforge.py','version.json','LANCER_INKFORGE.cmd','LISEZ_MOI.txt'];
 function tagged(tag,name){return cp.execFileSync('git',['show',tag+':'+name],{cwd:repo})}
 for(const name of files)fs.writeFileSync(path.join(folder,name),tagged('v2.7.1',name));
 const source=path.join(tmp,'previous');fs.mkdirSync(source);
 for(const name of files)fs.writeFileSync(path.join(source,name),tagged('v2.7.3',name));
 const previous=path.join(tmp,'previous.zip');
 cp.execFileSync(python,['-m','zipfile','-c',previous,...files],{cwd:source});
 await start(folder,'studio');
 context=await chromium.launchPersistentContext(path.join(tmp,'repair-profile'),{headless:true,executablePath:process.env.CHROME_BIN||undefined});
 const page=await context.newPage(),errors=[];page.on('pageerror',err=>errors.push(err.message));page.on('dialog',d=>d.accept());
 await page.goto(url);await page.waitForFunction(()=>workspaceReady);
 const sent=await page.evaluate(async data=>{
  const bytes=Uint8Array.from(atob(data),c=>c.charCodeAt(0));
  return (await fetch('/updates/install',{method:'POST',headers:{'Content-Type':'application/zip','X-Inkforge-Version':studioVersion},body:bytes})).json();
 },fs.readFileSync(previous).toString('base64'));
 assert.equal(sent.version,'2.7.3');
 await page.reload();await page.waitForFunction(()=>document.querySelector('#workLoading').textContent.includes('Ouverture interrompue'));
 const versions=await page.evaluate(async()=>[studioVersion,(await (await fetch('/work/status')).json()).version]);
 assert.deepEqual(versions,['2.7.3','2.7.1']);
 console.log('Incident reproduit en rechargeant après installation : page',versions[0],'relais',versions[1],await page.locator('#workLoading').innerText());
 await stop();await start(folder,'studio');await page.goto(url);await page.waitForFunction(()=>workspaceReady);
 await page.evaluate(async()=>{project.title='Travail avant réparation';await persist(true)});
 const workFile=path.join(folder,'_inkforge_travail','state.json'),rescueFile=path.join(folder,'_secours_inkforge.zip');
 const work=fs.readFileSync(workFile),rescue=fs.readFileSync(rescueFile);
 await stop();await start(folder,'prepare');await page.goto(url);
 await page.getByRole('button',{name:'Réparer INKFORGE et garder mes données'}).click();
 await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('prête'));await closed;server=null;
 assert.deepEqual(fs.readFileSync(workFile),work);assert.deepEqual(fs.readFileSync(rescueFile),rescue);
 for(let launch=0;launch<2;launch++){
  await start(folder,'studio');await page.goto(url);await page.waitForFunction(()=>workspaceReady);
  assert.equal(await page.evaluate(()=>studioVersion),'2.7.4');assert.equal(await page.evaluate(()=>project.title),'Travail avant réparation');
  for(const tab of ['characters','places','studio3d','ai','projects','editor']){
   await page.locator('[data-tab='+tab+']').click();assert.ok(await page.locator('#'+tab).isVisible());
  }
  await stop();
 }
 assert.deepEqual(errors,[]);await context.close();context=null;
 console.log('PASS réparation autonome sur installation 2.7.3, travail et secours identiques, deux lancements et navigation.');
}
(async()=>{try{cp.execFileSync(python,[path.join(repo,'tools','prepare_release.py'),dist]);await flow(true);await flow(false);await blockedStartup()}
 catch(error){console.error('Échec du parcours de migration',error);throw error}
 finally{await context?.close();await stop();fs.rmSync(tmp,{recursive:true,force:true,maxRetries:5,retryDelay:150})}})().catch(e=>{console.error(e);process.exitCode=1});
