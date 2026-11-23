// Aides communes : toutes les générations passent par la file en arrière-plan.
const assert = require('node:assert/strict');
const SETTLED = ['done','ready','failed','cancelled'];
// Clique sur le déclencheur, attend que les tâches ajoutées à la file soient terminées et renvoie la dernière.
async function settle(p, trigger, timeout = 120000) {
 const before = await p.evaluate(() => generationQueue.length);
 await trigger.click();
 await p.waitForFunction(n => generationQueue.length > n, before, { timeout: 15000 });
 await p.waitForFunction(([n, done]) => generationQueue.slice(n).every(j => done.includes(j.status)), [before, SETTLED], { timeout });
 return p.evaluate(() => { const j = generationQueue.at(-1); return { id: j.id, status: j.status, error: j.error, label: j.label }; });
}
// Ouvre l'aperçu d'une vue terminée depuis le panneau de la file.
async function openResult(p, job) {
 assert.equal(job.status, 'ready', (job.label || '') + ' — ' + job.error);
 await p.locator('[data-queue-job="' + job.id + '"]').getByRole('button', { name: /^Voir/ }).click();
 await p.locator('#aiProgressDialog').waitFor({ state: 'visible' });
}
// Lance une vue, ouvre son aperçu : remplace l'ancien enchaînement bloquant.
async function preview(p, trigger) { const job = await settle(p, trigger); await openResult(p, job); return job; }
module.exports = { settle, openResult, preview, SETTLED };
