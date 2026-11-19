(() => {
    const form = document.getElementById('uploadForm');
    const uploadButton = document.getElementById('uploadBtn');
    const todayButton = document.getElementById('updateTodayBtn');
    const message = document.getElementById('uploadMsg');
    const todayMessage = document.getElementById('todayMsg');
    const badge = document.getElementById('statusBadge');
    const detail = document.getElementById('statusDetail');
    const history = document.getElementById('historyBody');
    let submitting = false;
    let running = false;
    let initialized = false;
    let timer = null;
    let polling = false;

    function syncButtons() {
        uploadButton.disabled = todayButton.disabled = !initialized || submitting || running;
        todayButton.textContent = running ? '正在更新，请稍候…' : '更新今日数据';
    }

    function showMessage(element, text, error = false) {
        element.textContent = text;
        element.className = 'small mt-2 ' + (error ? 'text-danger' : 'text-info');
    }

    async function parseResponse(response) {
        let data;
        try { data = await response.json(); }
        catch (_) { throw new Error('无法读取服务器回复，请刷新页面后重试。'); }
        if (!response.ok) throw new Error(data.error || '更新请求失败，请重试。');
        return data;
    }

    function schedulePoll() {
        if (!timer) timer = setTimeout(() => { timer = null; pollStatus(); }, 3000);
    }

    function renderStatus(status) {
        initialized = true;
        running = Boolean(status.running);
        syncButtons();
        const labels = {starting: '启动中', crawl: '抓取今日数据', write_master: '保存数据',
            refresh_market_cache: '更新行情数据', backtest: '回测中', weekly: '计算礼拜攻势',
            refresh_index_cache: '更新指数和择时回测'};
        const failed = !running && status.stage && status.stage !== 'done';
        badge.textContent = running ? (labels[status.stage] || '运行中')
            : (failed ? '更新失败' : (status.stage === 'done' ? '更新完成' : '等待更新'));
        badge.className = 'badge ' + (running ? 'bg-warning text-dark'
            : failed ? 'bg-danger' : status.stage === 'done' ? 'bg-success' : 'bg-secondary');
        detail.textContent = (status.date ? '日期：' + status.date + ' | ' : '')
            + (running ? '开始：' + (status.started_at || '') : (status.finished_at || ''))
            + (status.error ? ' | ' + status.error : '');
        if (status.source === 'today_button') {
            showMessage(todayMessage, running ? (labels[status.stage] || '更新中') + '…'
                : failed ? (status.error || '更新失败，请重试。') : '今日数据和回测已更新完成。', failed);
            if (!running && !failed) todayMessage.className = 'small mt-2 text-success';
        }
        history.replaceChildren();
        for (const item of status.history || []) {
            const row = document.createElement('tr');
            for (const value of [item.date, item.status === 'success' ? '成功' : '失败',
                item.time, item.elapsed + 's']) {
                const cell = document.createElement('td');
                cell.textContent = value;
                row.appendChild(cell);
            }
            history.appendChild(row);
        }
        if (!history.children.length) {
            const row = document.createElement('tr');
            const cell = document.createElement('td');
            cell.colSpan = 4; cell.className = 'text-muted'; cell.textContent = '暂无记录';
            row.appendChild(cell); history.appendChild(row);
        }
    }

    async function pollStatus() {
        if (polling) return;
        polling = true;
        try {
            const status = await fetch('/api/pipeline/status', {
                cache: 'no-store', signal: AbortSignal.timeout(15000)
            }).then(parseResponse);
            renderStatus(status);
            if (running) schedulePoll();
        } catch (error) {
            badge.textContent = '暂时无法获取进度';
            badge.className = 'badge bg-warning text-dark';
            detail.textContent = error.message + ' 正在重新连接…';
            schedulePoll();
        } finally { polling = false; }
    }

    async function submit(url, body, element) {
        if (submitting || running) return;
        submitting = true; syncButtons();
        showMessage(element, '正在提交…');
        try {
            const data = await fetch(url, {
                method: 'POST', body, signal: AbortSignal.timeout(15000)
            }).then(parseResponse);
            running = true;
            showMessage(element, data.message);
        } catch (error) { showMessage(element, error.message, true); }
        finally {
            submitting = false; syncButtons();
            await pollStatus();
            if (running) schedulePoll();
        }
    }

    todayButton.addEventListener('click', () => {
        const body = new FormData();
        body.set('csrf_token', form.elements.csrf_token.value);
        submit('/admin/update-today', body, todayMessage);
    });
    form.addEventListener('submit', event => {
        event.preventDefault();
        if (!form.reportValidity()) return;
        submit('/admin/upload', new FormData(form), message);
    });
    syncButtons();
    pollStatus();
})();
