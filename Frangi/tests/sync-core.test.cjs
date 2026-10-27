'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const core = require('../sync-core.js');
function storage(data) {
  const items = new Map(Object.entries(data));
  return {get length(){return items.size},key:i=>[...items.keys()][i],getItem:k=>items.get(k)??null};
}
const date='2026-10-27';
const T=(id,result)=>({id,result});
const S=values=>({version:1,days:values.length?{[date]:values}:{}});
test('legacy TP/SL and repeated results become distinct trades',()=>{
  const captured=core.capture(storage({['tpsl_calendar_trade_'+date]:'["TP","TP","SL"]'}));
  assert.deepEqual(captured.days[date],[T('legacy_'+date+'_0','TP'),T('legacy_'+date+'_1','TP'),T('legacy_'+date+'_2','SL')]);
});
test('independent additions and a deletion merge without losing results',()=>{
  const base=S([T('one','TP')]);
  const left=S([T('one','TP'),T('left','SL')]);
  const right=S([T('one','TP'),T('right','TP')]);
  assert.deepEqual(core.merge(base,left,right).snapshot.days[date], [T('one','TP'),T('left','SL'),T('right','TP')]);
  assert.deepEqual(core.merge(base,S([]),right).snapshot.days[date],[T('right','TP')]);
});
test('same-trade edits require an explicit decision and both keeps two trades',()=>{
  const base=S([T('one','TP')]);
  const left=S([T('one','SL')]);
  const right=S([]);
  const first=core.merge(base,left,right);
  assert.equal(first.conflicts.length,1);
  assert.deepEqual(core.merge(base,left,right,{[first.conflicts[0].id]:'both'}).snapshot.days[date],[T('one','SL')]);
  const noBase=S([]),firstA=S([T('same','TP')]),firstB=S([T('same','SL')]);
  const clash=core.merge(noBase,firstA,firstB);
  assert.equal(clash.conflicts.length,1);
  const both=core.merge(noBase,firstA,firstB,{[clash.conflicts[0].id]:'both'}).snapshot.days[date];
  assert.deepEqual(both.map(item=>item.result).sort(),['SL','TP']);
});
test('malformed remote data is rejected before an apply plan is built',()=>{
  assert.throws(()=>core.validate({version:1,days:{[date]:[{id:'x',result:'WIN'}]}}));
  const local=storage({['tpsl_calendar_trade_'+date]:JSON.stringify([T('x','TP')]),'api_key':'private'});
  const plan=core.planApply(local,S([]));
  assert.deepEqual(plan.remove,['tpsl_calendar_trade_'+date]);
  assert.equal('api_key' in plan.set,false);
});
