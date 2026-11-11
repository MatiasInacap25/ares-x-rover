// Real C controls -> Python mission/planner -> DOM and canvas output in F.
const [port, appPort] = process.argv.slice(2);
const tabs = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const ws = new WebSocket(tabs.find(t => t.type === 'page').webSocketDebuggerUrl);
await new Promise((resolve, reject) => { ws.onopen=resolve; ws.onerror=reject; });
let serial=0; const pending=new Map();
ws.onmessage=event=>{
  const m=JSON.parse(event.data), p=pending.get(m.id);
  if(p){ pending.delete(m.id); m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result); }
};
function cdp(method, params={}){
  return new Promise((resolve,reject)=>{const id=++serial;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
}
async function evaluate(expression){
  const r=await cdp('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});
  if(r.exceptionDetails) throw Error(JSON.stringify(r.exceptionDetails)); return r.result.value;
}
try{
  await cdp('Page.navigate',{url:`http://127.0.0.1:${appPort}/`});
  let ready=false;
  for(let i=0;i<300;i++){
    ready=await evaluate('typeof S!=="undefined"&&!!S&&!!META&&!busy'); if(ready)break;
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  if(!ready)throw Error('Dashboard initialization timed out');
  const results=await evaluate(`(${async function run(){
    const results=[], lines={}; let inflight=0, replies=0;
    const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
    const check=(condition,message)=>{if(!condition)throw Error(message);};
    const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
    const original=api;
    api=async(...args)=>{inflight++;try{return await original(...args);}finally{inflight--;replies++;}};
    const clear=CanvasRenderingContext2D.prototype.clearRect, line=CanvasRenderingContext2D.prototype.lineTo;
    CanvasRenderingContext2D.prototype.clearRect=function(...args){lines[this.canvas.id]=0;return clear.apply(this,args);};
    CanvasRenderingContext2D.prototype.lineTo=function(...args){lines[this.canvas.id]=(lines[this.canvas.id]||0)+1;return line.apply(this,args);};
    async function waitFor(predicate,label){
      for(let i=0;i<1000;i++){if(predicate())return;await sleep(20);}throw Error('Timeout: '+label+' / '+$('msg').textContent);
    }
    async function settled(){await waitFor(()=>!busy&&!inflight,'API completion');await sleep(60);await waitFor(()=>!busy&&!inflight,'render completion');}
    async function click(selector,request=true){
      const n=replies,el=document.querySelector(selector);check(el,'Missing '+selector);el.click();
      if(request)await waitFor(()=>replies>n,selector);await settled();
    }
    const value=(id,v)=>{$(id).value=v;$(id).dispatchEvent(new Event('input',{bubbles:true}));};
    async function fresh(){
      running=false;++runId;gaRunSel=null;if(travelSkip)travelSkip();
      await call('ghosts',{enabled:false});await settled();
      await call('configure',{planet:'Marte',mode:'rover',policy:'hibrido',seed:42,
        difficulty:'medium',battery:100,step_duration:1,drone:false});await settled();
      for(const [id,v]of Object.entries({fMode:'rover',fPolicy:'hibrido',fSeed:42,
        fDiff:'medium',fBattery:100,fDur:1,fSpeed:2,fTool:''}))value(id,v);
      setDestMode(false);
    }
    function view(){return [$('gaSub').textContent,$('gaInfo').textContent,$('gaGenLbl').textContent,
      $('gaOps').textContent,$('gaChrom').innerHTML,$('gaCand').innerHTML,$('fRun').innerHTML];}
    async function rendered(G=S.ga,run=gaRunSel){
      const runs=S.ga_runs||[];
      check($('fRun').options.length===(runs.length||1),'Execution selector differs from engine');
      check($('gaSub').textContent===(G.mode==='ag'?G.candidates.length+' rutas candidatas':G.mode),'Planner mode/candidate count differs');
      const rows=[...$('gaCand').querySelectorAll('tr')].slice(1);
      check(rows.length===G.candidates.length,'Candidate table is incomplete');
      G.candidates.forEach((c,i)=>{
        const cells=rows[i].querySelectorAll('td');
        check(cells[0].textContent===String(c.index)&&cells[1].textContent===fmt(c.fitness,3),'Candidate identity/fitness differs');
        ['science','distance','energy','predicted_risk'].forEach((k,j)=>
          check(cells[j+2].textContent===fmt(c.components[k],2),'Candidate component differs: '+k));
        if(c.index===G.chosen)check(cells[6].textContent==='ELEGIDA','Chosen route is not identified');
      });
      if(runs.length){
        const a={generation:+$('fGen').value,...(run===null?{}:{run})},o=await api('ga_generation',a);
        check(!o.error,'Generation inspection failed: '+o.error);
        check($('gaGenLbl').textContent===o.generation+'/'+(o.total-1),'Generation label differs from engine');
        check($('gaOps').textContent.includes('mejor '+fmt(o.best,3)),'Operator/best-fitness summary differs');
        check($('gaChrom').querySelectorAll('tr').length-1===Math.min(5,o.rows.length),'Chromosome table incomplete');
      }
    }
    async function test(name,fn){
      try{await fresh();await fn();results.push({name,passed:true});}
      catch(error){results.push({name,passed:false,error:String(error)});}
    }
    await test('Initial plan is displayed before Paso',async()=>{check(S.status.step===0,'Not at step zero');await rendered();check(lines.gaMap>0,'Initial routes missing');});
    await test('All configuration fields are deferred until Apply',async()=>{
      const before=view();for(const[id,v]of Object.entries({fMode:'sonda',fPolicy:'sin_rna',fSeed:7,fDiff:'high',fBattery:80,fDur:2}))value(id,v);
      check(same(before,view()),'Form edit changed F before Apply');await click('#bApply');await rendered();
    });
    for(const policy of Object.keys(META.policies))await test('Policy selector: '+policy,async()=>{
      value('fPolicy',policy);await click('#bApply');await rendered();
    });
    for(const planet of META.planets)await test('Planet: '+planet.name,async()=>{
      const before=view();await click('[data-planet="'+planet.name+'"]');
      if(!planet.rocky){check(same(before,view()),'Rejected wheels/gas selection changed F');await click('[data-planet="'+planet.name+'"]');}
      if(travelSkip)travelSkip();check(S.planet.name===planet.name,'Wrong planet');await rendered();
    });
    for(const selector of ['#bReset','#bApply','#bGhost'])await test(selector+' prepares a fresh initial execution',async()=>{
      await click('[data-ev="tormenta_polvo"]');check(S.ga_runs.length>1,'Replan prerequisite not reached');
      await click(selector);check(S.status.step===0&&S.ga_runs.length===1,'Restart retained old execution history');await rendered();
    });
    await test('Drone toggles preserve current plan and historical executions in place',async()=>{
      await click('#bStep');
      for(const enabled of [true,false]){
        const before={ga:S.ga,runs:S.ga_runs,path:S.map.path,step:S.status.step};
        await click('#bDrone');
        check(S.config.drone===enabled&&S.status.step===before.step&&same(S.map.path,before.path),
          'Drone toggle restarted or moved the mission');
        check(same(S.ga,before.ga)&&same(S.ga_runs,before.runs),'Drone toggle replaced planning history');
        await rendered();await click('#bStep');await rendered();
      }
    });
    for(const button of document.querySelectorAll('[data-ev]'))await test('Event: '+button.textContent,async()=>{
      const selector='[data-ev="'+button.dataset.ev+'"]'+(button.dataset.sensor?'[data-sensor="todos"]':':not([data-sensor])');
      await click(selector);await rendered();await click('#bStep');await rendered();
    });
    for(let speed=0;speed<6;speed++)await test('Start/pause cadence: '+SPEEDS[speed],async()=>{
      value('fSpeed',speed);await click('#bRun');await waitFor(()=>S.status.step>=1,'automatic step');
      await click('#bRun',false);await settled();const before=view(),step=S.status.step;await sleep(1500);
      check(!running&&S.status.step===step&&same(before,view()),'Paused planner changed');await rendered();
    });
    await test('Paso updates F and stops automatic mode',async()=>{await click('#bStep');check(!running&&S.status.step===1,'Paso did not advance once');await rendered();});
    await test('Destination and terrain controls preserve planner inspection',async()=>{
      const cell=S.map.route[2];await click('#bDest',false);cellAction(...cell);await settled();
      check(S.map.destinations.length===1,'Destination not added');await rendered();await click('#bDest',false);await click('#bDestClear');
      for(const kind of ['','obstaculo','barranco','limpiar']){value('fTool',kind);cellAction(...cell);await settled();await rendered();}
      await click('#bStep');await rendered();
    });
    for(const format of ['csv','json','comparison_csv'])await test('Export: '+format,async()=>{
      const before=view();await click('[data-export="'+format+'"]');check(same(before,view()),'Export changed F');
    });
    await test('Generation slider renders requested public generation',async()=>{
      for(const gen of [0,5,+$('fGen').max]){value('fGen',gen);await sleep(100);await settled();await rendered();}
    });
    for(const policy of ['sin_ag','control'])await test('No-GA policy clears previous generation label: '+policy,async()=>{
      const old=$('gaGenLbl').textContent;value('fPolicy',policy);await click('#bApply');
      check(S.ga_runs.length===0&&$('gaChrom').textContent===''&&$('gaOps').textContent==='','Old generation details retained');
      const parts=$('gaGenLbl').textContent.split('/');
      check(!(parts.length===2&&parts.every(v=>v!==''&&!Number.isNaN(Number(v)))),
        'Generation label '+$('gaGenLbl').textContent+' remains with no GA runs (previous '+old+')');
    });
    await test('Historical execution selection retains candidate routes on mini-map',async()=>{
      check(lines.gaMap>0&&S.map.candidates.some(r=>r.length>1),'Initial drawable-route prerequisite missing');
      await click('[data-ev="tormenta_polvo"]');check(S.ga_runs.length>=2,'No historical execution available');
      $('fRun').value='0';$('fRun').dispatchEvent(new Event('change',{bubbles:true}));await settled();
      const selected=await api('ga_run',{run:0});await rendered(selected.ga,0);
      check(lines.gaMap>0,'Historical candidates exist, but gaMap drew zero route line segments');
    });
    running=false;++runId;return results;
  }})()`);
  process.stdout.write(JSON.stringify(results));
}finally{ws.close();}
