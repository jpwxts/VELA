const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('app/static/js/activity-workspace.js','utf8');
test('workspace preserves gaps and measured zero and uses stored period totals',()=>{
 const context=vm.createContext({});
 vm.runInContext(source.slice(source.indexOf('function workspacePercent'),source.indexOf('function renderWorkspaceChart')),context);
 assert.equal(context.workspacePercent(null),'Activity estimate unavailable');
 assert.equal(context.workspacePercent(0),'0.0%');
 assert.equal(context.workspacePercent(21/309),'6.8%');
 const payload={days:[{activity_rate:21/309}],weeks:[{activity_rate:7/761}],months:[{activity_rate:28/1209}]};
 assert.equal(context.workspaceRows(payload,'month')[0].activity_rate,28/1209);
 assert.equal(context.workspaceRows(payload,'week')[0].activity_rate,7/761);
});
