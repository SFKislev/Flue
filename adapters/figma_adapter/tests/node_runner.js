'use strict';
// Test helper: runs the REAL plugin/code.js against the fake Figma API and speaks JSON lines.
// stdin : {"jid": "...", "job": {"op": ..., ...}}   (one per line)
// stdout: {"jid": "...", "res": {...}}                (one per line)
// The Python end-to-end test plays the role of the plugin window (ui.html) and pipes jobs here.
const readline = require('node:readline');
const plugin = require('../plugin/code.js');
const { MockFigma } = require('./figma_mock.js');

plugin.setFigma(new MockFigma());
plugin._state.evalOk = true;

let chain = Promise.resolve();
readline.createInterface({ input: process.stdin }).on('line', (line) => {
  chain = chain.then(async () => {
    const { jid, job } = JSON.parse(line);
    const res = await plugin.runJob(job);
    process.stdout.write(JSON.stringify({ jid, res }) + '\n');
  });
});
