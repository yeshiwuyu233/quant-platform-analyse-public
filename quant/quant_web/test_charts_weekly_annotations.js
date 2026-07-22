const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync('/var/www/quant/quant_web/static/charts.js', 'utf8');
const options = [];
const context = {
  console,
  window: { addEventListener: () => {} },
  document: { getElementById: () => null },
  echarts: { init: () => ({ setOption: (option) => { options.push(option); }, resize: () => {} }), graphic: {} }
};
vm.createContext(context);
vm.runInContext(source, context);

assert.strictEqual(typeof context.buildLowGt1CountRanges, 'function');

const ranges = context.buildLowGt1CountRanges([
  { date: '05/13', gt1_count: 63 },
  { date: '05/14', gt1_count: 23 },
  { date: '05/15', gt1_count: 19 },
  { date: '05/18', gt1_count: 61 },
  { date: '05/19', gt1_count: 58 },
  { date: '05/20', gt1_count: 57 },
], 60);

assert.deepStrictEqual(JSON.parse(JSON.stringify(ranges)), [
  { start: '05/14', end: '05/15', label: '05/14-05/15 指标>1数量<60' },
  { start: '05/19', end: '05/20', label: '05/19-05/20 指标>1数量<60' },
]);

context.document.getElementById = () => ({});
const weeklyRecord = {
  date: '04/01',
  gt1_count: 80,
  top_nav: 1,
  filtered_top_nav: 1,
  long_short_top_nav: 1,
  cold_nav: 1,
  standard_nav: 1,
  csi1000_nav: 1,
  top_drawdown: 0,
  filtered_top_drawdown: 0,
  long_short_top_drawdown: 0,
  cold_drawdown: -1,
  standard_drawdown: -2,
  csi1000_drawdown: -3,
};
context.renderWeeklyStrategyNav('nav', [weeklyRecord]);
context.renderWeeklyStrategyDrawdown('drawdown', [
  weeklyRecord
]);

const navOption = options[0];
const drawdownOption = options[1];
assert.deepStrictEqual(navOption.legend.data, drawdownOption.legend.data);
assert.deepStrictEqual(navOption.color, drawdownOption.color);

for (let i = 0; i < navOption.series.length; i += 1) {
  const navSeries = navOption.series[i];
  const drawdownSeries = drawdownOption.series[i];
  assert.strictEqual(navSeries.name, drawdownSeries.name);
  assert.strictEqual(navSeries.color, drawdownSeries.color, `${navSeries.name} series colors should match`);
  assert.strictEqual(navSeries.lineStyle.color, drawdownSeries.lineStyle.color, `${navSeries.name} line colors should match`);
  assert.strictEqual(navSeries.itemStyle.color, navSeries.lineStyle.color, `${navSeries.name} nav marker color should match line color`);
  assert.strictEqual(drawdownSeries.itemStyle.color, drawdownSeries.lineStyle.color, `${drawdownSeries.name} drawdown marker color should match line color`);
}

console.log('weekly annotation tests passed');
