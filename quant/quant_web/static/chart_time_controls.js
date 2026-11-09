/* Shared date windows. Original observations and NAV baselines stay unchanged. */
function chartDateISO(value) {
    let raw = String(value == null ? '' : value).trim();
    if (/^\d{4}$/.test(raw)) raw = '2026' + raw; // Legacy market/report keys belong to 2026.
    if (/^\d{8}$/.test(raw)) raw = `${raw.slice(0,4)}-${raw.slice(4,6)}-${raw.slice(6)}`;
    if (/^\d{2}\/\d{2}$/.test(raw)) raw = `2026-${raw.replace('/', '-')}`;
    raw = raw.replaceAll('/', '-');
    if (!/^\d{4}-\d{2}-\d{2}$/.test(raw)) return null;
    const date = new Date(raw + 'T00:00:00Z');
    return Number.isFinite(date.valueOf()) && date.toISOString().slice(0,10) === raw ? raw : null;
}

function chartPresetBounds(period, anchor, minimum) {
    anchor = chartDateISO(anchor);
    minimum = chartDateISO(minimum);
    if (!anchor || !minimum) return null;
    if (period === 'all') return [minimum, anchor];
    if (period === 'day') return [anchor, anchor];
    const months = {month: 1, quarter: 3, year: 12}[period];
    if (!months) return null;
    const date = new Date(anchor + 'T00:00:00Z');
    const day = date.getUTCDate();
    date.setUTCDate(1);
    date.setUTCMonth(date.getUTCMonth() - months);
    const lastDay = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 0)).getUTCDate();
    date.setUTCDate(Math.min(day, lastDay));
    return [date.toISOString().slice(0,10), anchor];
}

function chartRangeIndices(dates, start, end) {
    let first = -1, last = -1;
    dates.forEach((date, index) => {
        if (date >= start && date <= end) {
            if (first === -1) first = index;
            last = index;
        }
    });
    return first === -1 ? null : [first, last];
}

function chartZoomBoundIndex(value, percent, dates) {
    if (value !== null && value !== undefined) {
        if (typeof value === 'number' && Number.isInteger(value) && value >= 0 && value < dates.length) return value;
        const date = chartDateISO(value);
        const index = date ? dates.indexOf(date) : -1;
        if (index >= 0) return index;
    }
    return Math.max(0, Math.min(dates.length - 1, Math.round((dates.length - 1) * percent / 100)));
}

class ChartTimeRangeController {
    constructor(root) {
        this.root = root;
        this.charts = new Map();
        this.syncing = false;
        this.axis = root.dataset.timeAxis || '日期';
        this.toolbar = document.createElement('div');
        this.toolbar.className = 'card mb-3 chart-time-controls';
        this.toolbar.innerHTML = `<div class="card-body py-2">
          <div class="d-flex flex-wrap align-items-end gap-2">
            <div class="btn-group btn-group-sm" role="group" aria-label="时间窗口">
              <button type="button" class="btn btn-outline-info" data-period="day">近1日</button>
              <button type="button" class="btn btn-outline-info" data-period="month">近1月</button>
              <button type="button" class="btn btn-outline-info" data-period="quarter">近1季</button>
              <button type="button" class="btn btn-outline-info" data-period="year">近1年</button>
              <button type="button" class="btn btn-info" data-period="all">全部</button>
            </div>
            <label class="small">开始日期<input type="date" class="form-control form-control-sm" data-time-start></label>
            <label class="small">结束日期<input type="date" class="form-control form-control-sm" data-time-end></label>
            <button type="button" class="btn btn-sm btn-primary" data-time-apply>查看</button>
          </div>
          <div class="small text-body-secondary mt-2" data-time-status title="也可以按住 Ctrl 滚动鼠标滚轮来缩放图表。"></div>
          <div class="small text-danger mt-1" data-time-error role="alert" hidden></div>
        </div>`;
        root.insertBefore(this.toolbar, root.firstChild);
        this.startInput = this.toolbar.querySelector('[data-time-start]');
        this.endInput = this.toolbar.querySelector('[data-time-end]');
        this.status = this.toolbar.querySelector('[data-time-status]');
        this.error = this.toolbar.querySelector('[data-time-error]');
        this.toolbar.querySelector('[data-time-apply]').addEventListener('click', () => this.apply(this.startInput.value, this.endInput.value));
        this.toolbar.querySelectorAll('[data-period]').forEach(button => button.addEventListener('click', () => {
            const period = button.dataset.period;
            const anchor = period === 'all' ? this.maximum : (chartDateISO(this.endInput.value) || this.maximum);
            const bounds = chartPresetBounds(period, anchor, this.minimum);
            if (bounds) this.apply(bounds[0], bounds[1], period);
        }));
    }

    add(chart, dates) {
        const dom = chart.getDom();
        let frame = dom.parentElement;
        if (!frame.classList.contains('chart-time-frame')) {
            frame = document.createElement('div');
            frame.className = 'chart-time-frame position-relative';
            dom.parentNode.insertBefore(frame, dom);
            frame.appendChild(dom);
        }
        let empty = frame.querySelector('.chart-time-empty');
        if (!empty) {
            empty = document.createElement('div');
            empty.className = 'chart-time-empty position-absolute top-0 start-0 w-100 h-100 d-flex align-items-center justify-content-center text-secondary';
            empty.textContent = '这段时间还没有已结算的数据';
            empty.style.background = '#212529';
            empty.style.pointerEvents = 'none';
            empty.style.zIndex = '10';
            empty.hidden = true;
            frame.appendChild(empty);
        }
        this.charts.set(dom.id, {chart, dates, empty, dom});
        const all = [...this.charts.values()].flatMap(item => item.dates);
        this.root.querySelectorAll('[data-range-date]').forEach(row => {
            const date = chartDateISO(row.dataset.rangeDate);
            if (date) all.push(date);
        });
        all.sort();
        this.minimum = all[0];
        this.maximum = all[all.length - 1];
        chart.setOption({
            grid: {bottom: 66},
            dataZoom: [
                {id: 'time-window-inside', type: 'inside', xAxisIndex: 0, start: 0, end: 100, filterMode: 'filter', zoomOnMouseWheel: 'ctrl'},
                {id: 'time-window-slider', type: 'slider', xAxisIndex: 0, start: 0, end: 100, filterMode: 'filter', bottom: 8, height: 20}
            ]
        }, {replaceMerge: ['dataZoom']});
        chart.on('datazoom', () => {
            if (this.syncing) return;
            const zoom = chart.getOption().dataZoom[0];
            const start = chartZoomBoundIndex(zoom.startValue, zoom.start || 0, dates);
            const end = chartZoomBoundIndex(zoom.endValue, zoom.end == null ? 100 : zoom.end, dates);
            if (dates[start] && dates[end]) this.apply(dates[start], dates[end]);
        });
        this.apply(this.startInput.value || this.minimum, this.endInput.value || this.maximum, this.activePeriod || 'all');
    }

    apply(start, end, period) {
        start = chartDateISO(start);
        end = chartDateISO(end);
        if (!start || !end || start > end) {
            this.error.textContent = '请检查日期，开始日期不能晚于结束日期。';
            this.error.hidden = false;
            return false;
        }
        this.error.hidden = true;
        this.startInput.value = start;
        this.endInput.value = end;
        this.activePeriod = period || null;
        this.toolbar.querySelectorAll('[data-period]').forEach(button => {
            const active = button.dataset.period === period;
            button.classList.toggle('btn-info', active);
            button.classList.toggle('btn-outline-info', !active);
            button.setAttribute('aria-pressed', String(active));
        });
        this.syncing = true;
        try {
            for (const entry of this.charts.values()) {
                if (entry.chart.isDisposed && entry.chart.isDisposed()) continue;
                const range = chartRangeIndices(entry.dates, start, end);
                entry.empty.hidden = !!range;
                // Bootstrap's d-flex would override [hidden] on this overlay.
                entry.empty.style.setProperty('display', range ? 'none' : 'flex', 'important');
                entry.dom.style.opacity = range ? '1' : '0';
                if (range) entry.chart.dispatchAction({type: 'dataZoom', startValue: range[0], endValue: range[1]});
            }
            this.root.querySelectorAll('[data-range-date]').forEach(row => {
                const date = chartDateISO(row.dataset.rangeDate);
                row.hidden = !!date && (date < start || date > end);
            });
            this.status.textContent = `${this.axis}：${start} 至 ${end} · 拖动下方滑块可缩放`;
        } finally {
            this.syncing = false;
        }
        return true;
    }
}

function registerChartTimeRange(chart, records) {
    if (!chart || typeof chart.getDom !== 'function' || !records || !records.length) return;
    const dates = records.map(record => chartDateISO(record.date_raw || record.date));
    if (dates.some(date => !date)) return;
    const dom = chart.getDom();
    let root = dom.closest('[data-chart-range-group]');
    if (!root) {
        root = document.createElement('div');
        root.dataset.chartRangeGroup = dom.id;
        dom.parentNode.insertBefore(root, dom);
        root.appendChild(dom);
    }
    if (!root.chartTimeController) root.chartTimeController = new ChartTimeRangeController(root);
    root.chartTimeController.add(chart, dates);
}

function initReportDateControls(root) {
    root = root || document;
    root.querySelectorAll('[data-report-date-controls]').forEach(container => {
        if (container.dataset.initialized) return;
        container.dataset.initialized = 'true';
        let entries;
        try {entries = JSON.parse(container.querySelector('[data-report-dates]').textContent);} catch (_) {return;}
        entries = entries.map(raw => ({raw, date: chartDateISO(raw)})).filter(item => item.date).sort((a,b) => a.date.localeCompare(b.date));
        if (!entries.length) return;
        const period = container.querySelector('[data-report-period]');
        const dateInput = container.querySelector('[data-report-anchor]');
        const select = container.querySelector('[data-report-selection]');
        const current = chartDateISO(container.dataset.currentDate) || entries[entries.length - 1].date;
        dateInput.value = current;
        function populate() {
            const anchor = chartDateISO(dateInput.value) || current;
            let start = anchor, end = anchor;
            if (period.value !== 'day') {
                const date = new Date(anchor + 'T00:00:00Z');
                const year = date.getUTCFullYear(), month = date.getUTCMonth();
                const firstMonth = period.value === 'year' ? 0 : period.value === 'quarter' ? Math.floor(month / 3) * 3 : month;
                const span = period.value === 'year' ? 12 : period.value === 'quarter' ? 3 : 1;
                start = new Date(Date.UTC(year, firstMonth, 1)).toISOString().slice(0,10);
                end = new Date(Date.UTC(year, firstMonth + span, 0)).toISOString().slice(0,10);
            }
            select.replaceChildren();
            const visible = entries.filter(entry => entry.date >= start && entry.date <= end);
            visible.forEach(entry => {
                const option = document.createElement('option');
                option.value = entry.raw;
                option.textContent = entry.date;
                option.selected = entry.date === anchor;
                select.appendChild(option);
            });
            container.querySelector('[data-report-open]').disabled = !visible.length;
            container.querySelector('[data-report-empty]').hidden = !!visible.length;
        }
        period.addEventListener('change', populate);
        dateInput.addEventListener('change', populate);
        container.querySelector('[data-report-open]').addEventListener('click', () => {
            if (select.value) window.location.href = container.dataset.basePath + encodeURIComponent(select.value);
        });
        populate();
    });
}

if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => initReportDateControls());
    else initReportDateControls();
}
