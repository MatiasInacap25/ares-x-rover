// Real Chromium DOM controls -> real local Python engine -> panel D rendering.
// No mocked predictions, browser packages, or application modifications.
const port = process.argv[2];
const appPort = process.argv[3];
const tabs = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const ws = new WebSocket(tabs.find(t => t.type === 'page').webSocketDebuggerUrl);
await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
let serial = 0;
const pending = new Map();
ws.onmessage = event => {
  const message = JSON.parse(event.data);
  if (pending.has(message.id)) {
    const {resolve, reject} = pending.get(message.id);
    pending.delete(message.id);
    message.error ? reject(Error(JSON.stringify(message.error))) : resolve(message.result);
  }
};
function cdp(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++serial; pending.set(id, {resolve, reject});
    ws.send(JSON.stringify({id, method, params}));
  });
}
async function evaluate(expression) {
  const result = await cdp('Runtime.evaluate', {expression, awaitPromise: true, returnByValue: true});
  if (result.exceptionDetails) throw Error(JSON.stringify(result.exceptionDetails));
  return result.result.value;
}
try {
  await cdp('Page.enable');
  await cdp('Page.navigate', {url: `http://127.0.0.1:${appPort}/`});
  let ready = false;
  for (let i = 0; i < 300; i++) {
    ready = await evaluate('typeof S !== "undefined" && !!S && !!META && !busy');
    if (ready) break;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  if (!ready) throw Error('Dashboard did not initialize: ' + await evaluate('document.body.innerText.slice(-1000)'));
  const results = await evaluate(`(${async function run() {
    const results = [];
    const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
    const check = (condition, detail) => { if (!condition) throw Error(detail); };
    const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
    const realApi = api;
    let replies = 0;
    api = async (...args) => { const result = await realApi(...args); replies++; return result; };
    const value = (id, v) => { $(id).value = v; $(id).dispatchEvent(new Event('input', {bubbles: true})); };
    async function waitFor(predicate, label) {
      for (let i = 0; i < 600; i++) { if (predicate()) return; await sleep(20); }
      throw Error('Timeout: ' + label + '; message=' + $('msg').textContent);
    }
    async function click(selector, request = true) {
      const n = replies;
      const el = document.querySelector(selector);
      check(el, 'Missing control ' + selector); el.click();
      if (request) await waitFor(() => replies > n && !busy, selector);
      await sleep(30);
    }
    async function fresh() {
      running = false; ++runId; setNN('live');
      if (travelSkip) travelSkip();
      await call('ghosts', {enabled: false});
      await call('configure', {planet: 'Marte', mode: 'rover', policy: 'hibrido', seed: 42,
        difficulty: 'medium', battery: 100, step_duration: 1, drone: false});
      value('fMode', 'rover'); value('fPolicy', 'hibrido'); value('fSeed', 42);
      value('fDiff', 'medium'); value('fBattery', 100); value('fDur', 1);
      value('fSpeed', 2); value('fTool', ''); setDestMode(false);
      await click('#bStep'); check(S.rna, 'Expected a live prediction after Paso');
    }
    function liveRendered() {
      check($('nnCell').textContent === '(' + S.rna.cell + ')', 'D shows the wrong cell');
      for (const feature of META.features) {
        check(Math.abs(Number($('nf_' + feature).value) - S.rna.features[feature]) <= .006,
          'D input differs from engine: ' + feature);
      }
      check($('nnDecision').textContent.includes(S.rna.label), 'D label differs from engine');
      check($('nnProbs').querySelectorAll('.prob').length === 3, 'D must show three probabilities');
    }
    async function test(name, body) {
      try { await fresh(); await body(); results.push({name, passed: true}); }
      catch (error) { results.push({name, passed: false, error: String(error)}); }
    }
    await test('Paso refreshes all live D inputs, class, cell and probabilities', async () => liveRendered());
    await test('All configuration fields remain deferred until Apply', async () => {
      const before = JSON.stringify(S); const prediction = $('nnProbs').innerHTML;
      value('fMode', 'sonda'); value('fPolicy', 'sin_ag'); value('fSeed', 7);
      value('fDiff', 'high'); value('fBattery', 80); value('fDur', 2);
      check(JSON.stringify(S) === before && $('nnProbs').innerHTML === prediction, 'Form edit changed live D');
      await click('#bApply');
      for (const [key, v] of Object.entries({mode: 'sonda', policy: 'sin_ag', seed: 7,
        difficulty: 'high', battery: 80, step_duration: 2})) check(S.config[key] === v, 'Apply ignored ' + key);
      check(S.rna === null && $('nnProbs').textContent.includes('Sin predicción'), 'Apply kept prediction');
      await click('#bStep'); liveRendered();
    });
    for (const policy of Object.keys(META.policies)) await test('Policy selector: ' + policy, async () => {
      value('fPolicy', policy); await click('#bApply'); await click('#bStep');
      if (['sin_rna', 'control', 'ag_puro'].includes(policy)) {
        check(S.rna === null && $('nnProbs').textContent.includes('Sin predicción'), 'Disabled RNA still appears');
      } else liveRendered();
    });
    for (const planet of META.planets) await test('Planet button: ' + planet.name, async () => {
      await click('[data-planet="' + planet.name + '"]');
      if (!planet.rocky) {
        check(S.planet.name === 'Marte' && $('fMode').value === 'sonda', 'Gas planet must reject wheels');
        await click('[data-planet="' + planet.name + '"]');
      }
      // the button validates first and configures after: wait for the configure reply, not the first one
      await waitFor(() => S.planet.name === planet.name && !busy, 'planet ' + planet.name);
      check(S.rna === null, 'Planet did not reset prediction');
      if (travelSkip) travelSkip(); await click('#bStep');
      if (S.rna) liveRendered();
      else check($('nnProbs').textContent.includes('Sin predicción'), 'D shows a nonexistent prediction');
    });
    for (const selector of ['#bReset', '#bApply', '#bGhost']) {
      await test(selector + ' clears stale live feature inputs', async () => {
        const old = META.features.map(f => $('nf_' + f).value);
        await click(selector);
        check(S.rna === null && $('nnCell').textContent === '', 'Prediction/cell not cleared');
        const inputs = META.features.map(f => $('nf_' + f));
        check(!same(old, inputs.map(el => el.value)) || inputs.every(el => el.disabled),
          'D cleared probabilities but retained all six editable inputs from the previous inference: ' + old);
      });
    }
    for (const button of document.querySelectorAll('[data-ev]')) {
      const selector = '[data-ev="' + button.dataset.ev + '"]' +
        (button.dataset.sensor ? '[data-sensor="todos"]' : ':not([data-sensor])');
      await test('Event button: ' + button.textContent, async () => {
        const before = JSON.stringify(S.rna); const count = S.event_feed.total;
        await click(selector);
        check(JSON.stringify(S.rna) === before && S.event_feed.total === count + 1, 'Event changed inference before sensing');
        await click('#bStep');
        if (S.rna) liveRendered();
        else check($('nnProbs').textContent.includes('Sin predicción'), 'Invalid inference displayed');
      });
    }
    for (let speed = 0; speed < 6; speed++) await test('Start/pause at speed ' + SPEEDS[speed], async () => {
      value('fSpeed', speed); await click('#bRun');
      await waitFor(() => S.status.step >= 2, 'automatic step');
      await click('#bRun', false); await waitFor(() => !busy, 'pause');
      const step = S.status.step; await sleep(1500);
      check(!running && S.status.step === step, 'Paused mission kept stepping'); liveRendered();
    });
    await test('Ghost toggles refresh the main live inference', async () => {
      for (const selector of ['#bGhost', '#bGhost']) {
        await click(selector); check(S.rna === null, 'Toggle kept old prediction');
        await click('#bStep'); liveRendered();
      }
    });
    await test('Drone toggles keep the mission, its step and the live inference', async () => {
      for (const selector of ['#bDrone', '#bDrone']) {
        const step = S.status.step, rna = JSON.stringify(S.rna);
        await click(selector);
        check(S.status.step === step && JSON.stringify(S.rna) === rna, 'Drone toggle restarted the mission');
        await click('#bStep'); liveRendered();
      }
    });
    await test('Destination and terrain tools preserve D until next step', async () => {
      const cell = S.rna.cell; await click('#bDest', false); cellAction(...cell);
      await waitFor(() => !busy && S.map.destinations.length === 1, 'destination');
      await click('#bDest', false); await click('#bDestClear');
      check(S.map.destinations.length === 0, 'Clear destinations ignored');
      for (const kind of ['', 'obstaculo', 'barranco', 'limpiar']) {
        const before = JSON.stringify(S.rna); value('fTool', kind); cellAction(...cell);
        await waitFor(() => !busy, 'terrain');
        check(JSON.stringify(S.rna) === before, 'Tool changed prediction before sensing');
      }
      await click('#bStep'); liveRendered();
    });
    for (const format of ['csv', 'json', 'comparison_csv']) await test('Export button: ' + format, async () => {
      const before = JSON.stringify(S); const probs = $('nnProbs').innerHTML;
      await click('[data-export="' + format + '"]');
      check(JSON.stringify(S) === before && $('nnProbs').innerHTML === probs, 'Export changed D');
      check($('msg').textContent.includes(format === 'comparison_csv' ? 'Primero' : 'Exportado'), 'Export feedback missing');
    });
    await test('D Prueba remains independent of C and En vivo restores mission inference', async () => {
      await click('[data-nn="test"]'); await waitFor(() => nnTest !== null, 'manual prediction');
      const before = $('nnProbs').innerHTML; await click('#bStep');
      check($('nnProbs').innerHTML === before, 'Mission overwrote Prueba');
      await click('[data-nn="live"]', false); liveRendered();
    });
    running = false; ++runId;
    return results;
  }} )()`);
  process.stdout.write(JSON.stringify(results));
} finally {
  ws.close();
}
