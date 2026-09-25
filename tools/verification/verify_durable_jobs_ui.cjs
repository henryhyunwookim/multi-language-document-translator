// Offline HTTP/credential/download contracts for the durable-job UI.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('../frontend/node_modules/typescript');
const source = fs.readFileSync(path.join(__dirname, '../frontend/app/durable-jobs.ts'), 'utf8');
const code = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}}).outputText;
const helpers = {};
new Function('exports', code)(helpers);

(async () => {
  const batch = {id: 'batch', token: 'private-capability'};
  assert.deepEqual(helpers.authorization(batch), {Authorization: 'Bearer private-capability'});
  assert.deepEqual(helpers.glossaryPairs('company = preferred name\n\nterm = target'), {company: 'preferred name', term: 'target'});
  assert.throws(() => helpers.glossaryPairs('no delimiter'), /source term/);
  let request;
  global.fetch = async (url, options) => {request = {url, options}; return new Response(JSON.stringify({id: 'batch', jobs: [], finished: false}));};
  const controller = new AbortController();
  const snapshot = await helpers.batchSnapshot('https://service.example', batch, controller.signal);
  assert.equal(snapshot.id, 'batch');
  assert.equal(request.options.headers.Authorization, 'Bearer private-capability');
  assert.equal(request.options.cache, 'no-store');
  assert(!request.url.includes(batch.token));
  global.fetch = async () => new Response('expired', {status: 410});
  await assert.rejects(helpers.batchSnapshot('', batch, controller.signal), /410/);
  global.fetch = async (url, options) => {request = {url, options}; return new Response('content');};
  const result = await helpers.jobDownload('', batch, {id: 'file', filename: 'figure.png'}, 'artifact');
  assert.equal(result.filename, 'figure_translated.md');
  assert(result.url.startsWith('blob:'));
  URL.revokeObjectURL(result.url);
  const report = await helpers.jobDownload('', batch, {id: 'file', filename: 'figure.png'}, 'report');
  assert.equal(report.filename, 'figure.png.quality.json');
  URL.revokeObjectURL(report.url);
  global.fetch = async () => new Response('not ready', {status: 404});
  await assert.rejects(helpers.jobDownload('', batch, {id: 'file', filename: 'file.txt'}, 'artifact'), /404/);
  console.log('8 durable-job UI contract checks passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
