/* ── 行业分布柱状图 ──────────────────── */
function renderIndustryBar(domId, data) {
    const el = document.getElementById(domId);
    if (!el) return;
    const chart = echarts.init(el, 'dark');
    const names = data.map(r => r['行业名称'] || r['行业'] || '');
    const counts = data.map(r => r['入选数量'] || 0);
    chart.setOption({
        tooltip: { trigger: 'axis' },
        grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
        xAxis: { type: 'category', data: names, axisLabel: { rotate: 45, fontSize: 11 } },
        yAxis: { type: 'value' },
        series: [{
            type: 'bar',
            data: counts,
            itemStyle: {
                borderRadius: [4,4,0,0],
                color: new echarts.graphic.LinearGradient(0,0,0,1, [
                    { offset: 0, color: '#0d6efd' },
                    { offset: 1, color: '#0a58ca' }
                ])
            }
        }]
    });
    window.addEventListener('resize', () => chart.resize());
}

/* ── 行业热度饼图 ────────────────────── */
function renderIndustryPie(domId, data) {
    const el = document.getElementById(domId);
    if (!el) return;
    const chart = echarts.init(el, 'dark');
    const pieData = data.map(r => ({
        name: r['当日热门行业'] || r['行业名称'] || '',
        value: r['今日符合数'] || r['入选数量'] || 0
    }));
    chart.setOption({
        tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
        series: [{
            type: 'pie',
            radius: ['35%', '65%'],
            center: ['50%', '50%'],
            label: { show: true, formatter: '{b}\n{d}%', fontSize: 11 },
            data: pieData,
            emphasis: {
                label: { show: true, fontSize: 14, fontWeight: 'bold' }
            }
        }]
    });
    window.addEventListener('resize', () => chart.resize());
}

/* ── 胜率趋势折线图 ──────────────────── */
function renderWinRateTrend(domId, records) {
    const el = document.getElementById(domId);
    if (!el) return;
    const chart = echarts.init(el, 'dark');
    const dates = records.map(r => r.date);
    chart.setOption({
        tooltip: { trigger: 'axis' },
        legend: { data: ['指标>0.8', '指标>1.2', '全样本'], top: 0 },
        grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
        xAxis: { type: 'category', data: dates, axisLabel: { rotate: 30 } },
        yAxis: { type: 'value', axisLabel: { formatter: '{value}%' }, min: 0 },
        series: [
            {
                name: '指标>0.8',
                type: 'line',
                data: records.map(r => r.acc_08),
                smooth: true,
                symbol: 'circle',
                symbolSize: 6,
                lineStyle: { width: 2 },
                itemStyle: { color: '#0d6efd' }
            },
            {
                name: '指标>1.2',
                type: 'line',
                data: records.map(r => r.acc_12),
                smooth: true,
                symbol: 'diamond',
                symbolSize: 6,
                lineStyle: { width: 2 },
                itemStyle: { color: '#ffc107' }
            },
            {
                name: '全样本',
                type: 'line',
                data: records.map(r => r.all_pct),
                smooth: true,
                symbol: 'triangle',
                symbolSize: 6,
                lineStyle: { width: 2 },
                itemStyle: { color: '#198754' }
            }
        ]
    });
    window.addEventListener('resize', () => chart.resize());
}

/* ── Alpha 趋势 ──────────────────────── */
function renderAlphaTrend(domId, records) {
    const el = document.getElementById(domId);
    if (!el) return;
    const chart = echarts.init(el, 'dark');
    const dates = records.map(r => r.date);
    chart.setOption({
        tooltip: { trigger: 'axis' },
        grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
        xAxis: { type: 'category', data: dates, axisLabel: { rotate: 30 } },
        yAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
        series: [{
            type: 'line',
            data: records.map(r => r.cold_alpha),
            smooth: true,
            symbol: 'circle',
            symbolSize: 6,
            lineStyle: { width: 2, color: '#dc3545' },
            areaStyle: {
                color: new echarts.graphic.LinearGradient(0,0,0,1, [
                    { offset: 0, color: 'rgba(220,53,69,0.3)' },
                    { offset: 1, color: 'rgba(220,53,69,0.02)' }
                ])
            }
        }]
    });
    window.addEventListener('resize', () => chart.resize());
}

/* ── 下一日达标数 ────────────────────── */
function renderNextDayTrend(domId, records) {
    const el = document.getElementById(domId);
    if (!el) return;
    const chart = echarts.init(el, 'dark');
    const dates = records.map(r => r.date);
    chart.setOption({
        tooltip: { trigger: 'axis' },
        grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
        xAxis: { type: 'category', data: dates, axisLabel: { rotate: 30 } },
        yAxis: { type: 'value', minInterval: 1 },
        series: [{
            type: 'bar',
            data: records.map(r => r.next_10),
            itemStyle: {
                borderRadius: [4,4,0,0],
                color: new echarts.graphic.LinearGradient(0,0,0,1, [
                    { offset: 0, color: '#0d6efd' },
                    { offset: 1, color: '#0a58ca' }
                ])
            }
        }]
    });
    window.addEventListener('resize', () => chart.resize());
}

function buildLowGt1CountRanges(records, minCount = 60) {
    const ranges = [];
    let start = null;
    let end = null;

    (records || []).forEach(r => {
        const count = Number(r.gt1_count || 0);
        if (count < minCount) {
            if (!start) start = r.date;
            end = r.date;
            return;
        }
        if (start) {
            ranges.push({
                start,
                end,
                label: start === end
                    ? `${start} 指标>1数量<${minCount}`
                    : `${start}-${end} 指标>1数量<${minCount}`
            });
            start = null;
            end = null;
        }
    });

    if (start) {
        ranges.push({
            start,
            end,
            label: start === end
                ? `${start} 指标>1数量<${minCount}`
                : `${start}-${end} 指标>1数量<${minCount}`
        });
    }
    return ranges;
}

function lowGt1CountMarkArea(records, minCount = 60) {
    const ranges = buildLowGt1CountRanges(records, minCount);
    if (!ranges.length) return undefined;
    return {
        silent: true,
        itemStyle: { color: 'rgba(220,53,69,0.12)' },
        label: { show: true, color: '#f8d7da', fontSize: 10, formatter: '<60' },
        data: ranges.map(r => [{ xAxis: r.start }, { xAxis: r.end }])
    };
}

function renderLowGt1CountRanges(domId, records, minCount = 60) {
    const el = document.getElementById(domId);
    if (!el) return;
    const ranges = buildLowGt1CountRanges(records, minCount);
    if (!ranges.length) {
        el.innerHTML = '<span class="text-secondary">没有出现指标&gt;1数量低于60的区间。</span>';
        return;
    }
    el.innerHTML = ranges
        .map(r => `<span class="badge text-bg-danger me-2 mb-2">${r.label}</span>`)
        .join('');
}

const WEEKLY_TIMING_FUTURES_LABEL = '>=60持有80%前三行业+20%做多中证1000股指期货\n<60持有20%做空中证1000股指期货(5倍)';
const WEEKLY_STRATEGY_SERIES = [
    {
        name: '前三行业',
        color: '#0d6efd',
        symbol: 'circle',
        symbolSize: 5,
        width: 2,
        navKey: 'top_nav',
        drawdownKey: 'top_drawdown',
        areaColor: 'rgba(13,110,253,0.16)',
        markLowGt1: true
    },
    {
        name: '前三行业(指标>1数量>=60)',
        color: '#20c997',
        symbol: 'diamond',
        symbolSize: 6,
        width: 3,
        navKey: 'filtered_top_nav',
        drawdownKey: 'filtered_top_drawdown',
        areaColor: 'rgba(32,201,151,0.14)'
    },
    {
        name: WEEKLY_TIMING_FUTURES_LABEL,
        color: '#6f42c1',
        symbol: 'none',
        width: 2,
        navKey: 'long_short_top_nav',
        drawdownKey: 'long_short_top_drawdown'
    },
    {
        name: '冷门行业',
        color: '#ffc107',
        symbol: 'triangle',
        symbolSize: 6,
        width: 2,
        navKey: 'cold_nav',
        drawdownKey: 'cold_drawdown',
        areaColor: 'rgba(255,193,7,0.12)'
    },
    {
        name: '标准>1',
        color: '#adb5bd',
        symbol: 'rect',
        symbolSize: 5,
        width: 2,
        navKey: 'standard_nav',
        drawdownKey: 'standard_drawdown'
    },
    {
        name: '中证1000',
        color: '#dc3545',
        symbol: 'none',
        width: 2,
        navKey: 'csi1000_nav',
        drawdownKey: 'csi1000_drawdown'
    }
];

function weeklyStrategyLegendNames() {
    return WEEKLY_STRATEGY_SERIES.map(s => s.name);
}

function weeklyStrategyPalette() {
    return WEEKLY_STRATEGY_SERIES.map(s => s.color);
}

function buildWeeklyStrategySeries(records, valueKey, weakGt1MarkArea, includeArea) {
    return WEEKLY_STRATEGY_SERIES.map(config => {
        const series = {
            name: config.name,
            type: 'line',
            color: config.color,
            data: records.map(r => r[config[valueKey]]),
            smooth: true,
            symbol: config.symbol,
            lineStyle: { width: config.width, color: config.color },
            itemStyle: { color: config.color },
            emphasis: { itemStyle: { color: config.color }, lineStyle: { color: config.color } }
        };
        if (config.symbolSize) series.symbolSize = config.symbolSize;
        if (includeArea && config.areaColor) series.areaStyle = { color: config.areaColor };
        if (config.markLowGt1) series.markArea = weakGt1MarkArea;
        return series;
    });
}

/* ── 礼拜攻势历史净值 ─────────────────── */
function renderWeeklyStrategyNav(domId, records) {
    const el = document.getElementById(domId);
    if (!el || !records || !records.length) return;
    const chart = echarts.init(el, 'dark');
    const dates = records.map(r => r.date);
    const weakGt1MarkArea = lowGt1CountMarkArea(records, 60);
    chart.setOption({
        color: weeklyStrategyPalette(),
        tooltip: {
            trigger: 'axis',
            valueFormatter: v => Number(v).toFixed(3)
        },
        legend: {
            data: weeklyStrategyLegendNames(),
            top: 0
        },
        grid: { left: '3%', right: '4%', top: 74, bottom: '3%', containLabel: true },
        xAxis: { type: 'category', data: dates, axisLabel: { rotate: 30 } },
        yAxis: { type: 'value', min: 'dataMin' },
        series: buildWeeklyStrategySeries(records, 'navKey', weakGt1MarkArea, false)
    });
    window.addEventListener('resize', () => chart.resize());
}

/* ── 礼拜攻势回撤 ───────────────────── */
function renderWeeklyStrategyDrawdown(domId, records) {
    const el = document.getElementById(domId);
    if (!el || !records || !records.length) return;
    const chart = echarts.init(el, 'dark');
    const dates = records.map(r => r.date);
    const weakGt1MarkArea = lowGt1CountMarkArea(records, 60);
    chart.setOption({
        color: weeklyStrategyPalette(),
        tooltip: {
            trigger: 'axis',
            valueFormatter: v => Number(v).toFixed(2) + '%'
        },
        legend: {
            data: weeklyStrategyLegendNames(),
            top: 0
        },
        grid: { left: '3%', right: '4%', top: 74, bottom: '3%', containLabel: true },
        xAxis: { type: 'category', data: dates, axisLabel: { rotate: 30 } },
        yAxis: { type: 'value', max: 0, axisLabel: { formatter: '{value}%' } },
        series: buildWeeklyStrategySeries(records, 'drawdownKey', weakGt1MarkArea, true)
    });
    window.addEventListener('resize', () => chart.resize());
}

/* ── 礼拜攻势策略分组透析图 ──────────── */
function renderWeeklySummary(domId, data) {
    try {
        console.log('[weeklyChart] rendering', domId, 'data:', data?.length, 'rows');
        const el = document.getElementById(domId);
        if (!el) { console.warn('[weeklyChart] element not found:', domId); return; }
        if (typeof echarts === 'undefined') { console.error('[weeklyChart] echarts not loaded!'); return; }
        const chart = echarts.init(el, 'dark');
        const groups = data.map(r => r['策略分组']);
        const avgReturns = data.map(r => {
            const v = parseFloat(r['平均持仓回报']);
            return isNaN(v) ? 0 : v;
        });
        const winRates = data.map(r => {
            const v = parseFloat(r['策略胜率(>0%)']);
            return isNaN(v) ? 0 : v;
        });
        const stockCounts = data.map(r => {
            const v = parseInt(r['入选股票数']);
            return isNaN(v) ? 0 : v;
        });

        chart.setOption({
            tooltip: {
                trigger: 'axis',
                axisPointer: { type: 'shadow' }
            },
            legend: {
                data: ['平均持仓回报', '策略胜率', '入选股票数'],
                top: 0
            },
            grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
            xAxis: {
                type: 'category',
                data: groups,
                axisLabel: { fontWeight: 'bold' }
            },
            yAxis: [
                {
                    type: 'value',
                    name: '回报 / 胜率 (%)',
                    nameTextStyle: { fontSize: 11 }
                },
                {
                    type: 'value',
                    name: '股票数',
                    nameTextStyle: { fontSize: 11 },
                    minInterval: 1
                }
            ],
            series: [
                {
                    name: '平均持仓回报',
                    type: 'bar',
                    data: avgReturns,
                    itemStyle: {
                        borderRadius: [4,4,0,0],
                        color: new echarts.graphic.LinearGradient(0,0,0,1, [
                            { offset: 0, color: '#0d6efd' },
                            { offset: 1, color: '#0a58ca' }
                        ])
                    },
                    label: {
                        show: true,
                        position: 'top',
                        formatter: '{c}%',
                        fontSize: 11,
                        fontWeight: 'bold'
                    }
                },
                {
                    name: '策略胜率',
                    type: 'bar',
                    data: winRates,
                    itemStyle: {
                        borderRadius: [4,4,0,0],
                        color: new echarts.graphic.LinearGradient(0,0,0,1, [
                            { offset: 0, color: '#198754' },
                            { offset: 1, color: '#157347' }
                        ])
                    },
                    label: {
                        show: true,
                        position: 'top',
                        formatter: '{c}%',
                        fontSize: 11,
                        fontWeight: 'bold'
                    }
                },
                {
                    name: '入选股票数',
                    type: 'line',
                    yAxisIndex: 1,
                    data: stockCounts,
                    smooth: true,
                    symbol: 'diamond',
                    symbolSize: 10,
                    lineStyle: { width: 2, color: '#ffc107' },
                    itemStyle: { color: '#ffc107' },
                    label: {
                        show: true,
                        position: 'top',
                        formatter: '{c}',
                        fontSize: 11,
                        fontWeight: 'bold'
                    }
                }
            ]
        });
        window.addEventListener('resize', () => chart.resize());
        console.log('[weeklyChart] rendered successfully');
    } catch(e) {
        console.error('[weeklyChart] render error:', e.message, e.stack);
        const el = document.getElementById(domId);
        if (el) el.innerHTML = '<div style="color:#dc3545;padding:40px;text-align:center;">⚠️ 图表渲染失败: ' + e.message + '</div>';
    }
}

/* ── 礼拜攻势胜率趋势 ─────────────────── */
function renderWeeklyWinRateTrend(domId, records) {
    try {
        console.log('[weeklyWinRate] rendering', domId, 'records:', records?.length);
        const el = document.getElementById(domId);
        if (!el) { console.warn('[weeklyWinRate] element not found:', domId); return; }
        if (typeof echarts === 'undefined') { console.error('[weeklyWinRate] echarts not loaded!'); return; }
        const chart = echarts.init(el, 'dark');
        const dates = records.map(r => r.date);
        const groups = ['gt_0_8', 'gt_1_0', 'gt_1_2'];
        const labels = ['指标>0.8', '指标>1.0', '指标>1.2'];
        const colors = ['#0d6efd', '#ffc107', '#198754'];
        const symbols = ['circle', 'diamond', 'triangle'];

        chart.setOption({
            tooltip: {
                trigger: 'axis',
                formatter: function(params) {
                    let s = params[0].axisValue;
                    params.forEach(p => {
                        s += '<br/>' + p.marker + ' ' + p.seriesName + ': ' + p.value + '%';
                    });
                    return s;
                }
            },
            legend: { data: labels, top: 0 },
            grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
            xAxis: { type: 'category', data: dates, axisLabel: { rotate: 30 } },
            yAxis: {
                type: 'value',
                axisLabel: { formatter: '{value}%' },
                min: function(value) {
                    return Math.max(0, Math.floor(value.min - 5));
                }
            },
            series: groups.map((g, i) => ({
                name: labels[i],
                type: 'line',
                data: records.map(r => r[g + '_胜率']),
                smooth: true,
                symbol: symbols[i],
                symbolSize: 6,
                lineStyle: { width: 2, color: colors[i] },
                itemStyle: { color: colors[i] }
            }))
        });
        window.addEventListener('resize', () => chart.resize());
        console.log('[weeklyWinRate] rendered successfully');
    } catch(e) {
        console.error('[weeklyWinRate] render error:', e.message, e.stack);
        const el = document.getElementById(domId);
        if (el) el.innerHTML = '<div style="color:#dc3545;padding:40px;text-align:center;">⚠️ 图表渲染失败: ' + e.message + '</div>';
    }
}

/* ── 礼拜攻势平均回报趋势 ─────────────── */
function renderWeeklyReturnTrend(domId, records) {
    try {
        console.log('[weeklyReturn] rendering', domId, 'records:', records?.length);
        const el = document.getElementById(domId);
        if (!el) { console.warn('[weeklyReturn] element not found:', domId); return; }
        if (typeof echarts === 'undefined') { console.error('[weeklyReturn] echarts not loaded!'); return; }
        const chart = echarts.init(el, 'dark');
        const dates = records.map(r => r.date);
        const groups = ['gt_0_8', 'gt_1_0', 'gt_1_2'];
        const labels = ['指标>0.8', '指标>1.0', '指标>1.2'];
        const colors = ['#0d6efd', '#ffc107', '#198754'];
        const symbols = ['circle', 'diamond', 'triangle'];

        chart.setOption({
            tooltip: {
                trigger: 'axis',
                formatter: function(params) {
                    let s = params[0].axisValue;
                    params.forEach(p => {
                        s += '<br/>' + p.marker + ' ' + p.seriesName + ': ' + p.value + '%';
                    });
                    return s;
                }
            },
            legend: { data: labels, top: 0 },
            grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
            xAxis: { type: 'category', data: dates, axisLabel: { rotate: 30 } },
            yAxis: {
                type: 'value',
                axisLabel: { formatter: '{value}%' },
                axisLine: { onZero: false }
            },
            series: groups.map((g, i) => ({
                name: labels[i],
                type: 'line',
                data: records.map(r => r[g + '_回报']),
                smooth: true,
                symbol: symbols[i],
                symbolSize: 6,
                lineStyle: { width: 2, color: colors[i] },
                itemStyle: { color: colors[i] },
                areaStyle: {
                    color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                        { offset: 0, color: colors[i] + '33' },
                        { offset: 1, color: colors[i] + '05' }
                    ])
                }
            }))
        });
        window.addEventListener('resize', () => chart.resize());
        console.log('[weeklyReturn] rendered successfully');
    } catch(e) {
        console.error('[weeklyReturn] render error:', e.message, e.stack);
        const el = document.getElementById(domId);
        if (el) el.innerHTML = '<div style="color:#dc3545;padding:40px;text-align:center;">⚠️ 图表渲染失败: ' + e.message + '</div>';
    }
}

/* ── 5日生命周期轨迹图 ─────────────────── */
function renderWeeklyTrajectory(domId, summaryRows) {
    try {
        var el = document.getElementById(domId);
        if (!el) return;

        // 取可用天数（每组一致）
        var nAvail = summaryRows[0] ? (summaryRows[0]['可用天数'] || 0) : 0;
        if (nAvail === 0) {
            el.innerHTML = '<div style="color:#888;padding:60px;text-align:center;font-size:15px;">⏳ 暂无结算数据（后续交易日尚未到来），待有新数据后自动更新</div>';
            return;
        }

        var allLabels = ['T+1', 'T+2', 'T+3', 'T+4', 'T+5'];
        var labels = allLabels.slice(0, nAvail);
        var colors = ['#0d6efd', '#ffc107', '#198754'];
        var lineStyles = ['solid', 'dashed', 'dotted'];

        var series = summaryRows.map(function(row, i) {
            var allVals = [
                row['T1均值'] || 0,
                row['T2均值'] || 0,
                row['T3均值'] || 0,
                row['T4均值'] || 0,
                row['T5均值'] || 0
            ];
            var vals = allVals.slice(0, nAvail);
            return {
                name: row['策略分组'] || '',
                type: 'line',
                data: vals.map(function(v) { return (v * 100).toFixed(2); }),
                smooth: true,
                symbol: 'circle',
                symbolSize: 8,
                lineStyle: { width: 2.5, color: colors[i], type: lineStyles[i] },
                itemStyle: { color: colors[i] },
                label: {
                    show: true,
                    formatter: '{c}%',
                    fontSize: 10,
                    fontWeight: 'bold',
                    offset: [8, -10]
                }
            };
        });

        var chart = echarts.init(el, 'dark');
        chart.setOption({
            title: nAvail < 5 ? {
                text: '⚠️ 仅展示已结算的 ' + nAvail + '/5 天，后续交易日后自动更新',
                left: 'center',
                bottom: 0,
                textStyle: { color: '#ffc107', fontSize: 12, fontWeight: 'normal' }
            } : undefined,
            tooltip: {
                trigger: 'axis',
                formatter: function(params) {
                    var s = params[0].axisValue;
                    params.forEach(function(p) {
                        s += '<br/>' + p.marker + ' ' + p.seriesName + ': ' + p.value + '%';
                    });
                    return s;
                }
            },
            legend: { data: summaryRows.map(function(r) { return r['策略分组'] || ''; }), top: 0 },
            grid: { left: '6%', right: '6%', bottom: nAvail < 5 ? '30px' : '3%', top: '40px', containLabel: true },
            xAxis: { type: 'category', data: labels, boundaryGap: true },
            yAxis: {
                type: 'value',
                name: '累计收益 (%)',
                axisLabel: { formatter: '{value}%' }
            },
            series: series
        });
        window.addEventListener('resize', function() { chart.resize(); });
    } catch(e) {
        console.error('[trajectoryChart] render error:', e.message);
        var el2 = document.getElementById(domId);
        if (el2) el2.innerHTML = '<div style="color:#dc3545;padding:40px;text-align:center;">⚠️ 图表渲染失败: ' + e.message + '</div>';
    }
}

/* ── 收益率分布直方图 ─────────────────── */
function renderReturnHistogram(domId, returns) {
    const el = document.getElementById(domId);
    if (!el) return;
    const chart = echarts.init(el, 'dark');
    const minR = Math.min(...returns);
    const maxR = Math.max(...returns);
    const binCount = 20;
    const binWidth = (maxR - minR) / binCount || 0.01;
    const bins = Array.from({length: binCount}, (_, i) => {
        const lo = minR + i * binWidth;
        const hi = lo + binWidth;
        const count = returns.filter(r => r >= lo && (i === binCount-1 ? r <= hi : r < hi)).length;
        const success = returns.filter(r => r >= lo && (i === binCount-1 ? r <= hi : r < hi) && r >= 0).length;
        return { lo, hi, count, success, fail: count - success };
    });
    const labels = bins.map(b => (b.lo * 100).toFixed(1) + '%');
    chart.setOption({
        tooltip: {
            trigger: 'axis',
            formatter: function(params) {
                const idx = params[0].dataIndex;
                const b = bins[idx];
                const range = (b.lo * 100).toFixed(1) + '% ~ ' + (b.hi * 100).toFixed(1) + '%';
                return range + '<br/>成功: ' + b.success + ' | 失败: ' + b.fail + ' | 合计: ' + b.count;
            }
        },
        grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
        xAxis: { type: 'category', data: labels, axisLabel: { rotate: 45, fontSize: 10 } },
        yAxis: { type: 'value', minInterval: 1 },
        series: [
            {
                name: '成功',
                type: 'bar',
                stack: 'total',
                data: bins.map(b => b.success),
                itemStyle: { color: '#198754' }
            },
            {
                name: '失败',
                type: 'bar',
                stack: 'total',
                data: bins.map(b => b.fail),
                itemStyle: { color: '#dc3545' }
            }
        ]
    });
    window.addEventListener('resize', () => chart.resize());
}

/* ── 冷门行业总轨迹图 ─────────────────── */
function renderColdCombinedTrajectory(domId, trajectory) {
    try {
        var el = document.getElementById(domId);
        if (!el) return;
        var chart = echarts.init(el, 'dark');

        var keys = Object.keys(trajectory).sort();
        if (keys.length === 0) {
            el.innerHTML = '<div style="color:#888;padding:60px;text-align:center;">暂无冷门行业合并数据</div>';
            return;
        }

        var labels = keys.map(function(k) { return k.replace('均值', '').replace('T', 'T+'); });
        var vals = keys.map(function(k) { return (trajectory[k] * 100).toFixed(2); });

        chart.setOption({
            tooltip: { trigger: 'axis', formatter: function(p) { return p[0].name + '<br/>累计回报: ' + p[0].value + '%'; } },
            grid: { left: '5%', right: '5%', bottom: '3%', top: '5%', containLabel: true },
            xAxis: { type: 'category', data: labels },
            yAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
            series: [{
                name: '冷门总回报',
                type: 'line',
                data: vals,
                smooth: true,
                symbol: 'circle',
                symbolSize: 8,
                lineStyle: { width: 3, color: '#ffc107' },
                itemStyle: { color: '#ffc107' },
                areaStyle: {
                    color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                        { offset: 0, color: 'rgba(255,193,7,0.3)' },
                        { offset: 1, color: 'rgba(255,193,7,0.02)' }
                    ])
                },
                markLine: {
                    data: [{ type: 'average', name: '均值' }],
                    lineStyle: { type: 'dashed', color: '#aaa' }
                }
            }]
        });
        window.addEventListener('resize', function() { chart.resize(); });
    } catch(e) {
        console.error('[coldCombined] render error:', e.message);
    }
}
