'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {webcrypto} = require('node:crypto');
const core = require('../static/sync-core.js');
const recovery = require('../static/sync-preflight.js');
const {createEngine} = require('../static/sync-engine.js');

class Storage {
  constructor() { this.data = new Map(); this.fail = null; }
  get length() { return this.data.size; }
  key(i) { return [...this.data.keys()][i] ?? null; }
  getItem(k) { return this.data.get(k) ?? null; }
  setItem(k,v) { if (this.fail && this.fail(k,v)) throw new Error('QuotaExceededError'); this.data.set(k,String(v)); }
  removeItem(k) { this.data.delete(k); }
}
function remoteStore() {
  const rows = new Map(), requests = [];
  let version = 0;
  const api = {rows, requests, beforePut: null, afterPut: null};
  api.fetch = async (_,options) => {
    const token=options.headers.Authorization;
    requests.push({method:options.method, headers:{...options.headers}, body:options.body});
    if(options.method==='GET') {
      const row=rows.get(token);
      return Response.json(row || {code:'not_found'}, {status:row?200:404});
    }
    if(api.beforePut) await api.beforePut(token,options);
    const existing=rows.get(token), match=options.headers['X-Sync-If-Match'];
    if(existing ? match!==existing.revision : options.headers['X-Sync-If-None-Match']!=='*') return Response.json({code:'conflict'},{status:409});
    const row={envelope:JSON.parse(options.body),revision:'"revision-'+(++version)+'"'};
    rows.set(token,row);
    if(api.afterPut) await api.afterPut(token,options);
    return Response.json({revision:row.revision});
  };
  return api;
}
function device(api,options={}) {
  const storage=new Storage();
  storage.setItem('pf_portfolios',JSON.stringify([{id:'default',name:'real',type:'Standard',openingCash:0,currency:'USD',ledgerVersion:3}]));
  storage.setItem('pf_transactions_default','[]');
  storage.setItem('watchlist','[]');
  const engine=createEngine({storage,core,recovery,crypto:webcrypto,fetch:api.fetch,locks:{request:async(...args)=>args.at(-1)({})},
    guardTabs:false,autoStart:false,backup:async()=>{},onApplied:()=>{},...options});
  return {storage,engine};
}
async function pair(options={}) {
  const api=remoteStore(), a=device(api), b=device(api,options);
  a.storage.setItem('note_AAPL','original');
  await a.engine.create();
  await b.engine.connect(a.engine.revealCode());
  assert.equal(b.engine.getState().status,'idle');
  return {api,a,b};
}

test('uses authenticated encryption and excludes device secrets from the cloud',async()=>{
  const api=remoteStore(),a=device(api);
  a.storage.setItem('note_AAPL','private investment note');
  a.storage.setItem('mi_api_key','private-provider-key');
  assert.equal((await a.engine.create()).status,'idle');
  const code=a.engine.revealCode(),wire=JSON.stringify(api.requests);
  assert.match(code,/^MI1-[A-Za-z0-9_-]{43}$/);
  assert(!wire.includes(code)); assert(!wire.includes('private investment note')); assert(!wire.includes('private-provider-key'));
  assert.deepEqual(Object.keys([...api.rows.values()][0].envelope).sort(),['ciphertext','iv','version']);
  const b=device(api);await b.engine.connect(code);
  assert.equal(b.storage.getItem('note_AAPL'),'private investment note');
  assert.equal(b.storage.getItem('mi_api_key'),null);
});
test('wrong key or tampered ciphertext cannot change local data or link a device',async()=>{
  const api=remoteStore(),a=device(api),b=device(api);
  await a.engine.create();b.storage.setItem('note_AAPL','keep me');
  assert.equal((await b.engine.connect('MI1-'+Buffer.alloc(32,7).toString('base64url'))).status,'error');
  assert.equal(b.engine.revealCode(),null);
  const row=[...api.rows.values()][0];
  const bytes=Buffer.from(row.envelope.ciphertext,'base64url');bytes[0]^=1;row.envelope.ciphertext=bytes.toString('base64url');
  assert.equal((await b.engine.connect(a.engine.revealCode())).status,'error');
  assert.equal(b.storage.getItem('note_AAPL'),'keep me');assert.equal(b.engine.revealCode(),null);
});
test('an edit while upload is pending remains dirty and is uploaded next time',async()=>{
  const {api,a,b}=await pair();
  a.storage.setItem('note_AAPL','first edit');
  api.afterPut=async()=>{api.afterPut=null;a.storage.setItem('note_AAPL','second edit');};
  assert.equal((await a.engine.sync()).pending,true);
  assert.equal(JSON.parse(a.storage.getItem('marketintel_sync_state')).base.notes.note_AAPL,'first edit');
  await a.engine.sync();await b.engine.sync();
  assert.equal(b.storage.getItem('note_AAPL'),'second edit');
});
test('failed backup leaves local data and acknowledged baseline intact',async()=>{
  let fail=false;
  const {a,b}=await pair({backup:async()=>{if(fail)throw new Error('Backup failed');}});
  a.storage.setItem('note_AAPL','remote edit');await a.engine.sync();
  const prior=b.storage.getItem('marketintel_sync_state');fail=true;
  assert.equal((await b.engine.sync()).status,'error');
  assert.equal(b.storage.getItem('note_AAPL'),'original');assert.equal(b.storage.getItem('marketintel_sync_state'),prior);
});
test('storage failure rolls back changes and does not acknowledge the remote snapshot',async()=>{
  const {a,b}=await pair();
  a.storage.setItem('note_AAPL','remote edit');await a.engine.sync();
  const prior=b.storage.getItem('marketintel_sync_state');
  let failed=false;b.storage.fail=(key,value)=>{if(!failed&&key==='note_AAPL'&&value==='remote edit'){failed=true;return true;}return false;};
  assert.equal((await b.engine.sync()).status,'error');
  assert.equal(b.storage.getItem('note_AAPL'),'original');assert.equal(b.storage.getItem('marketintel_sync_state'),prior);
  assert.equal(b.storage.getItem('marketintel_sync_journal'),null);
  await b.engine.sync();assert.equal(b.storage.getItem('note_AAPL'),'remote edit');
});
test('cannot apply a snapshot when a recovery journal cannot be saved',async()=>{
  const {a,b}=await pair();a.storage.setItem('note_AAPL','remote edit');await a.engine.sync();
  b.storage.fail=key=>key==='marketintel_sync_journal';
  assert.equal((await b.engine.sync()).status,'error');assert.equal(b.storage.getItem('note_AAPL'),'original');
});
test('CAS conflict fetches and merges the latest version before retrying',async()=>{
  const {api,a,b}=await pair();
  a.storage.setItem('note_MSFT','from A');b.storage.setItem('note_NVDA','from B');
  api.beforePut=async()=>{api.beforePut=null;await b.engine.sync();};
  assert.equal((await a.engine.sync()).status,'idle');await b.engine.sync();
  assert.equal(a.storage.getItem('note_NVDA'),'from B');assert.equal(b.storage.getItem('note_MSFT'),'from A');
  assert.equal(api.requests.filter(r=>r.method==='PUT').length,4);
});
test('conflict decisions are invalidated when either version changes during review',async()=>{
  const {a,b}=await pair();a.storage.setItem('note_AAPL','A');b.storage.setItem('note_AAPL','B');
  await a.engine.sync();assert.equal((await b.engine.sync()).status,'conflict');
  a.storage.setItem('note_AAPL','A newer');await a.engine.sync();
  assert.equal((await b.engine.sync({'note:note_AAPL':'local'})).status,'conflict');
  assert.equal(b.storage.getItem('note_AAPL'),'B');
  await b.engine.sync({'note:note_AAPL':'both'});
  assert.match(b.storage.getItem('note_AAPL'),/A newer/);assert.match(b.storage.getItem('note_AAPL'),/B/);
});
test('recovery restores an interrupted apply including derived and sync metadata',()=>{
  const s=new Storage();s.setItem('note_AAPL','partially applied');s.setItem('pf_positions_new','[{"ticker":"AAPL"}]');
  s.setItem('marketintel_sync_journal',JSON.stringify({version:1,entries:[['note_AAPL','original'],['pf_positions_new',null],['marketintel_sync_state','original metadata']]}));
  assert.equal(recovery.recover(s),true);assert.equal(s.getItem('note_AAPL'),'original');
  assert.equal(s.getItem('pf_positions_new'),null);assert.equal(s.getItem('marketintel_sync_state'),'original metadata');
  assert.equal(recovery.recover(s),false);
});
test('disconnect retains local records and explicit linking can reconnect',async()=>{
  const {a,b}=await pair();const key=b.engine.revealCode();await b.engine.disconnect();
  assert.equal(b.engine.getState().connected,false);assert.equal(b.engine.revealCode(),null);
  assert.equal(b.storage.getItem('note_AAPL'),'original');await b.engine.connect(key);
  assert.equal(b.engine.getState().connected,true);assert.equal(a.engine.getState().connected,true);
});
test('saved local changes upload automatically after the observation debounce',async()=>{
  const api=remoteStore(),a=device(api,{autoStart:true});
  try {
    await a.engine.create();a.storage.setItem('note_AAPL','automatic change');
    const deadline=Date.now()+10000;
    while(api.requests.filter(r=>r.method==='PUT').length<2&&Date.now()<deadline) await new Promise(resolve=>setTimeout(resolve,100));
    assert.equal(api.requests.filter(r=>r.method==='PUT').length,2);
    const b=device(api);await b.engine.connect(a.engine.revealCode());
    assert.equal(b.storage.getItem('note_AAPL'),'automatic change');
  } finally {a.engine.dispose();}
});
