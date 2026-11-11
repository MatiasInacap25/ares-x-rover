// Isolated browser and real engine; native CDP mouse clicks exercise the 2D map.
const [port, appPort] = process.argv.slice(2);
const tabs = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const ws = new WebSocket(tabs.find(t => t.type === 'page').webSocketDebuggerUrl);
await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
let serial = 0;
const pending = new Map(), exceptions = [];
function cdp(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++serial; pending.set(id, {resolve, reject});
    ws.send(JSON.stringify({id, method, params}));
  });
}
ws.onmessage = async event => {
  const m = JSON.parse(event.data), request = pending.get(m.id);
  if (request) {
    pending.delete(m.id);
    m.error ? request.reject(Error(JSON.stringify(m.error))) : request.resolve(m.result);
  }
  if (m.method === 'Runtime.exceptionThrown') exceptions.push(m.params.exceptionDetails);
  if (m.method === 'Runtime.bindingCalled' && m.params.name === '__telemetryPointer') {
    const p = JSON.parse(m.params.payload); let error = '';
    try {
      if (!(p.x >= 0 && p.x < 1440 && p.y >= 0 && p.y < 1100)) throw Error('Pointer outside test viewport');
      await cdp('Input.dispatchMouseEvent', {type:'mouseMoved', x:p.x, y:p.y});
      await cdp('Input.dispatchMouseEvent', {type:'mousePressed', x:p.x, y:p.y, button:'left', clickCount:1});
      await cdp('Input.dispatchMouseEvent', {type:'mouseReleased', x:p.x, y:p.y, button:'left', clickCount:1});
    } catch (e) { error = String(e); }
    await cdp('Runtime.evaluate', {expression:`window.__pointerAck=${Number(p.id)};window.__pointerError=${JSON.stringify(error)}`});
  }
};
async function evaluate(expression) {
  const r = await cdp('Runtime.evaluate', {expression, awaitPromise:true, returnByValue:true});
  if (r.exceptionDetails) throw Error(JSON.stringify(r.exceptionDetails));
  return r.result.value;
}
try {
  await cdp('Runtime.enable');
  await cdp('Runtime.addBinding', {name:'__telemetryPointer'});
  await cdp('Emulation.setDeviceMetricsOverride', {width:1440, height:1100, deviceScaleFactor:1, mobile:false});
  await cdp('Browser.setDownloadBehavior', {behavior:'deny'});
  await cdp('Page.navigate', {url:`http://127.0.0.1:${appPort}/`});
  let ready = false;
  for (let i = 0; i < 300; i++) {
    ready = await evaluate('typeof S!=="undefined"&&!!S&&!!META&&!busy');
    if (ready) break;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  if (!ready) throw Error('Dashboard initialization timed out');
  const results = await evaluate(`(${async function run() {
    const results = [], sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
    let inflight = 0, replies = 0, pointerId = 0;
    const check = (condition, message) => { if (!condition) throw Error(message); };
    const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
    const fixed = (value, digits) => value === null || value === undefined ? '—' : Number(value).toFixed(digits);
    const original = api;
    api = async (...args) => { inflight++; try { return await original(...args); } finally { inflight--; replies++; } };
    async function waitFor(predicate, label) {
      for (let i = 0; i < 1000; i++) { if (predicate()) return; await sleep(20); }
      throw Error('Timeout: ' + label + ' / ' + $('msg').textContent);
    }
    async function settled() { await waitFor(() => !busy && !inflight, 'engine'); await sleep(60); }
    async function click(selector, request = true) {
      const n = replies, el = document.querySelector(selector); check(el, 'Missing ' + selector); el.click();
      if (request) await waitFor(() => replies > n, selector); await settled();
    }
    const value = (id, v) => { $(id).value = v; $(id).dispatchEvent(new Event('input', {bubbles:true})); };
    function rows() {
      return Object.fromEntries([...$('tele').querySelectorAll('.tl')].map(el =>
        [el.querySelector('.n').textContent, {value:el.querySelector('.v').textContent,
          unit:el.querySelector('.u').textContent, chip:el.querySelector('.chip').textContent}]));
    }
    function view() { return [$('pName').textContent, $('pInfo').textContent, $('tSub').textContent, rows()]; }
    function rendered() {
      const st = S.status, t = S.telemetry, p = S.planet, nav = t.nav_valid || {}, actual = rows();
      check(Object.keys(actual).length === 23, 'Expected 23 telemetry indicators');
      check($('pName').textContent === p.name, 'Planet name mismatch');
      check($('pInfo').textContent.includes(fixed(p.gravity,2)) &&
        $('pInfo').textContent.includes(p.mode === 'rover' ? 'Rover de superficie' : 'Sonda atmosférica virtual'), 'Reference/mode mismatch');
      const pressure = t.pressure == null ? '—' : t.pressure >= 100000 ?
        fixed(t.pressure / 100000,1) + ' bar' : String(Math.round(t.pressure));
      const expected = {
        'Batería':fixed(st.battery,1)+' %', 'Integridad':fixed(st.health,0)+' %',
        'Temp. exterior':fixed(t.temperature_external,1), 'Temp. componentes':fixed(st.temperature_internal,1),
        'O₂ exterior (ambiental)':fixed(t.oxygen_ambient,2), 'O₂ almacenado':fixed(t.oxygen_stored,0),
        'Presión':pressure, 'Gravedad':fixed(p.gravity,2), 'Radiación (índice)':fixed(t.radiation,2),
        'Pendiente':fixed(t.slope,1), 'Proximidad':nav.proximidad === false ? 'NaN' : fixed(t.distance,2),
        'LIDAR / borde':nav.lidar === false ? 'NaN' : fixed(t.elevation_delta,1),
        'Visibilidad':fixed(st.visibility,2), 'Potencia solar':fixed(t.solar_power,1),
        'Enlace':st.link ? 'OK' : fixed(st.link_latency,0)+' s · '+st.queued_orders,
        'Vibración':fixed(st.vibration,1), 'Viento':fixed(st.wind,0),
        'Eventos':st.events_total+' · '+st.anomalies+' · '+st.contacts,
        'Pasos perdidos':st.wait_steps+' · '+st.degraded_steps, 'Ciencia':Math.round(st.science*100)+' %',
        'Dron explorador':S.drone ? String(S.metrics.drone_discoveries) : '—',
        'Destinos':S.map.destination ? st.destinations_left+' · '+(st.destination_distance ?? '—') : '—',
        'Instrumentación':st.instruments+'/'+st.instruments_total,
      };
      for (const [label, v] of Object.entries(expected)) check(actual[label]?.value === v,
        label + ': DOM=' + actual[label]?.value + ', engine=' + v);
      check(actual['Batería'].chip === (st.battery < 15 ? 'CRÍTICO' : st.battery < 35 ? 'ALERTA' : 'NOMINAL'), 'Battery status mismatch');
      check(actual['Dron explorador'].chip === (S.drone ? S.drone.flying ? 'VOLANDO' : 'EN TIERRA' : 'APAGADO'), 'Drone status mismatch');
      check($('tSub').textContent.includes(st.daylight ? 'día' : 'noche'), 'Day/night mismatch');
      for (const [key, label] of [['storm','tormenta'],['heat','ola de calor'],['wind','viento']])
        check($('tSub').textContent.includes(label) === !!st[key], 'Environment flag mismatch: ' + key);
    }
    async function fresh() {
      running = false; ++runId; if (travelSkip) travelSkip();
      await call('ghosts', {enabled:false}); await settled();
      await call('configure', {planet:'Marte', mode:'rover', policy:'hibrido', seed:42,
        difficulty:'medium', battery:100, step_duration:1, drone:false}); await settled();
      for (const [id,v] of Object.entries({fMode:'rover', fPolicy:'hibrido', fSeed:42,
        fDiff:'medium', fBattery:100, fDur:1, fSpeed:2, fTool:''})) value(id,v);
      setDestMode(false); await click('#bStep');
    }
    async function test(name, fn) {
      try { await fresh(); await fn(); results.push({name,passed:true}); }
      catch (error) { results.push({name,passed:false,error:String(error)}); }
    }
    async function mapClick(cell) {
      await click('[data-view="2d"]', false); $('map2d').scrollIntoView({block:'center'}); await sleep(100);
      const rect = $('map2d').getBoundingClientRect(), id = ++pointerId;
      window.__telemetryPointer(JSON.stringify({id,x:rect.left+geom2d.ox+(cell[1]+.5)*geom2d.cs,
        y:rect.top+geom2d.oy+(cell[0]+.5)*geom2d.cs}));
      await waitFor(() => window.__pointerAck === id, 'native map click');
      check(!window.__pointerError, window.__pointerError); await settled();
    }
    await test('Paso renders all 23 indicators from the engine', async () => rendered());
    await test('Configuration edits stay deferred until Apply', async () => {
      const before = view();
      for (const [id,v] of Object.entries({fMode:'sonda',fPolicy:'sin_rna',fSeed:7,fDiff:'high',fBattery:80,fDur:2})) value(id,v);
      check(same(before,view()), 'Form edits changed A before Apply'); await click('#bApply'); rendered();
      await click('#bStep'); rendered();
    });
    for (const planet of META.planets) await test('Planet: '+planet.name, async () => {
      const before = view(); await click('[data-planet="'+planet.name+'"]');
      if (!planet.rocky) { check(same(before,view()), 'Rejected wheels/gas selection changed A'); await click('[data-planet="'+planet.name+'"]'); }
      if (travelSkip) travelSkip(); rendered(); await click('#bStep'); rendered();
    });
    for (const policy of Object.keys(META.policies)) await test('Policy: '+policy, async () => {
      value('fPolicy',policy); await click('#bApply'); await click('#bStep'); rendered();
      check(rows()['Temp. exterior'].value !== '—', 'Policy disabled physical sensor readings');
    });
    for (const battery of [0,10,30,50,100]) await test('Initial battery and status: '+battery, async () => {
      value('fBattery',battery); await click('#bApply'); check(S.status.battery===battery,'Battery not applied'); rendered();
    });
    for (const selector of ['#bReset','#bApply','#bGhost']) await test(selector+' resets main telemetry and counters', async () => {
      await click('[data-ev="corrosion"]'); await click(selector); check(S.status.step===0&&S.status.events_total===0,'Counters not reset'); rendered();
      check(rows()['Temp. exterior'].value==='—','Previous measured temperature retained');
    });
    await test('Drone toggles update A without resetting mission', async () => {
      for (const enabled of [true,false]) {
        const step=S.status.step; await click('#bDrone'); check(S.status.step===step&&S.config.drone===enabled,'Drone restarted mission');
        rendered(); await click('#bStep'); rendered();
      }
    });
    for (const button of document.querySelectorAll('[data-ev]')) await test('Event: '+button.textContent, async () => {
      const selector='[data-ev="'+button.dataset.ev+'"]'+(button.dataset.sensor?'[data-sensor="todos"]':':not([data-sensor])');
      const old=S.telemetry; await click(selector); check(same(old,S.telemetry),'Event resampled sensors before a step'); rendered();
      await click('#bStep'); rendered();
      if (button.dataset.ev==='falla_sensor') check(rows()['Proximidad'].chip==='FALLA','Failed proximity shown healthy');
      if (button.dataset.sensor==='todos') check(rows()['LIDAR / borde'].chip==='FALLA','Failed LIDAR shown healthy');
    });
    for (let speed=0;speed<6;speed++) await test('Start/pause at cadence '+SPEEDS[speed], async () => {
      value('fSpeed',speed); await click('#bRun'); await waitFor(()=>S.status.step>=2,'automatic step');
      await click('#bRun',false); await settled(); const before=view(),step=S.status.step; await sleep(1500);
      check(!running&&S.status.step===step&&same(before,view()),'Telemetry changed while paused'); rendered();
    });
    await test('Native 2D destination clicks update A and clear correctly', async () => {
      const cell=S.map.route[2]; await click('#bDest',false); await mapClick(cell);
      check(S.map.destinations.some(p=>same(p,cell)),'Native click did not select intended destination'); rendered();
      check(rows()['Destinos'].chip==='EN RUTA','Destination status not updated');
      await click('#bDest',false); await click('#bDestClear'); rendered();
      check(rows()['Destinos'].chip==='SIN FIJAR','Destination clear not reflected');
    });
    await test('Native terrain clicks preserve last reading until next step', async () => {
      const cell=S.map.route[2];
      for (const kind of ['','obstaculo','barranco','limpiar']) {
        value('fTool',kind); const before=S.telemetry; await mapClick(cell);
        check(same(before,S.telemetry),'Terrain edit resampled telemetry before a step'); rendered();
        if (kind==='obstaculo') check(S.map.hidden_obstacles.some(p=>same(p,cell)),'Obstacle click missed cell');
        if (kind==='barranco') check(S.map.hidden_cliffs.some(p=>same(p,cell)),'Cliff click missed cell');
      }
      await click('#bStep'); rendered();
    });
    for (const format of ['csv','json','comparison_csv']) await test('Export leaves A unchanged: '+format, async () => {
      const before=view(); await click('[data-export="'+format+'"]'); check(same(before,view()),'Export altered telemetry');
    });
    for (const planet of ['Tierra','Venus']) await test('Pressure value and unit agree: '+planet, async () => {
      await click('[data-planet="'+planet+'"]'); if(travelSkip)travelSkip(); await click('#bStep');
      const p=rows()['Presión']; check(!(p.value.includes('bar')&&p.unit.includes('Pa')),
        'Contradictory pressure display: value='+p.value+', unit='+p.unit);
    });
    for (const selector of ['#bReset','#bApply','#bGhost']) await test('Unavailable sensor status after '+selector, async () => {
      await click(selector); const r=rows(), unavailable=['Radiación (índice)','Pendiente','Proximidad','LIDAR / borde','Potencia solar','O₂ almacenado'];
      const misleading=unavailable.filter(label=>r[label].value==='—'&&['NOMINAL','ALERTA','CRÍTICO','FALLA'].includes(r[label].chip));
      check(!misleading.length,'No readings, but health statuses are shown: '+JSON.stringify(misleading.map(label=>({label,...r[label]}))));
    });
    running=false; ++runId; return results;
  }})()`);
  process.stdout.write(JSON.stringify(results));
  process.stderr.write(JSON.stringify({uncaught_browser_exceptions:exceptions}));
} finally { ws.close(); }
