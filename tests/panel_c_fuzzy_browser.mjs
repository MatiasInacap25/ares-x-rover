// Isolated Chromium, real DOM controls, real Python API; no mocked inference.
const [port, appPort] = process.argv.slice(2);
const tabs = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const ws = new WebSocket(tabs.find(t => t.type === 'page').webSocketDebuggerUrl);
await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
let serial = 0;
const pending = new Map();
ws.onmessage = event => {
  const message = JSON.parse(event.data), request = pending.get(message.id);
  if (request) {
    pending.delete(message.id);
    message.error ? request.reject(Error(JSON.stringify(message.error))) : request.resolve(message.result);
  }
};
function cdp(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++serial; pending.set(id, {resolve, reject});
    ws.send(JSON.stringify({id, method, params}));
  });
}
async function evaluate(expression) {
  const r = await cdp('Runtime.evaluate', {expression, awaitPromise: true, returnByValue: true});
  if (r.exceptionDetails) throw Error(JSON.stringify(r.exceptionDetails));
  return r.result.value;
}
try {
  await cdp('Page.navigate', {url: `http://127.0.0.1:${appPort}/`});
  let ready = false;
  for (let i = 0; i < 300; i++) {
    ready = await evaluate('typeof S !== "undefined" && !!S && !!META && !busy');
    if (ready) break;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  if (!ready) throw Error('Dashboard initialization timed out');
  const results = await evaluate(`(${async function run() {
    const results = [], painted = {};
    const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
    const check = (condition, message) => { if (!condition) throw Error(message); };
    const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
    // Observe canvas labels without replacing drawing or engine output.
    const text = CanvasRenderingContext2D.prototype.fillText;
    const clear = CanvasRenderingContext2D.prototype.clearRect;
    CanvasRenderingContext2D.prototype.fillText = function(value, ...args) {
      (painted[this.canvas.id] ||= []).push(String(value)); return text.call(this, value, ...args);
    };
    CanvasRenderingContext2D.prototype.clearRect = function(...args) {
      painted[this.canvas.id] = []; return clear.apply(this, args);
    };
    let replies = 0; const original = api;
    api = async (...args) => { const result = await original(...args); replies++; return result; };
    const value = (id, v) => { $(id).value = v; $(id).dispatchEvent(new Event('input', {bubbles: true})); };
    async function waitFor(predicate, label) {
      for (let i = 0; i < 600; i++) { if (predicate()) return; await sleep(20); }
      throw Error('Timeout: ' + label + '; ' + $('msg').textContent);
    }
    async function click(selector, request = true) {
      const n = replies, el = document.querySelector(selector); check(el, 'Missing ' + selector); el.click();
      if (request) await waitFor(() => replies > n && !busy, selector); await sleep(30);
    }
    async function fresh() {
      running = false; ++runId; setFZ('live'); if (travelSkip) travelSkip();
      await call('ghosts', {enabled: false});
      await call('configure', {planet: 'Marte', mode: 'rover', policy: 'hibrido', seed: 42,
        difficulty: 'medium', battery: 100, step_duration: 1, drone: false});
      for (const [id, v] of Object.entries({fMode:'rover', fPolicy:'hibrido', fSeed:42,
        fDiff:'medium', fBattery:100, fDur:1, fSpeed:2, fTool:''})) value(id, v);
      setDestMode(false); await click('#bStep'); check(S.fuzzy, 'Missing initial inference');
    }
    function rendered(F = S.fuzzy) {
      check(F, 'No fuzzy inference');
      check($('fzSub').textContent === F.rules.length + '/' + F.all_rules.length +
        ' reglas activas · v=' + fmt(F.speed, 2), 'E summary differs from engine');
      check($('fzRules').querySelectorAll('.rule').length === F.all_rules.length, 'Incomplete rule list');
      check($('fzRules').querySelectorAll('.rule.act').length === F.rules.length, 'Wrong active-rule count');
      const rows = [...$('fzRules').querySelectorAll('.rule')];
      for (const rule of F.rules) {
        const row = rows.find(el => el.firstElementChild.textContent === 'R' + rule.id);
        check(row?.lastElementChild.textContent === fmt(rule.strength, 2), 'Wrong rule strength R' + rule.id);
      }
      for (const [key, v] of Object.entries(F.inputs)) {
        check((painted.fzSets || []).some(t => t.includes('x=' + fmt(v, 1))), 'Missing input label ' + key);
      }
      check((painted.fzAgg || []).some(t => t.includes('centroide ' + fmt(F.centroid, 3))), 'Wrong centroid label');
    }
    function view() { return [$('fzSub').textContent, $('fzRules').innerHTML, painted.fzSets, painted.fzAgg]; }
    async function test(name, fn) {
      try { await fresh(); await fn(); results.push({name, passed:true}); }
      catch (error) { results.push({name, passed:false, error:String(error)}); }
    }
    await test('Enabled policy before first step must not claim fuzzy is disabled', async () => {
      await call('reset', {});
      check(!$('fzSub').textContent.includes('desactivada') &&
        !$('fzRules').textContent.includes('sin lógica difusa'), 'Hybrid at step 0 says: ' +
        $('fzSub').textContent + ' / ' + $('fzRules').textContent);
    });
    await test('Paso renders inputs, active rules, strengths and centroid', async () => rendered());
    await test('Configuration fields are deferred until Apply', async () => {
      const before = view();
      for (const [id, v] of Object.entries({fMode:'sonda', fPolicy:'sin_rna', fSeed:7,
        fDiff:'high', fBattery:80, fDur:2})) value(id, v);
      check(same(before, view()), 'Form edits changed E before Apply');
      await click('#bApply'); await click('#bStep'); rendered();
    });
    for (const policy of Object.keys(META.policies)) await test('Policy: ' + policy, async () => {
      value('fPolicy', policy); await click('#bApply'); await click('#bStep');
      if (['sin_difuso','control','ag_puro'].includes(policy)) {
        check(S.fuzzy === null && $('fzRules').querySelectorAll('.rule.act').length === 0 &&
          $('fzSub').textContent.includes('desactivada'), 'Disabled policy retained live inference');
      } else rendered();
    });
    for (const planet of META.planets) await test('Planet: ' + planet.name, async () => {
      const before = view(); await click('[data-planet="' + planet.name + '"]');
      if (!planet.rocky) {
        check(same(before, view()), 'Rejected gas/wheels configuration changed E');
        await click('[data-planet="' + planet.name + '"]');
      }
      // the button validates first and configures after: wait for the configure reply, not the first one
      await waitFor(() => S.planet.name === planet.name && !busy, 'planet ' + planet.name);
      if (travelSkip) travelSkip(); check(S.fuzzy === null, 'Planet kept old inference');
      await click('#bStep'); rendered();
    });
    for (const selector of ['#bReset','#bApply','#bGhost']) await test(selector + ' distinguishes pending from disabled', async () => {
      await click(selector); check(S.fuzzy === null, 'Old inference retained');
      check(!$('fzSub').textContent.includes('desactivada') && !$('fzRules').textContent.includes('sin lógica difusa'),
        'Enabled hybrid after reset says: ' + $('fzSub').textContent + ' / ' + $('fzRules').textContent);
    });
    for (const button of document.querySelectorAll('[data-ev]')) await test('Event: ' + button.textContent, async () => {
      const selector = '[data-ev="' + button.dataset.ev + '"]' + (button.dataset.sensor ? '[data-sensor="todos"]' : ':not([data-sensor])');
      const before = view(); await click(selector); check(same(before, view()), 'Event changed E before step');
      await click('#bStep'); rendered();
    });
    for (let speed=0; speed<6; speed++) await test('Automatic cadence and pause: ' + SPEEDS[speed], async () => {
      value('fSpeed', speed); await click('#bRun'); await waitFor(() => S.status.step >= 2, 'automatic step');
      await click('#bRun', false); await waitFor(() => !busy, 'pause');
      const before = view(), step = S.status.step; await sleep(1500);
      check(!running && S.status.step === step && same(before, view()), 'E changed while paused'); rendered();
    });
    await test('Drone toggle keeps the mission and the current E inference', async () => {
      await click('#bStep'); const step = S.status.step, before = view();
      await click('#bDrone'); check(S.status.step === step && same(before, view()), 'Drone toggle restarted the mission or changed E');
      await click('#bDrone');
    });
    await test('Ghost and drone toggles keep E on main mission', async () => {
      for (const selector of ['#bGhost','#bGhost','#bDrone','#bDrone']) {
        await click(selector); await click('#bStep'); rendered();
      }
    });
    await test('Destination and terrain controls refresh E only on next step', async () => {
      const cell = S.rna.cell; await click('#bDest', false); cellAction(...cell);
      await waitFor(() => !busy && S.map.destinations.length === 1, 'destination');
      await click('#bDest', false); await click('#bDestClear');
      for (const kind of ['','obstaculo','barranco','limpiar']) {
        const before = view(); value('fTool', kind); cellAction(...cell);
        await waitFor(() => !busy, 'terrain'); check(same(before, view()), 'Edit recomputed E before step');
      }
      await click('#bStep'); rendered();
    });
    for (const format of ['csv','json','comparison_csv']) await test('Export: ' + format, async () => {
      const before = view(); await click('[data-export="' + format + '"]');
      check(same(before, view()), 'Export changed E');
    });
    await test('Manual mode survives C steps and Live restores mission values', async () => {
      await click('[data-fz="test"]'); await waitFor(() => fzTest !== null, 'manual inference');
      const before = view(); await click('#bStep'); check(same(before, view()), 'C overwrote manual E');
      await click('[data-fz="live"]', false); rendered();
    });
    await test('Chart clicks evaluate manual inputs without changing the mission', async () => {
      const canvas = $('fzSets'), rect = canvas.getBoundingClientRect();
      const mission = JSON.stringify(S);
      const targets = {distance:6,battery:30,slope:20,temperature:20};
      for (const [row, t] of [[0,.3],[1,.3],[2,20/45],[3,.5]]) {
        const n = replies;
        canvas.dispatchEvent(new MouseEvent('click', {bubbles:true,
          clientX:rect.left+8+(rect.width-16)*t, clientY:rect.top+(row+.5)*rect.height/4}));
        await waitFor(() => replies>n, 'chart input'); await sleep(30);
      }
      // Pointer coordinates are pixel-quantized; allow one pixel plus UI rounding.
      for (const [key, target] of Object.entries(targets)) {
        const domain = META.fuzzy_sets[key].x;
        const tolerance = (domain.at(-1)-domain[0])/(rect.width-16)+.1;
        check(Math.abs(fzInputs[key]-target) <= tolerance,
          'Chart input mismatch: ' + key + '=' + fzInputs[key] + ', target=' + target + ', tolerance=' + tolerance);
      }
      check(JSON.stringify(S) === mission, 'Manual chart interaction changed the mission');
      rendered(fzTest);
    });
    running=false; ++runId; return results;
  }})()`);
  process.stdout.write(JSON.stringify(results));
} finally { ws.close(); }
