// Offline streaming/queue checks: node tools/verification/verify_document_stream.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('../frontend/node_modules/typescript');
const code = ts.transpileModule(fs.readFileSync(path.join(__dirname, '../frontend/app/document-stream.ts'), 'utf8'), {
  compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020},
}).outputText;
const moduleExports = {};
new Function('exports', code)(moduleExports);
const {consumeDocumentStream, runFileQueue} = moduleExports;
const stream = chunks => new ReadableStream({start(controller) {
  for (const chunk of chunks) controller.enqueue(new TextEncoder().encode(chunk));
  controller.close();
}});

(async () => {
  const events = [];
  await consumeDocumentStream(stream([': heartbeat\r\n\r\ndata: {"type":"lo',
    'g","message":"日本語"}\r\n\r', '\ndata: {"type":"complete"}']), async event => events.push(event));
  assert.deepEqual(events.map(event => event.type), ['log', 'complete']);
  assert.equal(events[0].message, '日本語');
  const encoded = new TextEncoder().encode('data: {"type":"complete","filename":"日本語.pptx"}\n\n');
  const splitUnicode = new ReadableStream({start(controller) {
    for (const byte of encoded) controller.enqueue(Uint8Array.of(byte));
    controller.close();
  }});
  await consumeDocumentStream(splitUnicode, async event => assert.equal(event.filename, '日本語.pptx'));
  await assert.rejects(consumeDocumentStream(stream(['data: {"type":"log"}\n\n']), async () => {}), /before this file completed/);
  await assert.rejects(consumeDocumentStream(stream(['data: broken\n\n']), async () => {}), SyntaxError);
  await assert.rejects(consumeDocumentStream(stream(['data: {"type":"complete"}\n\n']), async () => {throw Error('download failed');}), /download failed/);
  await assert.rejects(consumeDocumentStream(stream(['data: {"type":"error","message":"failed"}\n\n']), async event => {throw Error(event.message);}), /failed/);
  let releaseFirst;
  const first = new Promise(resolve => {releaseFirst = resolve;});
  const completed = [];
  let active = 0;
  let maximum = 0;
  await runFileQueue([0, 1, 2], async item => {
    active++;
    maximum = Math.max(maximum, active);
    if (item === 0) await first;
    completed.push(item);
    if (item === 2) releaseFirst();
    active--;
  });
  assert.deepEqual(completed, [1, 2, 0]);
  assert.equal(maximum, 2);
  const outcomes = [];
  await runFileQueue([0, 1, 2], async item => {
    try {
      if (item === 0) throw Error('file failed');
      outcomes.push(item);
    } catch {
      outcomes.push('failed');
    }
  });
  assert.deepEqual(outcomes, ['failed', 1, 2]);
  await runFileQueue([], async () => assert.fail('empty queue started work'));
  console.log('9 streaming/queue checks passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
