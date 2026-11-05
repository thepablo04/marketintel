'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const macro=require('../static/macro-context.js');
const stamp='2026-11-05T13:30:00Z';
function item(value,prior,unit='percent_yoy',date='2026-10-01',extra={}){
 return {date,display_value:value,display_unit:unit,status:'ok',context_usable:true,frequency:'monthly',
  fetched_at:stamp,published_at:null,source:'FRED',source_url:'https://fred.stlouisfed.org/series/PAYEMS',
  history:[{date:'2026-09-01',display_value:prior,display_unit:unit}],...extra};
}
const snapshot=series=>({updated_at:stamp,status:'ok',series});
test('new periods regenerate examples while identical polling is not a release',()=>{
 const first=macro.advance(null,snapshot({payrolls:item(100,150,'change_thousands','2026-09-01')}));
 const second=macro.advance(first.record,snapshot({payrolls:item(80,100,'change_thousands')}));
 assert.match(second.model.cards.payrolls.lead,/octubre.*80 mil empleos/);
 assert.match(second.model.cards.payrolls.changed,/Se incorpora octubre.*septiembre/);
 assert.match(second.model.cards.payrolls.meaning,/Se sigue creando empleo.*ritmo menor/);
 const again=macro.advance(second.record,snapshot({payrolls:item(80,100,'change_thousands')}));
 assert.match(again.model.cards.payrolls.changed,/Mismo período y misma cifra/);
 assert.equal(again.record.changes.length,0);
});
test('same-period corrections persist as observed changes, never official revisions',()=>{
 const a=macro.advance(null,snapshot({payrolls:item(80,100,'change_thousands')}));
 const b=macro.advance(a.record,snapshot({payrolls:item(90,100,'change_thousands')}));
 assert.match(b.model.cards.payrolls.changed,/cambió desde.*80/);
 assert.match(b.model.cards.payrolls.changed,/no se atribuye automáticamente a una revisión/);
 assert.deepEqual(b.record.changes.map(c=>[c.from,c.to]),[[80,90]]);
 const c=macro.advance(b.record,snapshot({payrolls:item(90,100,'change_thousands')}));
 assert.equal(c.record.changes.length,1);
});
test('stale, unavailable, invalid dates and false numeric values cannot drive context',()=>{
 for(const patch of [{status:'stale'},{status:'unavailable'},{status:'error'},{context_usable:false},{period_warning:'Antiguo'},
  {date:'2026-02-30'},{display_value:null},{display_value:Infinity},{display_value:false}]){
  const model=macro.build(snapshot({cpi:item(3,4,'percent_yoy','2026-10-01',patch)}));
  assert.equal(model.cards.cpi.usable,false,JSON.stringify(patch));
  assert.equal(model.cards.cpi.meaning,undefined);
  assert.match(model.summary[0],/No hay inflación con vigencia confirmada/);
 }
});
test('older periods cannot replace the last verified browser observation',()=>{
 const newer=macro.advance(null,snapshot({cpi:item(3,4)}));
 const older=macro.advance(newer.record,snapshot({cpi:item(2,3,'percent_yoy','2026-09-01')}));
 assert.equal(older.model.cards.cpi.usable,false);
 assert.equal(older.record.snapshot.series.cpi.date,'2026-10-01');
});
test('only contiguous comparable units establish a prior-period direction',()=>{
 const gap=item(90,100,'change_thousands','2026-11-01');
 assert.equal(macro.comparison(gap,'payrolls').direction,null);
 const wrongUnit=item(90,100,'change_thousands','2026-10-01',{history:[]});
 wrongUnit.previous={date:'2026-09-01',display_value:100,display_unit:'thousands'};
 assert.equal(macro.comparison(wrongUnit,'payrolls').direction,null);
 const weekly=item(220000,230000,'persons','2026-10-31',{frequency:'weekly',history:[{date:'2026-10-24',display_value:230000,display_unit:'persons'}]});
 assert.equal(macro.comparison(weekly,'initial_claims').delta,-10000);
});
test('monthly, annual and quarterly annualized measures stay distinct',()=>{
 assert.match(macro.formatValue(item(0.3,0.2,'percent_mom')),/mensual/);
 assert.match(macro.formatValue(item(2.5,2.4)),/interanual/);
 assert.match(macro.formatValue(item(3.1,2.4,'percent_qoq_annualized')),/trimestral anualizado/);
 const model=macro.build(snapshot({gdp:item(2,1,'percent_yoy','2026-07-01',{frequency:'quarterly',metrics:{qoq_annualized:3.2}})}));
 assert.match(model.cards.gdp.period,/T3 de 2026/);
 const html=macro.cardHTML(model.cards.gdp,[]);
 assert.match(html,/Variación trimestral anualizada/);
 assert.match(html,/no es el crecimiento interanual/);
});
test('zero and negative inflation/GDP do not falsely describe rising prices or output',()=>{
 const model=macro.build(snapshot({cpi:item(-1,-2),core_pce:item(0,1),gdp:item(0,1)}));
 assert.match(model.cards.cpi.meaning,/caída de precios.*se suavizó/);
 assert.doesNotMatch(model.cards.cpi.meaning,/encarecimiento anual ganó/);
 assert.match(model.cards.core_pce.meaning,/nivel de precios fue igual/);
 assert.match(model.cards.gdp.meaning,/producción no cambió/);
});
test('mixed inflation and sectors are explicit, the PMI 50 boundary is not expansion',()=>{
 const mixed=macro.build(snapshot({cpi:item(3,3.2),pce:item(2.7,2.5),pmi:item(49,48,'index'),services_pmi:item(52,53,'index')}));
 assert(mixed.summary.some(t=>t.includes('direcciones distintas')));
 assert(mixed.summary.some(t=>t.includes('divergencia entre sectores')));
 const boundary=macro.build(snapshot({pmi:item(50,49,'index'),services_pmi:item(49,48,'index')}));
 assert.match(boundary.cards.pmi.meaning,/umbral/);
 assert(!boundary.summary.some(t=>t.includes('lados distintos de 50')));
});
test('employment synthesis distinguishes slower hiring from job destruction',()=>{
 const cooling=macro.build(snapshot({payrolls:item(80,140,'change_thousands'),unemployment:item(4.3,4.1,'percent')}));
 assert(cooling.summary.some(t=>t.includes('Todavía se crean puestos')));
 assert.match(cooling.cards.payrolls.markets,/deterioro fuerte puede perjudicarlas/);
 const falling=macro.build(snapshot({payrolls:item(-20,80,'change_thousands'),unemployment:item(4.4,4.1,'percent')}));
 assert(falling.summary.some(t=>t.includes('ambas lecturas apuntan a deterioro')));
});
test('synthesis connects inflation and employment only with matching periods',()=>{
 const tension=macro.build(snapshot({pce:item(3,2.8),payrolls:item(80,140,'change_thousands')}));
 assert(tension.summary.some(t=>t.includes('tensión entre controlar precios y sostener empleo')));
 const easing=macro.build(snapshot({pce:item(2.8,3),payrolls:item(80,140,'change_thousands')}));
 assert(easing.summary.some(t=>t.includes('riesgo sobre beneficios puede contrarrestar')));
 const mismatch=macro.build(snapshot({pce:item(2.8,3),payrolls:item(80,140,'change_thousands','2026-09-01')}));
 assert(mismatch.summary.some(t=>t.includes('corresponden a meses distintos')));
 assert(!mismatch.summary.some(t=>t.includes('tensión entre controlar')));
});
test('dates remain publication/period/consultation separate and use Santo Domingo',()=>{
 assert.match(macro.period(item(1,2),'cpi'),/octubre.*2026/);
 assert.match(macro.localTime('2026-11-05'),/5 de noviembre/);
 const text=macro.localTime(stamp);
 assert.match(text,/9:30/);
 const html=macro.cardHTML(macro.build(snapshot({payrolls:item(80,100,'change_thousands')})).cards.payrolls,[]);
 assert.match(html,/Fecha de publicación:.*No suministrada/);
 assert.match(html,/Consenso previo:.*No disponible/);
 assert.match(html,/Reacción observada del mercado:.*No hay cotizaciones verificadas/);
});
test('source and observed-revision rendering escapes values and rejects script URLs',()=>{
 const row=item(80,100,'change_thousands','2026-10-01',{source:'<img src=x onerror=alert(1)>',source_url:'javascript:alert(1)',warning:'<script>bad</script>',
  revisions:[{date:'2026-09-01',previous_value:100,value:90,display_unit:'change_thousands',detected_at:stamp}],
  revision_note:'No equivale a una revisión oficial; se pierde al reiniciar el servidor.'});
 const html=macro.cardHTML(macro.build(snapshot({payrolls:row})).cards.payrolls,[]);
 assert.doesNotMatch(html,/<script>|<img|href="javascript:/);
 assert.match(html,/&lt;script&gt;bad/);
 assert.match(html,/Cambios observados entre consultas al servidor/);
 assert.match(html,/No equivale a una revisión oficial/);
});
test('damaged local comparison cache cannot break the course or create fake changes',()=>{
 const result=macro.advance({version:1,snapshot:{series:{cpi:null,payrolls:{date:'bad',display_value:0}}},changes:[null,1,{key:'payrolls',date:'bad',from:0,to:2}]},snapshot({payrolls:item(80,100,'change_thousands')}));
 assert.equal(result.record.changes.length,0);
 assert.equal(result.model.cards.payrolls.usable,true);
});
