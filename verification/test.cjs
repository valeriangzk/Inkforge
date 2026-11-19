const {chromium} = require('playwright')
const assert = require('node:assert/strict')
const {spawn} = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')
const os = require('node:os')

async function main() {
  const old = process.argv[2]
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'inkforge-test-'))
  const files = ['INKFORGE.html','serveur_inkforge.py','version.json']
  for (const filename of files) fs.copyFileSync(path.join(old,filename),path.join(dir,filename))
  const url = 'http://127.0.0.1:8765'
  const browser = await chromium.launch(process.env.CHROMIUM_BIN ? {executablePath:process.env.CHROMIUM_BIN} : {})
  let server
  async function stop() {
    if (!server || server.exitCode !== null) return
    const exited = new Promise(resolve => server.once('exit',resolve))
    server.kill()
    await exited
  }
  async function start(mode) {
    server = spawn(process.env.PYTHON || 'python',[path.join(__dirname,'serve-test.py'),dir,__dirname],{
      stdio:'inherit',env:{...process.env,INKFORGE_TEST_MODE:mode}
    })
    for(let tries=0;tries<60;tries++){
      try{ if ((await fetch(url+'/health')).ok) return }catch{}
      await new Promise(resolve=>setTimeout(resolve,100))
    }
    throw Error('Server failed to start')
  }
  try {
    await start('truncated')
    const page = await browser.newPage()
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    page.on('dialog', dialog=>dialog.accept())
    await page.goto(url)
    await page.locator('#inkUpdateClose').click()
    await page.evaluate(()=>{
      const title = document.getElementById('titleInput')
      title.value = 'Projet de vérification'
      title.dispatchEvent(new Event('change'))
      localStorage.setItem('inkforge-tooltips-enabled','false')
    })
    const snapshot = await page.evaluate(()=>({
      active:localStorage.getItem('inkforge-v2-active'),
      projects:localStorage.getItem('inkforge-v2-projects'),
      tooltips:localStorage.getItem('inkforge-tooltips-enabled')
    }))
    assert.match(snapshot.projects,/Projet de vérification/)
    await page.locator('#inkUpdateOpen').click()
    await page.locator('#inkUpdateAuto').click()
    await page.getByText(/Échec du contrôle SHA-256/).waitFor()
    for (const name of files)
      assert.deepEqual(fs.readFileSync(path.join(dir,name)),fs.readFileSync(path.join(old,name)))
    await stop()
    await start('good')
    await page.reload()
    await page.getByText(/Mise à jour disponible — INKFORGE 2.3.1/).waitFor()
    await page.locator('#inkUpdateAuto').click()
    await page.getByText(/Version 2.3.1 installée/).waitFor()
    assert.equal(JSON.parse(fs.readFileSync(path.join(dir,'version.json'))).version,'2.3.1')
    await stop()
    await start('good')
    await page.reload()
    assert.equal(await page.locator('#titleInput').inputValue(),'Projet de vérification')
    assert.equal(await page.evaluate(()=>localStorage.getItem('inkforge-v2-active')),snapshot.active)
    assert.equal(await page.evaluate(()=>localStorage.getItem('inkforge-tooltips-enabled')),snapshot.tooltips)
    await page.locator('#inkUpdateOpen').click()
    await page.getByText(/Aucune mise à jour plus récente disponible/).waitFor()
    assert.equal(await page.locator('#inkUpdateAuto').isVisible(),false)
    assert.deepEqual(errors,[])
    console.log('PASS: version detection, interrupted download, one-click install, restart, stored project/settings')
  } finally {
    await browser.close()
    await stop()
    fs.rmSync(dir,{recursive:true,force:true})
  }
}
main().catch(error=>{console.error(error);process.exitCode=1})
