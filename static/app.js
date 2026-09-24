const $ = id => document.getElementById(id);
const presets = {
  shopping: {title:'Boodschappen',body:'Brood\nMelk\nGroente',checklist:true},
  tasks: {title:'Taken',body:'Eerste taak\nTweede taak',checklist:true},
  reminder: {title:'Niet vergeten',body:'Wat moet ik onthouden?'},
  message: {title:'Berichtje',body:'Schrijf hier je bericht'},
  appointment: {title:'Afspraak',body:'Waar moet ik zijn?',date:true},
  parcel: {title:'Pakket',body:'Wat zit er in het pakket?',checklist:true},
  warning: {title:'Let op',body:'Schrijf de waarschuwing hier',icon:'warning'},
  instructions: {title:'Instructies',body:'Stap één\nStap twee',checklist:true},
  contact: {title:'Contact',body:'Naam\nTelefoonnummer'}
};
const headings = {shopping:'BOODSCHAPPEN',tasks:'TAKEN',reminder:'HERINNERING',message:'BERICHT',appointment:'AFSPRAAK',parcel:'PAKKET',warning:'LET OP',instructions:'INSTRUCTIES',contact:'CONTACT'};
const symbols = {warning:'⚠',info:'ⓘ',star:'★',heart:'♥',home:'⌂'};
const fields = ['title','body','recipient','sender','event-at','copies','date','checklist','paginate','icon','qr','heading','font-size'];
let activeTemplate='',customTemplateId=null,currentNoteId=null,photoData='',updateTimer=0,updateSerial=0;

async function api(path,options={}) {
  const response=await fetch('api/'+path,{headers:{'Content-Type':'application/json'},...options});
  const result=await response.json();
  if(!response.ok)throw Error(result.error||'De bewerking is mislukt.');
  return result;
}
function message(value,error=false){$('message').textContent=value;$('message').className='feedback '+(error?'error':'success')}
function eventInput(value){
  if(!value)return '';
  const match=/^(\d\d)-(\d\d)-(\d{4}) (\d\d:\d\d)$/.exec(value);
  return match?`${match[3]}-${match[2]}-${match[1]}T${match[4]}`:value;
}
function data(){return {
  title:$('title').value,body:$('body').value,recipient:$('recipient').value,sender:$('sender').value,
  event_at:$('event-at').value,copies:Number($('copies').value),date:$('date').checked,
  checklist:$('checklist').checked,paginate:$('paginate').checked,qr:$('qr').value,
  template:activeTemplate,heading:$('heading').value,font_size:Number($('font-size').value),
  icon:$('icon').value,photo:photoData
}}
function applyNote(note){
  customTemplateId=null;$('custom-name').value='';$('delete-template').hidden=true;
  activeTemplate=note.template||'';
  for(const key of ['title','body','recipient','sender','qr','icon','heading'])$(key).value=note[key]||'';
  $('event-at').value=eventInput(note.event_at);
  for(const key of ['date','checklist','paginate'])$(key).checked=!!note[key];
  $('copies').value=note.copies||1;$('font-size').value=String(note.font_size||0);
  $('custom-layout').value=activeTemplate;$('template').value=activeTemplate;
  photoData=note.photo||'';$('photo').value='';$('clear-photo').hidden=!photoData;
  update();
}
function resetNote(){
  currentNoteId=null;customTemplateId=null;$('custom-name').value='';$('delete-template').hidden=true;
  applyNote({title:'',body:'',copies:1});message('Nieuw leeg label.');
}
function applyBuiltin(kind){
  if(!kind){activeTemplate='';$('custom-layout').value='';$('heading').value='';$('font-size').value='0';update();return}
  const source=presets[kind];
  applyNote({...source,template:kind,copies:1});
}
async function applySelectedTemplate(){
  const value=$('template').value;
  try{
    if(value.startsWith('custom:')){
      const id=Number(value.slice(7)),result=await api('templates/'+id);
      applyNote(result.item.payload);customTemplateId=id;$('custom-name').value=result.item.name;
      $('template').value=value;$('delete-template').hidden=false;$('layout-details').open=true;
    }else{applyBuiltin(value);customTemplateId=null;$('custom-name').value='';$('delete-template').hidden=true}
    currentNoteId=null;message('Sjabloon en opmaak toegepast.');
  }catch(e){message(e.message,true)}
}
async function saveTemplate(asNew){
  const name=$('custom-name').value.trim();
  if(!name){message('Geef je sjabloon eerst een naam.',true);$('layout-details').open=true;return}
  activeTemplate=$('custom-layout').value;update();
  const id=asNew?null:customTemplateId;
  try{
    const result=await api(id?'templates/'+id:'templates',{method:id?'PUT':'POST',body:JSON.stringify({name,note:data()})});
    customTemplateId=result.id;$('delete-template').hidden=false;
    await loadTemplates();$('template').value='custom:'+result.id;
    message('Sjabloon en labelindeling bewaard.');
  }catch(e){message(e.message,true)}
}
async function loadTemplates(){
  const result=await api('templates');const group=$('my-templates');group.replaceChildren();
  for(const item of result.items){const option=document.createElement('option');option.value='custom:'+item.id;option.textContent=item.name;group.appendChild(option)}
}
async function deleteTemplate(){
  if(!customTemplateId)return;
  try{await api('templates/'+customTemplateId,{method:'DELETE'});customTemplateId=null;$('delete-template').hidden=true;$('custom-name').value='';$('template').value=activeTemplate;await loadTemplates();message('Sjabloon verwijderd; de huidige notitie blijft staan.')}
  catch(e){message(e.message,true)}
}
function renderFirstPage(layout,note){
  $('paper').className='paper '+layout.style;
  $('preview-kicker').textContent=layout.heading||'';
  $('preview-title').textContent=layout.title||'';
  $('rule').hidden=!layout.title||!note.body||['reminder','message'].includes(layout.style);
  $('preview-meta').textContent=layout.meta.join('\n');
  const art=$('preview-art');art.replaceChildren();art.hidden=!layout.image;
  if(note.photo){const image=document.createElement('img');image.src=note.photo;image.alt='Foto op label';art.appendChild(image)}
  else if(note.icon)art.textContent=symbols[note.icon]||'';
  $('preview-date').textContent=note.date?new Date().toLocaleString('nl-NL',{dateStyle:'short',timeStyle:'short'}):'';
  $('preview-qr').hidden=!note.qr||layout.pages>1;
  const body=$('preview-body');body.replaceChildren();
  for(const line of layout.first_page){
    const row=document.createElement('div');row.className=(line.checkbox?'item':'continuation')+(line.last?' end':'');
    if(layout.style==='tasks'&&line.checkbox){const number=document.createElement('span');number.className='number';number.textContent=line.number+'.';row.appendChild(number)}
    if(note.checklist&&line.checkbox){const box=document.createElement('span');box.className='box';row.appendChild(box)}
    const value=document.createElement('span');value.textContent=line.text||' ';row.appendChild(value);body.appendChild(row);
  }
  $('page-count').textContent=layout.pages+' '+(layout.pages===1?'label':'labels')+' per exemplaar'+(note.copies>1?' · '+layout.pages*note.copies+' totaal':'');
}
function update(){
  clearTimeout(updateTimer);const serial=++updateSerial,note=data();
  $('page-count').textContent=note.title||note.body||note.qr?'Labels berekenen…':'Vul een notitie in';
  if(!note.title&&!note.body&&!note.qr){$('preview-body').replaceChildren();return}
  updateTimer=setTimeout(async()=>{try{const layout=await api('layout',{method:'POST',body:JSON.stringify(note)});if(serial===updateSerial)renderFirstPage(layout,note)}catch(e){if(serial===updateSerial){$('page-count').textContent=e.message;$('preview-body').replaceChildren()}}},220);
}
async function saveNote(){
  try{
    const result=await api(currentNoteId?'notes/'+currentNoteId:'notes',{method:currentNoteId?'PUT':'POST',body:JSON.stringify(data())});
    currentNoteId=result.id;message('Notitie bewaard.');
  }catch(e){message(e.message,true)}
}
async function printNote(){
  $('print').disabled=true;message('Afdruk wordt verzonden…');
  try{const result=await api('print',{method:'POST',body:JSON.stringify(data())});message(result.message+'.');refreshStatus()}
  catch(e){message(e.message,true)}finally{$('print').disabled=false}
}
async function previewPdf(){
  const tab=window.open('','_blank');$('preview-pdf').disabled=true;
  try{
    const response=await fetch('api/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data())});
    if(!response.ok)throw Error((await response.json()).error);
    const url=URL.createObjectURL(await response.blob());
    if(tab)tab.location.href=url;else{const link=document.createElement('a');link.href=url;link.download='notitie.pdf';link.click()}
    setTimeout(()=>URL.revokeObjectURL(url),60000);message('Het volledige labelvoorbeeld is geopend.');
  }catch(e){if(tab)tab.close();message(e.message,true)}finally{$('preview-pdf').disabled=false}
}
async function compressPhoto(file){
  if(!file)return;
  try{
    const image=new Image(),url=URL.createObjectURL(file);
    try{await new Promise((resolve,reject)=>{image.onload=resolve;image.onerror=reject;image.src=url})}
    finally{URL.revokeObjectURL(url)}
    const scale=Math.min(1,360/Math.max(image.naturalWidth,image.naturalHeight));
    const canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.round(image.naturalWidth*scale));canvas.height=Math.max(1,Math.round(image.naturalHeight*scale));
    const context=canvas.getContext('2d');context.filter='grayscale(1)';context.drawImage(image,0,0,canvas.width,canvas.height);
    const result=canvas.toDataURL('image/jpeg',.72);
    if(result.length>360000)throw Error('De foto is te groot. Kies een kleinere afbeelding.');
    photoData=result;$('clear-photo').hidden=false;message('Foto toegevoegd.');update();
  }catch(e){$('photo').value='';message(e.message||'Foto kon niet worden gelezen.',true)}
}
function switchView(name){
  for(const view of document.querySelectorAll('.view'))view.hidden=view.id!==name;
  for(const tab of document.querySelectorAll('.tab'))tab.classList.toggle('active',tab.dataset.view===name);
  if(name==='saved')loadNotes();if(name==='history')loadHistory();if(name==='printer')loadPrinter();
}
function row(title,detail,actions){
  const item=document.createElement('div');item.className='list-item';
  const info=document.createElement('div'),strong=document.createElement('strong'),small=document.createElement('small');
  strong.textContent=title;small.textContent=detail;info.append(strong,small);item.append(info);
  const buttons=document.createElement('div');buttons.className='list-actions';
  for(const [label,callback,danger] of actions){const button=document.createElement('button');button.type='button';button.textContent=label;button.className=danger?'danger':'secondary';button.onclick=async()=>{button.disabled=true;try{await callback()}catch(e){message(e.message,true);switchView('compose')}finally{button.disabled=false}};buttons.append(button)}
  item.append(buttons);return item;
}
async function loadNotes(){
  const list=$('saved-list');list.textContent='Laden…';
  try{const items=(await api('notes')).items;list.replaceChildren();if(!items.length){list.textContent='Nog geen opgeslagen notities.';return}
    for(const item of items)list.append(row(item.title,new Date(item.updated_at).toLocaleString('nl-NL'),[
      ['Open',async()=>{const detail=await api('notes/'+item.id);applyNote(detail.item.payload);currentNoteId=item.id;switchView('compose');message('Notitie geopend.')}],
      ['Verwijder',async()=>{await api('notes/'+item.id,{method:'DELETE'});if(currentNoteId===item.id)currentNoteId=null;loadNotes()},true]
    ]));
  }catch(e){list.textContent=e.message}
}
async function loadHistory(){
  const list=$('history-list');list.textContent='Laden…';
  try{const items=(await api('history')).items;list.replaceChildren();if(!items.length){list.textContent='Er zijn nog geen afdrukken.';return}
    for(const item of items)list.append(row(item.title,(item.status==='sent'?'Verzonden':'Mislukt')+' · '+new Date(item.created_at).toLocaleString('nl-NL')+' · '+item.detail,[
      ['Opnieuw printen',async()=>{await api('history/'+item.id+'/reprint',{method:'POST'});loadHistory();refreshStatus()}],
      ['Open',async()=>{const detail=await api('history/'+item.id);applyNote(detail.item.payload);currentNoteId=null;switchView('compose');message('Eerdere afdruk geopend.')}],
      ['Verwijder',async()=>{await api('history/'+item.id,{method:'DELETE'});loadHistory()},true]
    ]));
  }catch(e){list.textContent=e.message}
}
async function refreshStatus(){
  try{const result=await api('status');$('status').textContent=result.message+(result.model?' · '+result.model:'');$('status').className='status'+(result.connected?' good':'')}
  catch{$('status').textContent='Printerstatus niet beschikbaar';$('status').className='status'}
}
async function loadPrinter(){
  const details=$('printer-details'),list=$('job-list');details.textContent='Printerstatus laden…';list.replaceChildren();
  try{const state=await api('printer');details.textContent=(state.connected?'Verbonden: DYMO LabelWriter '+state.model:state.error)+' · '+state.state;
    if(!state.jobs.length){list.textContent='Geen afdrukken in de wachtrij.';return}
    for(const job of state.jobs){const id=job.split(/\s+/)[0];list.append(row(id,job,[['Annuleer',async()=>{await api('printer/cancel',{method:'POST',body:JSON.stringify({job:id})});loadPrinter()}]]))}
  }catch(e){details.textContent=e.message;list.textContent='Wachtrij niet beschikbaar.'}
}
async function copyShortcut(){const input=$('shortcut-url');try{await navigator.clipboard.writeText(input.value)}catch{input.select();document.execCommand('copy')}message('URL gekopieerd. Plak hem in Siri Opdrachten.');switchView('compose')}
function importShortcut(){
  const params=new URLSearchParams(location.search);if(!params.has('text')&&!params.has('title'))return;
  const kind=params.get('template')||'';if(presets[kind])applyBuiltin(kind);
  if(params.has('text'))$('body').value=(params.get('text')||'').slice(0,2500);
  if(params.has('title'))$('title').value=(params.get('title')||'').slice(0,80);
  history.replaceState({},'',location.pathname);update();message('Tekst uit je iPhone-snelkoppeling ingevuld. Bekijk het label en druk op Print.');
}
function start(){
  for(const id of fields)$(id).addEventListener('input',update);
  $('custom-layout').addEventListener('change',()=>{activeTemplate=$('custom-layout').value;update()});
  $('apply-template').addEventListener('click',applySelectedTemplate);
  $('save-template').addEventListener('click',()=>saveTemplate(false));$('save-as-template').addEventListener('click',()=>saveTemplate(true));$('delete-template').addEventListener('click',deleteTemplate);
  $('save-note').addEventListener('click',saveNote);$('new-note').addEventListener('click',resetNote);
  $('preview-pdf').addEventListener('click',previewPdf);
  $('form').addEventListener('submit',event=>{event.preventDefault();printNote()});
  $('photo').addEventListener('change',event=>compressPhoto(event.target.files[0]));
  $('clear-photo').addEventListener('click',()=>{photoData='';$('photo').value='';$('clear-photo').hidden=true;update()});
  for(const button of document.querySelectorAll('.tab'))button.addEventListener('click',()=>switchView(button.dataset.view));
  for(const button of document.querySelectorAll('.refresh'))button.addEventListener('click',()=>switchView(button.dataset.refresh));
  $('shortcut-url').value=location.origin+location.pathname+'?text=';
  $('copy-shortcut').addEventListener('click',copyShortcut);
  loadTemplates().catch(e=>message(e.message,true));refreshStatus();setInterval(refreshStatus,15000);
  importShortcut();update();
}
start();
