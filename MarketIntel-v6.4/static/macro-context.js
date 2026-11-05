(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.MarketIntelMacroContext=api;})(typeof globalThis!=='undefined'?globalThis:this,function(){
'use strict';
const STORAGE_KEY='mi_macro_context_observed_v1',ZONE='America/Santo_Domingo';
const PANELS=[
 ['fed','Política monetaria',['fed_upper']],
 ['inflation','Precios en el contexto actual',['cpi','pce']],
 ['cpi','El IPC publicado, explicado',['cpi','core_cpi']],
 ['pce','El PCE publicado, explicado',['pce','core_pce']],
 ['nfp','El empleo publicado, explicado',['payrolls','unemployment','wages','jolts','initial_claims']],
 ['pib','Crecimiento y consumo publicados',['gdp','retail_sales']],
 ['pmi','La actividad publicada, explicada',['pmi','services_pmi']],
 ['consumer','Confianza frente al gasto',['consumer_sentiment','retail_sales']]
];
const LABELS={fed_upper:'Tasa objetivo de la Fed',cpi:'IPC general',core_cpi:'IPC subyacente',pce:'PCE general',core_pce:'PCE subyacente',payrolls:'Empleo no agrícola (NFP)',unemployment:'Tasa de desempleo',wages:'Salarios por hora',gdp:'PIB real',retail_sales:'Ventas minoristas',pmi:'ISM manufacturero',services_pmi:'ISM de servicios',consumer_sentiment:'Confianza de U. Michigan',jolts:'Vacantes de empleo (JOLTS)',initial_claims:'Solicitudes iniciales de desempleo'};
const INFLATION=new Set(['cpi','core_cpi','pce','core_pce']);
const number=v=>(typeof v==='number'||(typeof v==='string'&&v.trim()!==''))&&Number.isFinite(Number(v));
const round=v=>Number(v).toLocaleString('es-DO',{maximumFractionDigits:2});
const signed=v=>(Number(v)>0?'+':'')+round(v);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function safeURL(v){try{const u=new URL(v);return ['https:','http:'].includes(u.protocol)?u.href:null;}catch(_){return null;}}
function dateParts(v){
 if(typeof v!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(v))return null;
 const d=new Date(v+'T00:00:00Z');
 return Number.isFinite(d.getTime())&&d.toISOString().slice(0,10)===v?v.split('-').map(Number):null;
}
function period(item,key){
 const p=dateParts(item?.date);if(!p)return 'período no disponible';
 if(key==='gdp'||item.frequency==='quarterly')return 'T'+(Math.floor((p[1]-1)/3)+1)+' de '+p[0];
 const d=new Date(item.date+'T12:00:00Z');
 const monthly=item.frequency==='monthly'||(!item.frequency&&!['fed_upper','fed_lower','treasury_10y','initial_claims'].includes(key));
 return d.toLocaleDateString('es-DO',monthly?{month:'long',year:'numeric',timeZone:'UTC'}:{day:'numeric',month:'long',year:'numeric',timeZone:'UTC'});
}
function localTime(v){
 if(!v)return 'no disponible';
 if(dateParts(v))return new Date(v+'T12:00:00Z').toLocaleDateString('es-DO',{day:'numeric',month:'long',year:'numeric',timeZone:'UTC'});
 const d=new Date(v);return Number.isFinite(d.getTime())?d.toLocaleString('es-DO',{dateStyle:'medium',timeStyle:'short',timeZone:ZONE}):'no disponible';
}
function formatValue(item){
 if(!number(item?.display_value))return 'sin dato verificable';
 const v=Number(item.display_value),u=item.display_unit;
 if(u==='percent_yoy')return round(v)+'% interanual';
 if(u==='percent_mom')return signed(v)+'% mensual';
 if(u==='percent_qoq_annualized')return signed(v)+'% trimestral anualizado';
 if(u==='percent')return round(v)+'%';
 if(u==='change_thousands')return signed(v)+' mil empleos en el mes';
 if(u==='thousands')return round(v)+' mil';
 if(u==='billions')return round(v)+' mil millones de USD';
 if(u==='persons'||u==='count')return round(v)+' personas';
 return round(v)+(u==='index'?' puntos':'');
}
function usable(item){return !!item&&item.context_usable!==false&&item.status==='ok'&&!item.period_warning&&number(item.display_value)&&!!dateParts(item.date);}
function shiftDate(date,months,days=0){const p=dateParts(date);if(!p)return null;return new Date(Date.UTC(p[0],p[1]-1+months,p[2]+days)).toISOString().slice(0,10);}
function previous(item,key){
 const rows=[item?.previous,...(Array.isArray(item?.history)?item.history:[])].filter(r=>r&&dateParts(r.date)&&r.date<item.date&&r.display_unit===item.display_unit&&number(r.display_value));
 const daily=item?.frequency==='daily'||['fed_upper','fed_lower','treasury_10y'].includes(key);
 const prior=key==='gdp'||item?.frequency==='quarterly'?shiftDate(item.date,-3):key==='initial_claims'||item?.frequency==='weekly'?shiftDate(item.date,0,-7):shiftDate(item.date,-1);
 return daily?rows.sort((a,b)=>b.date.localeCompare(a.date))[0]||null:rows.find(r=>r.date===prior)||null;
}
function comparison(item,key){
 const prior=previous(item,key);
 if(!prior)return {direction:null,text:'No hay un período anterior comparable en esta respuesta; no se atribuye una aceleración ni una desaceleración.'};
 const delta=Number(item.display_value)-Number(prior.display_value),direction=Math.abs(delta)<0.005?0:Math.sign(delta);
 const unit=['percent','percent_yoy','percent_mom','percent_qoq_annualized'].includes(item.display_unit)?'puntos porcentuales':item.display_unit==='change_thousands'?'mil empleos':item.display_unit==='thousands'?'mil':item.display_unit==='persons'?'personas':'puntos';
 return {prior,direction,delta,text:'Frente a '+period({...item,date:prior.date},key)+': '+formatValue(prior)+'. '+(direction?'La diferencia es de '+signed(delta)+' '+unit+'.':'La cifra se mantiene en la precisión publicada.')};
}
function observationChange(item,old,key){
 if(!old||!number(old.display_value))return 'Primera lectura disponible en este navegador. La comparación económica usa los períodos de la fuente, no una supuesta publicación anterior.';
 if(item.display_unit!==old.display_unit)return 'Cambió la medida disponible. No se compara directamente con la lectura anterior de este navegador.';
 if(item.date>old.date)return 'Se incorpora '+period(item,key)+' en lugar de '+period(old,key)+'. La explicación se recalcula con el nuevo período.';
 if(item.date<old.date)return 'La fuente devolvió un período anterior al ya observado; se suspende la lectura actual hasta verificarlo.';
 if(Number(item.display_value)!==Number(old.display_value))return 'La cifra de este mismo período cambió desde '+formatValue(old)+' en la consulta anterior. Es un cambio observado en este navegador; sin una versión oficial anterior no se atribuye automáticamente a una revisión del organismo.';
 return 'Mismo período y misma cifra que en la consulta anterior; volver a consultar no equivale a una nueva publicación.';
}
function meaning(key,item,cmp,series){
 const v=Number(item.display_value),d=cmp.direction;
 if(INFLATION.has(key)){
  const level=v<0?'El nivel de precios fue inferior al del mismo mes del año anterior.':v===0?'El nivel de precios fue igual al del mismo mes del año anterior en la precisión publicada.':'El nivel de precios fue superior al del mismo mes del año anterior.';
  const direction=d===-1?(v>0?' La tasa interanual bajó: los precios crecen más despacio; no significa que todo cueste menos.':v<0?' La tasa interanual bajó y es negativa: la caída de precios frente a un año antes se acentuó.':' La tasa interanual descendió hasta cero en esta comparación.'):
   d===1?(v>0?' La tasa interanual aumentó: el encarecimiento anual ganó ritmo.':v<0?' La tasa interanual aumentó, pero sigue negativa: la caída de precios frente a un año antes se suavizó.':' La tasa interanual aumentó hasta cero en esta comparación.'):
   d===0?' La tasa interanual permanece estable en esta comparación.':' Sin un mes anterior comparable no se puede confirmar la dirección de la inflación.';
  return level+direction+(key.startsWith('core')?' Subyacente significa que excluye alimentos y energía; ayuda a estudiar la persistencia, pero no sustituye la inflación total que pagan los hogares.':' La cifra general incluye alimentos y energía.')+' Conviene contrastar la variación mensual y sus componentes. Un cambio interanual también puede responder al mes que sale de la comparación: el llamado efecto base.';
 }
 if(key==='payrolls')return (v<0?'El saldo neto de empleo no agrícola fue negativo: se perdieron puestos frente al mes anterior.':v===0?'El saldo neto de puestos fue prácticamente nulo en la precisión publicada.':'Se añadieron puestos de trabajo frente al mes anterior.')+(d===-1&&v>0?' Se sigue creando empleo, pero a un ritmo menor que en el mes previo; esto no es lo mismo que destruir empleo.':d===1?' El saldo mensual mejoró respecto al período anterior.':'')+' NFP mide puestos en nómina, no personas únicas. Desempleo, salarios y revisiones ayudan a distinguir enfriamiento gradual de deterioro.';
 if(key==='unemployment')return 'Es la proporción de la población activa que busca trabajo y no lo tiene. '+(d===1?'El aumento puede señalar menor capacidad de absorber trabajadores; también puede influir la entrada de más personas a buscar empleo.':d===-1?'La caída puede reflejar contratación o salida de personas de la población activa; la participación ayuda a distinguirlo.':'Debe leerse junto con la participación laboral y las nóminas.')+' La diferencia entre dos tasas se expresa en puntos porcentuales.';
 if(key==='wages')return 'Mide la variación interanual del salario medio por hora, antes de descontar inflación. '+(d===1?'El crecimiento salarial ganó ritmo respecto al mes previo.':d===-1?'El crecimiento salarial perdió ritmo respecto al mes previo.':'La cifra debe contrastarse con inflación, productividad y composición del empleo.')+' Los salarios sostienen el consumo; también pueden presionar costos si crecen por encima de la productividad. No determinan por sí solos la inflación.';
 if(key==='gdp')return 'El PIB real descuenta los cambios de precios. Esta cifra interanual compara el trimestre con el mismo trimestre del año anterior; no es la variación trimestral anualizada de los titulares.'+(v<0?' El nivel de producción es inferior al de un año antes.':v>0?' El nivel de producción es superior al de un año antes.':' El nivel de producción no cambió frente a un año antes en la precisión publicada.')+' La composición entre consumo, inversión e inventarios importa. Dos trimestres negativos no constituyen por sí solos una declaración oficial de recesión en EE. UU.';
 if(key==='retail_sales')return 'Las ventas minoristas muestran el gasto nominal en comercios; una variación mensual positiva no prueba que se compraran más unidades, porque también influyen los precios. '+(v<0?'La caída mensual apunta a menor facturación minorista.':v>0?'El aumento mensual apunta a mayor facturación minorista.':'La facturación mensual apenas cambió.')+' No cubren todo el consumo, especialmente muchos servicios.';
 if(key==='pmi'||key==='services_pmi')return 'ISM es una encuesta de difusión: resume cuántas empresas informan mejoras o deterioros. '+(v>50?'Por encima de 50, el sector informa expansión frente al mes anterior.':v<50?'Por debajo de 50, el sector informa contracción frente al mes anterior.':'En 50, la encuesta está en el umbral entre expansión y contracción.')+(d===1&&v<50?' Subió respecto a la lectura anterior, pero sigue bajo 50: la contracción se suaviza, no se convierte todavía en expansión.':d===-1&&v>50?' Bajó, pero sigue sobre 50: la expansión pierde impulso.':'')+' Manufactura y servicios pueden dar señales distintas. El índice no es una tasa de crecimiento del PIB.';
 if(key==='jolts')return 'Son puestos vacantes que los empleadores buscan cubrir; no son contrataciones realizadas. '+(d===-1?'La caída puede indicar menor demanda de trabajadores.':d===1?'El aumento puede indicar mayor demanda de trabajadores o dificultades para cubrir puestos.':'Conviene compararlos con contrataciones, renuncias y desempleados.')+' JOLTS se publica con más retraso que las nóminas; revisa el mes antes de combinar ambas lecturas.';
 if(key==='initial_claims')return 'Son nuevas solicitudes semanales de seguro de desempleo, no el total de desempleados. '+(d===1?'Un aumento puede advertir de más despidos, pero una semana aislada puede ser ruidosa.':d===-1?'La caída sugiere menos solicitudes esa semana; no demuestra por sí sola una aceleración de la contratación.':'La media de varias semanas ayuda a separar ruido de tendencia.')+' Festivos y ajustes estacionales pueden influir.';
 if(key==='fed_upper'){const lower=series.fed_lower;return (usable(lower)&&lower.date===item.date?'El rango objetivo observado es '+round(lower.display_value)+'–'+round(v)+'%.':'Esta lectura corresponde al límite superior del rango objetivo, no a todo el rango.')+' Es la política vigente en la fecha de la serie. Su comparación diaria no prueba que haya ocurrido una reunión ese día. Los comunicados, declaraciones y expectativas implícitas del mercado requieren fuentes propias; no se deducen de este nivel.';}
 return 'La encuesta mide percepciones de los hogares, no ventas realizadas. '+(d===1?'La mejora de confianza podría apoyar decisiones de gasto, si ingresos y crédito lo permiten.':d===-1?'El deterioro de confianza puede hacer que los hogares sean más cautelosos, aunque el gasto todavía resista.':'Conviene contrastar confianza con datos de ingresos y consumo.')+' El dato de Michigan y el de Conference Board pertenecen a encuestas distintas y no se comparan como si fueran la misma serie.';
}
function implications(key,item,cmp){
 const d=cmp.direction;
 if(INFLATION.has(key)||key==='wages')return {fed:(d===-1?'La moderación podría dar margen para una política menos restrictiva si se sostiene y el empleo lo permite.':d===1?'La aceleración puede favorecer cautela con los recortes, si otros datos confirman persistencia inflacionaria.':'La Fed necesita una trayectoria de varias publicaciones para valorar si la presión de precios cede.')+' Su meta del 2% corresponde al PCE general a largo plazo; el subyacente ayuda a analizar la tendencia. Un solo dato no decide una reunión.',markets:'Si el dato lleva al mercado a descontar tasas más bajas, podría apoyar las valoraciones de acciones, elevar el precio de bonos de pagos fijos y reducir sus rendimientos. El dólar podría perder apoyo relativo. Si cambian las expectativas hacia tasas más altas, puede ocurrir lo contrario. El crecimiento, las primas de riesgo y lo ya esperado pueden alterar esas respuestas.'};
 if(['payrolls','unemployment','jolts','initial_claims'].includes(key))return {fed:'Un enfriamiento sostenido del empleo puede dar margen para bajar tasas, mientras que un mercado laboral resistente puede permitir esperar. La decisión también depende de inflación, salarios y condiciones financieras.',markets:'Un enfriamiento gradual podría ayudar a las acciones si reduce la presión sobre las tasas. Un deterioro fuerte puede perjudicarlas por menores ventas y beneficios, aun cuando se esperen recortes. Si caen los rendimientos, suele subir el precio de bonos de pagos fijos; el dólar puede debilitarse por tasas relativas o fortalecerse como refugio. No hay una equivalencia automática entre dato débil y bolsa al alza.'};
 if(key==='fed_upper')return {fed:'La tasa publicada muestra una decisión ya vigente, no una promesa para la siguiente reunión. Para atribuir una postura a la Fed hay que consultar su comunicado y sus declaraciones; aquí no se presenta una probabilidad de recorte.',markets:'Tasas más altas elevan el costo de financiarse y de descontar beneficios futuros; tasas más bajas pueden aliviarlo. La bolsa también valora el motivo del cambio. Los precios de bonos de pagos fijos y sus rendimientos se mueven en direcciones opuestas. El dólar depende de la diferencia de tasas frente a otras economías y del apetito por riesgo.'};
 return {fed:'Una actividad resistente puede permitir a la Fed esperar mientras evalúa la inflación. Una pérdida persistente de impulso puede favorecer alivio monetario, siempre que el contexto de precios lo permita.',markets:'Una mejora de actividad puede sostener ingresos y beneficios empresariales, pero también rendimientos más altos si retrasa recortes. Un deterioro puede presionar a las acciones aunque aumenten las expectativas de estímulo. En bonos de pagos fijos, una caída del rendimiento implica un aumento del precio. El dólar responde a las tasas relativas y a la demanda de refugio, además del dato.'};
}
function describe(key,item,old,series){
 const title=LABELS[key]||item?.label||key,valid=usable(item)&&!(old?.date&&item.date<old.date);
 const card={key,title,usable:valid,value:formatValue(item),period:period(item,key),status:valid?'Lectura disponible':'Vigencia sin confirmar',item:item||{}};
 if(!valid){card.lead=number(item?.display_value)?'La última cifra recibida es '+card.value+' para '+card.period+'. Su actualización no está confirmada; no se usa para explicar el contexto vigente.':'No hay una cifra verificable disponible en esta consulta. La explicación se actualizará cuando responda la fuente.';card.warning=item?.period_warning||item?.warning||item?.error||(old?.date&&item?.date<old.date?'La fuente devolvió un período anterior al observado.':'Dato no disponible o no vigente.');return card;}
 const cmp=comparison(item,key),i=implications(key,item,cmp);
 card.direction=cmp.direction;card.lead='Para '+card.period+', '+title.toLowerCase()+' registra '+card.value+'.';card.comparison=cmp.text;card.meaning=meaning(key,item,cmp,series);card.changed=observationChange(item,old,key);card.fed=i.fed;card.markets=i.markets;card.warning=[item.warning,item.period_warning].filter(Boolean).join(' ');return card;
}
function build(macro,previousSnapshot){
 const series=macro?.series||{},prev=previousSnapshot?.series||{},cards={};
 for(const [,,keys]of PANELS)for(const key of keys)if(!cards[key])cards[key]=describe(key,series[key],prev[key],series);
 const summary=[],inflation=['cpi','pce','core_pce'].filter(k=>cards[k].usable);
 if(inflation.length){summary.push('Inflación: '+inflation.map(k=>cards[k].title+' '+cards[k].value+' ('+cards[k].period+')').join('; ')+'.');const dirs=inflation.map(k=>cards[k].direction).filter(v=>v!==null);summary.push(dirs.includes(1)&&dirs.includes(-1)?'Las medidas de inflación dan direcciones distintas respecto a sus períodos anteriores. No hay una señal uniforme de aceleración o moderación.':dirs.length?'En las medidas comparables, '+(dirs.includes(1)?'hay tasas que aumentan.':'las tasas disminuyen o se mantienen.')+' La comparación mensual de una tasa interanual puede incluir efectos base.':'Faltan períodos comparables para establecer una dirección de la inflación.');}
 else summary.push('No hay inflación con vigencia confirmada para resumir el panorama de precios.');
 const work=['payrolls','unemployment'].filter(k=>cards[k].usable);
 summary.push(work.length?'Empleo: '+work.map(k=>cards[k].title+' '+cards[k].value+' ('+cards[k].period+')').join('; ')+'. Revisa salarios y revisiones antes de calificar la fortaleza del mercado laboral.':'Faltan datos de empleo con vigencia confirmada.');
 if(cards.payrolls.usable&&cards.unemployment.usable){
  if(series.payrolls.date!==series.unemployment.date)summary.push('Nóminas y desempleo describen meses distintos. No se combinan como si fueran una sola publicación.');
  else if(Number(series.payrolls.display_value)<0&&cards.unemployment.direction===1)summary.push('Las nóminas caen y el desempleo sube: ambas lecturas apuntan a deterioro laboral. Podría aumentar el margen para recortar tasas, pero también el riesgo para ventas y beneficios empresariales.');
  else if(Number(series.payrolls.display_value)>0&&cards.payrolls.direction===-1&&cards.unemployment.direction===1)summary.push('Todavía se crean puestos, pero a menor ritmo, y sube el desempleo. Es una combinación compatible con enfriamiento; hace falta ver si se estabiliza o se profundiza.');
  else if(cards.payrolls.direction===1&&cards.unemployment.direction===-1)summary.push('El saldo de nuevos puestos mejora y el desempleo baja. Ambas lecturas apoyan la resistencia del empleo, sin demostrar por sí solas una aceleración de la inflación.');
 }
 const priceKey=['pce','cpi','core_pce'].find(key=>cards[key].usable&&cards[key].direction!==null);
 if(priceKey&&cards.payrolls.usable){
  const prices=cards[priceKey],jobs=cards.payrolls,jobLevel=Number(series.payrolls.display_value);
  if(series[priceKey].date!==series.payrolls.date)summary.push('La inflación y las nóminas disponibles corresponden a meses distintos. La síntesis describe una secuencia de lecturas, no una confirmación conjunta del mismo mes.');
  else if(prices.direction===1&&(jobs.direction===-1||jobLevel<0))summary.push('La tasa de '+prices.title.toLowerCase()+' aumenta mientras el empleo pierde impulso: hay tensión entre controlar precios y sostener empleo. Esto complica la decisión de la Fed; para las acciones pueden coincidir presión sobre tasas y riesgo sobre beneficios.');
  else if(prices.direction===-1&&jobLevel>0&&jobs.direction===-1)summary.push('La tasa de '+prices.title.toLowerCase()+' baja y todavía se crean empleos, aunque más despacio. Si la combinación se sostiene, podría dar margen para reducir la restricción y apoyar las valoraciones. Si el enfriamiento se profundiza, el riesgo sobre beneficios puede contrarrestar ese apoyo.');
  else if(prices.direction===-1&&jobLevel<0)summary.push('La tasa de '+prices.title.toLowerCase()+' baja, pero también se pierden empleos. Podría aumentar el margen para recortar tasas y apoyar el precio de bonos si caen sus rendimientos; las acciones seguirían expuestas al deterioro de ingresos y beneficios.');
 }
 const activity=['pmi','services_pmi','gdp','retail_sales'].filter(k=>cards[k].usable);
 summary.push(activity.length?'Actividad y consumo: '+activity.map(k=>cards[k].title+' '+cards[k].value+' ('+cards[k].period+')').join('; ')+'. Las frecuencias y períodos son distintos; no todos describen el mismo momento.':'Faltan datos de actividad y consumo con vigencia confirmada.');
 if(cards.pmi.usable&&cards.services_pmi.usable&&((Number(series.pmi.display_value)-50)*(Number(series.services_pmi.display_value)-50)<0))summary.push('Manufactura y servicios se sitúan a lados distintos de 50: hay divergencia entre sectores, no una expansión o contracción uniforme.');
 summary.push(cards.fed_upper.usable?cards.fed_upper.meaning:'No hay una tasa de política monetaria con vigencia confirmada.');
 return {cards,panels:PANELS.map(([id,title,keys])=>({id,title,cards:keys.map(k=>cards[k])})),summary,updated:localTime(macro?.updated_at)};
}
function advance(record,macro){
 record=record&&record.version===1?record:{version:1,snapshot:{series:{}},changes:[]};
 const series={};
 for(const [key,item]of Object.entries(record.snapshot?.series||{}))if(Object.hasOwn(LABELS,key)&&dateParts(item?.date)&&number(item?.display_value)&&typeof item.display_unit==='string')series[key]=item;
 const model=build(macro,{series}),changes=Array.isArray(record.changes)?record.changes.filter(c=>c&&Object.hasOwn(LABELS,c.key)&&dateParts(c.date)&&number(c.from)&&number(c.to)&&typeof c.display_unit==='string').slice(-40):[];
 for(const [key,card]of Object.entries(model.cards)){if(!card.usable)continue;const item=card.item,prior=series[key];if(prior&&prior.date===item.date&&prior.display_unit===item.display_unit&&Number(prior.display_value)!==Number(item.display_value))changes.push({key,date:item.date,from:Number(prior.display_value),to:Number(item.display_value),display_unit:item.display_unit,observed_at:macro.updated_at||null});series[key]={date:item.date,display_value:Number(item.display_value),display_unit:item.display_unit,frequency:item.frequency};}
 model.changes=changes.slice(-40);return {model,record:{version:1,snapshot:{series},changes:model.changes}};
}
function paragraph(label,value){return value?'<p><strong>'+esc(label)+'</strong> '+esc(value)+'</p>':'';}
function cardHTML(card,changes){
 const item=card.item,sourceURL=safeURL(item.source_url),releaseURL=safeURL(item.release_url);
 const links=[sourceURL?'<a href="'+esc(sourceURL)+'" target="_blank" rel="noopener noreferrer">'+esc(item.source||'Serie consultada')+'</a>':'Fuente de la cifra no enlazada en esta respuesta',releaseURL&&releaseURL!==sourceURL?'<a href="'+esc(releaseURL)+'" target="_blank" rel="noopener noreferrer">Publicación del organismo</a>':''].filter(Boolean).join(' · ');
 const observed=changes.filter(c=>c.key===card.key).slice(-3).reverse().map(c=>'<li>'+esc(period({date:c.date,frequency:item.frequency},card.key))+': '+esc(formatValue({display_value:c.from,display_unit:c.display_unit}))+' → '+esc(formatValue({display_value:c.to,display_unit:c.display_unit}))+' · observado '+esc(localTime(c.observed_at))+'</li>').join('');
 const serverChanges=(Array.isArray(item.revisions)?item.revisions:[]).filter(c=>c&&dateParts(c.date)&&number(c.previous_value)&&number(c.value)&&c.display_unit===item.display_unit).slice(-3).reverse().map(c=>'<li>'+esc(period({date:c.date,frequency:item.frequency},card.key))+': '+esc(formatValue({display_value:c.previous_value,display_unit:c.display_unit}))+' → '+esc(formatValue({display_value:c.value,display_unit:c.display_unit}))+' · detectado '+esc(localTime(c.detected_at))+'</li>').join('');
 const serverHistory=serverChanges?'<p><strong>Cambios observados entre consultas al servidor</strong></p><ul>'+serverChanges+'</ul>'+paragraph('Alcance de esta comparación:',item.revision_note||'No equivale a una revisión oficial. Este historial puede perderse al reiniciar el servidor.') : '';
 let metrics='';
 for(const [name,label]of [['mom','Variación mensual'],['yoy','Variación interanual'],['qoq_annualized','Variación trimestral anualizada']]){const m=item.metrics?.[name],v=typeof m==='object'?m?.value:m;if(card.usable&&number(v))metrics+=paragraph(label,round(v)+'%'+(name==='qoq_annualized'?' · ritmo de un trimestre elevado a un año; no es el crecimiento interanual.':''));}
 return '<article class="mc-card'+(card.usable?'':' mc-unavailable')+'" data-macro-context-key="'+esc(card.key)+'"><div class="mc-card-heading"><h4>'+esc(card.title)+'</h4><span>'+esc(card.status)+'</span></div><p class="mc-lead">'+esc(card.lead)+'</p>'+(card.usable?'<p>'+esc(card.meaning)+'</p>':'')+'<details><summary>Comparación, mercados y fuentes</summary><div class="mc-details">'+paragraph('Frente al período previo:',card.comparison)+metrics+paragraph('Qué cambió:',card.changed)+paragraph('Para la Fed:',card.fed)+paragraph('Bolsa, bonos y dólar:',card.markets)+paragraph('Consenso previo:','No disponible con una fuente verificada; no se califica el dato como sorpresa frente a lo esperado.')+paragraph('Reacción observada del mercado:','No hay cotizaciones verificadas con una ventana alrededor de esta publicación. Los efectos descritos son escenarios, no una reacción observada.')+paragraph('Revisiones oficiales:','No se dispone de un historial oficial de versiones de cada publicación. El dato anterior de la serie puede estar revisado.')+(observed?'<p><strong>Cambios observados en este navegador</strong></p><ul>'+observed+'</ul>':'')+serverHistory+paragraph('Aviso de la fuente:',card.warning)+'<p class="mc-sources">'+links+'</p>'+paragraph('Período medido:',card.period)+paragraph('Fecha de publicación:',item.published_at?localTime(item.published_at):'No suministrada de forma verificable por esta respuesta; no se sustituye por la fecha del período.')+paragraph('Última consulta a la fuente:',localTime(item.fetched_at)+' · America/Santo_Domingo')+'</div></details></article>';
}
let memoryRecord=null;
function render(macro){
 if(typeof document==='undefined')return build(macro);
 if(memoryRecord===null){try{memoryRecord=JSON.parse(localStorage.getItem(STORAGE_KEY));}catch(_){}}
 const result=advance(memoryRecord,macro);memoryRecord=result.record;try{localStorage.setItem(STORAGE_KEY,JSON.stringify(memoryRecord));}catch(_){}
 const model=result.model;
 for(const panel of model.panels){const target=document.getElementById('ind-'+panel.id);if(!target)continue;let host=target.querySelector('.mi-macro-context');if(!host){host=document.createElement('section');host.className='mi-macro-context';target.insertBefore(host,target.querySelector('.example'));}
 const opened=new Set([...host.querySelectorAll('details[open]')].map(el=>el.closest('[data-macro-context-key]')?.dataset.macroContextKey));
 host.innerHTML='<div class="mc-heading"><span>Ejemplo con datos publicados</span><h3>'+esc(panel.title)+'</h3></div>'+panel.cards.map(card=>cardHTML(card,model.changes)).join('');
 host.querySelectorAll('[data-macro-context-key]').forEach(el=>{if(opened.has(el.dataset.macroContextKey))el.querySelector('details').open=true;});
 }
 const summary=document.getElementById('macro-context-summary');
 if(summary){const opened=summary.querySelector('details')?.open;summary.classList.add('mi-macro-context','mc-overview');summary.innerHTML='<div class="mc-heading"><span>Contexto con las últimas lecturas disponibles</span><h3>Qué está pasando y cómo interpretarlo</h3></div>'+model.summary.map(line=>'<p>'+esc(line)+'</p>').join('')+'<details'+(opened?' open':'')+'><summary>Qué falta por confirmar y cómo se actualiza</summary><div class="mc-details"><p>Vigila las próximas publicaciones de empleo, IPC, PCE, ISM y PIB para confirmar o cambiar esta lectura. No se asignan fechas de calendario sin confirmación oficial.</p><p>La tasa vigente, el mensaje de la Fed y las expectativas del mercado son cosas distintas. Esta conexión no aporta un flujo verificado de comunicados, declaraciones o probabilidades implícitas; consulta el <a href="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm" target="_blank" rel="noopener noreferrer">calendario y los comunicados del FOMC</a>.</p><p>Se comprueba al abrir la aplicación, al volver a ella y aproximadamente cada cinco minutos mientras permanece abierta. El ejemplo cambia cuando la fuente entrega un período o una cifra distintos. No hay un proceso que consulte con la app cerrada; tampoco se garantiza recepción al segundo de la publicación.</p><p>Última consulta: '+esc(model.updated)+' · America/Santo_Domingo. La fecha de consulta no es la fecha de publicación.</p></div></details>';}
 return model;
}
return {build,render,advance,describe,usable,comparison,previous,formatValue,period,localTime,cardHTML,STORAGE_KEY};
});
