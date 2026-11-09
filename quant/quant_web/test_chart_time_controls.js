const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const context = {console};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'static/chart_time_controls.js'),'utf8'), context);
const normalized = value => JSON.parse(JSON.stringify(value));
assert.strictEqual(context.chartDateISO('1027'), '2026-10-27');
assert.strictEqual(context.chartDateISO('20261027'), '2026-10-27');
assert.strictEqual(context.chartDateISO('2027/01/04'), '2027-01-04');
assert.strictEqual(context.chartDateISO('2026-02-29'), null);
assert.strictEqual(context.chartDateISO('T+5'), null);
assert.deepStrictEqual(normalized(context.chartPresetBounds('month','2026-03-31','2026-01-01')), ['2026-02-28','2026-03-31']);
assert.deepStrictEqual(normalized(context.chartPresetBounds('year','2024-02-29','2023-01-01')), ['2023-02-28','2024-02-29']);
assert.deepStrictEqual(normalized(context.chartPresetBounds('quarter','2026-10-28','2026-01-01')), ['2026-07-28','2026-10-28']);
assert.deepStrictEqual(normalized(context.chartPresetBounds('day','2026-10-28','2026-01-01')), ['2026-10-28','2026-10-28']);
assert.deepStrictEqual(normalized(context.chartPresetBounds('all','2026-10-28','2026-01-01')), ['2026-01-01','2026-10-28']);
const dates = ['2026-10-23','2026-10-26','2026-10-27'];
assert.deepStrictEqual(normalized(context.chartRangeIndices(dates,'2026-10-24','2026-10-27')), [1,2]);
assert.strictEqual(context.chartZoomBoundIndex(null,50,dates),1);
assert.strictEqual(context.chartZoomBoundIndex('2026/10/27',0,dates),2);
assert.strictEqual(context.chartZoomBoundIndex(0,50,dates),0);
assert.strictEqual(context.chartRangeIndices(dates,'2026-10-28','2026-10-28'), null);
assert.strictEqual(context.chartRangeIndices(dates,'2026-10-24','2026-10-25'), null);
assert.deepStrictEqual(normalized(context.chartRangeIndices(dates,'2026-01-01','2027-01-01')), [0,2]);
// Short states are expressed in native category coordinates, not fixed pixels.
vm.runInContext(fs.readFileSync(path.join(__dirname,'static/charts.js'),'utf8'), context);
let option;
context.applyShortPositionBackground({setOption: value => {option=value;}}, [
 {date:'04/01',futures_position:'做空80%'},{date:'04/02',futures_position:'做多50%'},
 {date:'04/03',futures_position:'做空80%'},{date:'04/04',futures_position:'做多50%'}
]);
assert.deepStrictEqual(normalized(option.series[0].markLine.data), [
 {xAxis:'04/01'},{xAxis:'04/03'}
]);
console.log('time window, leap year, empty-day, and native zoom shading tests passed');
