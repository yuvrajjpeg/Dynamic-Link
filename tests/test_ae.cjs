// Simulate AE's host API to exercise template selection and footage trim setup.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.join(__dirname, '../resolve_ae');
const companion = fs.readFileSync(path.join(root, 'Resolve AE Bridge.jsx'), 'utf8');
const create = fs.readFileSync(path.join(root, 'create_composition.jsx'), 'utf8');

function host(templates = ['High Quality']) {
  const events = {removed:0, alerts:[], files:[]};
  const layer = {};
  const output = {
    templates,
    applyTemplate(name) { events.selected = name; },
    getSettings() { return {Format:'QuickTime'}; },
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
