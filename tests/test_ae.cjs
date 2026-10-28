// Simulate AE's host API to exercise template selection and footage trim setup.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.join(__dirname, '../resolve_ae');
const companion = fs.readFileSync(path.join(root, 'Resolve AE Bridge.jsx'), 'utf8');
const create = fs.readFileSync(path.join(root, 'create_composition.jsx'), 'utf8');

function host(templates = ['High Quality'], format = 'QuickTime') {
  const events = {removed:0, alerts:[], files:[]};
  const layer = {};
  const output = {
    templates,
    applyTemplate(name) { events.selected = name; },
    getSettings() { return {Format:format}; },
    saveAsTemplate(name) { events.template = name; }
  };
  const project = {
    numItems:0, file:null,
    items:{addComp(...args) { events.comp = args; return {layers:{add(){return layer;}}, remove(){events.removed++;}, openInViewer(){}}; }},
    renderQueue:{items:{add(){return {outputModule(){return output;},remove(){events.removed++;}};}}},
    importFile(options){ events.source = options.file.path; return {hasVideo:true, width:1920,height:1080,pixelAspect:1}; },
    save(file){events.saved = file.path;}
  };
  const context = {
    $:{_resolveBridgeHeadless:true},
    app:{project,newProject(){},preferences:{saveToDisk(){events.preferencesSaved=true;}}},
    GetSettingsFormat:{STRING:1},CloseOptions:{PROMPT_TO_SAVE_CHANGES:1},
    ImportOptions:function(file){this.file=file;},
    File:function(p){this.path=p;this.open=()=>true;this.write=text=>events.files.push([p,text]);this.close=()=>{};},
    alert(message){events.alerts.push(message);}
  };
  vm.createContext(context);
  vm.runInContext(companion, context);
  return {context,events,layer};
}

test('compatible preset automatically creates persistent bridge template and cleans temporary items',()=>{
  const {context,events}=host();
  context.ResolveAEBridge.ensureOutputTemplate('Resolve Bridge ProRes');
  assert.equal(events.template,'Resolve Bridge ProRes');
  assert.equal(events.removed,2);
  assert.equal(events.preferencesSaved,true);
});
test('missing preset fails with actionable error and cleans temporary items',()=>{
  const {context,events}=host([]);
  assert.throws(()=>context.ResolveAEBridge.ensureOutputTemplate('Bridge'),/No compatible/);
  assert.equal(events.removed,2);
});
test('handoff imports exact source, applies trim, saves generated AEP and signals ready',()=>{
  const {context,events,layer}=host();
  const job={source:'/shots/clip with spaces.mov',comp:'Linked shot',fps:24,frames:48,offset:72,aep:'/jobs/shot/Composition.aep',directory:'/jobs/shot',id:'shot'};
  vm.runInContext(create.replace('/*BRIDGE_JOB*/null',JSON.stringify(job)),context);
  assert.equal(events.source,job.source);
  assert.equal(layer.startTime,-3);
  assert.equal(layer.outPoint,2);
  assert.equal(events.saved,job.aep);
  assert.deepEqual(events.files,[['/jobs/shot/ae-ready.txt','ready']]);
  assert.deepEqual(events.alerts,[]);
});

function renderHost(status = 'DONE', format = 'QuickTime') {
  const h = host();
  const {context, events} = h;
  const files = {};
  const job = {comp:'Linked shot', fps:24, frames:48, directory:'/jobs/shot'};
  context.File = function(p) {
    this.fsName = p; this.exists = true; this.length = 20;
    this.open = () => true; this.close = () => {};
    this.read = () => JSON.stringify(job);
    this.write = text => { files[p] = text; };
  };
  context.CompItem = function() {};
  const comp = new context.CompItem();
  Object.assign(comp, {name:job.comp, frameRate:24, duration:2});
  const parked = {status:'QUEUED', render:true};
  const item = {outputModule:()=>({applyTemplate(){}, getSettings:()=>({Format:format}), set file(v){events.output=v;}}), remove(){events.queueRemoved=true;}};
  context.RQItemStatus = {QUEUED:'QUEUED', DONE:'DONE'};
  Object.assign(context.app.project, {
    file:{parent:{fsName:job.directory}}, numItems:1, item:()=>comp,
    save(){events.saved=true;},
    renderQueue:{numItems:1, item:()=>parked, items:{add:()=>item}, render(){item.status=status;}}
  });
  // The helper temporarily creates its own queue item before the actual render.
  let calls = 0;
  context.app.project.renderQueue.items.add = () => {
    if (calls++ === 0) return {outputModule:()=>({templates:['Resolve Bridge ProRes'], applyTemplate(){},
      getSettings:()=>({Format:format}), saveAsTemplate(){}}), remove(){}};
    return item;
  };
  return {...h, files, item, parked, comp};
}

test('render forces full linked duration and restores parked queue',()=>{
  const h = renderHost();
  h.context.ResolveAEBridge.renderForResolve();
  assert.equal(h.item.timeSpanStart,0);
  assert.equal(h.item.timeSpanDuration,2);
  assert.equal(h.parked.render,true);
  assert.ok(h.files['/jobs/shot/latest-render.txt']);
});
test('cancelled render never publishes a partial movie and restores queue',()=>{
  const h = renderHost('USER_STOPPED');
  assert.throws(()=>h.context.ResolveAEBridge.renderForResolve(),/stopped or failed/);
  assert.equal(h.files['/jobs/shot/latest-render.txt'],undefined);
  assert.equal(h.parked.render,true);
  assert.equal(h.events.queueRemoved,true);
});
test('changed composition timing is refused before rendering',()=>{
  const h = renderHost(); h.comp.frameRate=30;
  assert.throws(()=>h.context.ResolveAEBridge.renderForResolve(),/original frame rate/);
  assert.equal(h.events.saved,undefined);
});
test('manual handoff succeeds without any compatible output presets',()=>{
  const h = host([]);
  const job={source:'/clip.mov',comp:'Shot',fps:24,frames:48,offset:0,aep:'/jobs/Composition.aep',directory:'/jobs',id:'shot'};
  vm.runInContext(create.replace('/*BRIDGE_JOB*/null',JSON.stringify(job)),h.context);
  assert.equal(h.events.saved,job.aep);
});


test('manual Windows render accepts AVI and publishes matching extension',()=>{
  const h = renderHost('DONE', 'AVI');
  h.context.ResolveAEBridge.renderForResolve();
  assert.match(h.files['/jobs/shot/latest-render.txt'], /\.avi$/);
});
test('background MOV workflow continues to reject AVI templates',()=>{
  const h = host(['Lossless'], 'AVI');
  assert.throws(()=>h.context.ResolveAEBridge.ensureOutputTemplate('Bridge'), /No compatible/);
});
test('Windows pending handoff uses USERPROFILE even with OneDrive Documents',()=>{
  const h = host(); const paths = [];
  h.context.$.os = 'Windows';
  h.context.$.getenv = name => name === 'USERPROFILE' ? 'C:/Users/Editor' : '';
  h.context.Folder = {myDocuments:{parent:{fsName:'C:/Users/Editor/OneDrive'}}};
  h.context.File = function(p) { paths.push(p); this.exists=false; };
  assert.throws(()=>h.context.ResolveAEBridge.openFromResolve(), /Nothing to open/);
  assert.equal(paths[0], 'C:/Users/Editor/Videos/Resolve AE Bridge/pending-handoff.txt');
});
