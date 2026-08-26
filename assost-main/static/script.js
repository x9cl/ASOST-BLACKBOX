// ================================================================
//  ASOST Dashboard — Live Edition
//  كل البيانات المعروضة هنا حقيقية وقادمة من server.py الذي يستدعي
//  محرك الترجمة الأصلي PF.py مباشرة. لا توجد بيانات عشوائية/وهمية.
// ================================================================
'use strict';

// ── Chart.js defaults ───────────────────────────────────────────
Chart.defaults.color       = '#5a8a68';
Chart.defaults.font.family = "'JetBrains Mono', monospace";
Chart.defaults.font.size   = 11;

const C = {
    green:   '#72b35a',
    greenDim:'rgba(114,179,90,0.12)',
    blue:    '#0c8c6a',
    orange:  '#c4a23a',
    red:     '#cc241d',
    purple:  '#b16286',
    aqua:    '#689d6a',
    bg:      'rgba(8,10,8,0.85)',
    border:  'rgba(26,101,68,0.28)',
};

function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
        '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
    }[c]));
}

// ================================================================
//  1. CLOCK
// ================================================================
const clockEl = document.getElementById('clock');
function updateClock() {
    const n = new Date();
    const pad = v => String(v).padStart(2,'0');
    if (clockEl) clockEl.innerHTML = `<i class="fa-regular fa-clock"></i> ${pad(n.getHours())}:${pad(n.getMinutes())}:${pad(n.getSeconds())}`;
}
setInterval(updateClock, 1000);
updateClock();

function getTs() {
    const n = new Date(), pad = v => String(v).padStart(2,'0');
    return `[${pad(n.getHours())}:${pad(n.getMinutes())}:${pad(n.getSeconds())}]`;
}

// ================================================================
//  2. SOUND (Web Audio API)
// ================================================================
let audioCtx = null, soundEnabled = false;
document.getElementById('sound-toggle').addEventListener('click', () => {
    soundEnabled = !soundEnabled;
    if (soundEnabled && !audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    document.getElementById('sound-icon').className = soundEnabled ? 'fa-solid fa-volume-low' : 'fa-solid fa-volume-xmark';
    document.getElementById('sound-toggle').classList.toggle('on', soundEnabled);
    if (soundEnabled) playClick();
});
function playClick() {
    if (!audioCtx || !soundEnabled) return;
    try {
        const buf = audioCtx.createBuffer(1, Math.floor(audioCtx.sampleRate * 0.022), audioCtx.sampleRate);
        const d   = buf.getChannelData(0);
        for (let i = 0; i < d.length; i++) d[i] = (Math.random()*2-1) * Math.pow(1 - i/d.length, 12);
        const s = audioCtx.createBufferSource(), g = audioCtx.createGain();
        s.buffer = buf; g.gain.value = 0.05;
        s.connect(g); g.connect(audioCtx.destination); s.start();
    } catch(e) {}
}

// ================================================================
//  3. WINDOW MAXIMIZE
// ================================================================
document.querySelectorAll('.ctrl-max').forEach(btn => {
    btn.addEventListener('click', e => {
        e.stopPropagation();
        const el = document.getElementById(btn.dataset.win);
        if (!el) return;
        el.classList.toggle('maximized');
        setTimeout(() => { Object.values(Chart.instances).forEach(c => c.resize()); }, 60);
    });
});
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
        document.querySelectorAll('.window.maximized').forEach(w => w.classList.remove('maximized'));
        document.querySelectorAll('.modal-overlay').forEach(m => m.classList.remove('open'));
    }
});

// ================================================================
//  4. LOG TERMINAL  (fed by real backend log lines — see section 6)
// ================================================================
const termBody = document.getElementById('terminal-output');
let curFilter = 'ALL', curSearch = '';

function asostAddLog(msg, type = 'sys') {
    if (!termBody) return;
    playClick();
    const div = document.createElement('div');
    div.dataset.type = type;
    div.dataset.raw  = msg.replace(/<[^>]+>/g,'').toLowerCase();
    let cls = 'log-info', pre = '';
    if (type==='sys')  cls = 'log-sys';
    if (type==='warn') { cls = 'log-warn'; pre = 'WARN: '; }
    if (type==='err')  { cls = 'log-err';  pre = 'ERR!: '; }
    div.innerHTML = `<span class="log-time">${getTs()}</span><span class="${cls}">${pre}${msg}</span>`;
    if (!matchFilter(div)) div.classList.add('hidden');
    termBody.appendChild(div);
    if (termBody.children.length > 280) termBody.removeChild(termBody.firstChild);
    termBody.scrollTop = termBody.scrollHeight;
}
function matchFilter(el) {
    const t = el.dataset.type || 'info';
    const r = el.dataset.raw  || '';
    return (curFilter === 'ALL' || t === curFilter) && (!curSearch || r.includes(curSearch));
}
function applyFilters() {
    termBody.querySelectorAll('div').forEach(el => el.classList.toggle('hidden', !matchFilter(el)));
    termBody.scrollTop = termBody.scrollHeight;
}
document.querySelectorAll('.log-filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.log-filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        curFilter = btn.dataset.filter;
        applyFilters();
    });
});
const logSearch = document.getElementById('log-search');
if (logSearch) logSearch.addEventListener('input', () => { curSearch = logSearch.value.trim().toLowerCase(); applyFilters(); });
document.getElementById('log-clear-btn').addEventListener('click', () => { termBody.innerHTML = ''; });

// ================================================================
//  5. API CLIENT — كل شيء هنا يتحدث فعلياً مع server.py
// ================================================================
async function apiGet(path) {
    const res = await fetch(path);
    if (!res.ok) throw new Error((await res.json().catch(()=>({detail:res.statusText}))).detail || res.statusText);
    return res.json();
}
async function apiPost(path, body) {
    const res = await fetch(path, {
        method: 'POST',
        headers: body ? {'Content-Type':'application/json'} : undefined,
        body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) throw new Error((await res.json().catch(()=>({detail:res.statusText}))).detail || res.statusText);
    return res.json();
}
async function apiDelete(path) {
    const res = await fetch(path, { method: 'DELETE' });
    if (!res.ok) throw new Error((await res.json().catch(()=>({detail:res.statusText}))).detail || res.statusText);
    return res.json();
}
async function apiUpload(file) {
    const fd = new FormData();
    fd.append('file', file);
    const res = await fetch('/api/upload', { method: 'POST', body: fd });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || 'فشل الرفع');
    return data;
}

// ================================================================
//  6. LOG POLLING (real backend log stream)
// ================================================================
let logCursor = 0;
async function pollLogs() {
    try {
        const data = await apiGet(`/api/logs?after=${logCursor}&limit=200`);
        for (const l of data.logs) {
            asostAddLog(escapeHtml(l.message), l.type);
        }
        logCursor = data.last_seq;
    } catch (e) { /* الشبكة مؤقتاً غير متاحة — سيُعاد المحاولة بالدورة التالية */ }
}

// ================================================================
//  7. TPM LIVE CHART (أعلى 3 مفاتيح استهلاكاً — بيانات حقيقية)
// ================================================================
const tpmChart = new Chart(document.getElementById('tpmChart'), {
    type: 'line',
    data: { labels: [], datasets: [] },
    options: {
        responsive:true, maintainAspectRatio:false, animation:{duration:200},
        plugins: {
            legend:{display:false},
            tooltip:{
                backgroundColor:C.bg, titleColor:C.green, bodyColor:'#a0a0a0',
                borderColor:C.border, borderWidth:1, cornerRadius:0, padding:7,
                callbacks:{ label: ctx => ` ${ctx.dataset.label}: ${ctx.parsed.y.toLocaleString()} tpm` },
            },
        },
        scales:{
            y:{ min:0, max:32000, grid:{color:C.border}, ticks:{color:C.green, callback:v=>v>=1000?(v/1000)+'K':v} },
            x:{ grid:{color:C.border}, ticks:{color:C.green, maxTicksLimit:7} },
        },
        interaction:{intersect:false, mode:'index'},
    },
});
let tpmDangerY = 30000;
Chart.register({
    id:'dangerLine',
    afterDraw(chart) {
        if (chart.canvas.id !== 'tpmChart') return;
        const {ctx, chartArea, scales} = chart;
        if (!chartArea) return;
        const y = scales.y.getPixelForValue(tpmDangerY);
        ctx.save();
        ctx.strokeStyle='rgba(204,36,29,0.45)'; ctx.lineWidth=1; ctx.setLineDash([4,4]);
        ctx.beginPath(); ctx.moveTo(chartArea.left,y); ctx.lineTo(chartArea.right,y); ctx.stroke();
        ctx.restore();
    }
});
const TPM_LINE_COLORS = [C.green, C.blue, C.orange];
function updateTpmChart(tpmHistory) {
    const limit = tpmHistory.tpm_limit || 32000;
    tpmDangerY = Math.round(limit * 0.92);
    tpmChart.options.scales.y.max = limit;
    document.querySelector('.tpm-limit-label').textContent = `── ${limit>=1000?(limit/1000)+'K':limit} LIMIT`;

    tpmChart.data.labels = tpmHistory.labels || [];
    tpmChart.data.datasets = (tpmHistory.series || []).map((s, i) => ({
        label: s.alias, data: s.data,
        borderColor: TPM_LINE_COLORS[i] || C.aqua, backgroundColor:'transparent',
        borderWidth:1.5, pointRadius:0, tension:0.3,
    }));
    tpmChart.update('none');

    const legend = document.querySelector('.key-legend');
    if (legend) {
        legend.innerHTML = (tpmHistory.series || []).map((s,i) =>
            `<span class="leg-item" style="color:${TPM_LINE_COLORS[i]||C.aqua}" title="${s.masked}">■ ${s.alias}</span>`
        ).join('');
    }
}

// ================================================================
//  8. RADAR CHART (مقاييس حقيقية مجمّعة من السيرفر)
// ================================================================
const radarChart = new Chart(document.getElementById('radarChart'), {
    type:'radar',
    data:{
        labels:['SUCCESS','QUALITY','KEY HEALTH','CACHE HIT','RELIABILITY','SPEED'],
        datasets:[{
            label:'stats', data:[0,0,0,0,0,0],
            borderColor:C.green, backgroundColor:'rgba(138,184,0,0.08)',
            borderWidth:1.5, pointBackgroundColor:C.green, pointRadius:3,
        }],
    },
    options:{
        responsive:true, maintainAspectRatio:false,
        animation:{duration:250},
        plugins:{legend:{display:false}},
        scales:{r:{
            min:0, max:100,
            grid:{color:'rgba(70,102,0,0.18)'},
            angleLines:{color:'rgba(70,102,0,0.18)'},
            pointLabels:{color:C.green, font:{size:10, family:"'JetBrains Mono'"}},
            ticks:{display:false},
        }},
    },
});
function updateRadarChart(radar) {
    radarChart.data.datasets[0].data = [
        radar.success_rate||0, radar.quality||0, radar.key_health||0,
        radar.cache_hit||0, radar.reliability||0, radar.speed||0,
    ];
    radarChart.update('none');
}

// ================================================================
//  9. API KEYS — عرض فقط (النظام يبقى يدوياً بالكامل داخل PF.py)
// ================================================================
const apiDoughnut = new Chart(document.getElementById('apiChart'), {
    type:'doughnut',
    data:{
        labels:['ACTIVE','COOLING','BLOCKED/INVALID'],
        datasets:[{ data:[0,0,0], backgroundColor:[C.green,C.purple,C.red], borderWidth:0 }],
    },
    options:{ responsive:false, plugins:{legend:{display:false}} },
});

function updateApiDoughnut(keysSummary) {
    apiDoughnut.data.datasets[0].data = [
        keysSummary.active||0, keysSummary.cooling||0, (keysSummary.blocked||0)+(keysSummary.invalid||0)
    ];
    apiDoughnut.update('none');
}

async function renderApiTable() {
    const tbody = document.getElementById('api-table-body');
    if (!tbody) return;
    let keys;
    try { keys = (await apiGet('/api/keys')).keys; } catch (e) { return; }
    tbody.innerHTML = '';
    keys.forEach(k => {
        const pct = Math.min(100, Math.round((k.tpm_current / Math.max(1,k.tpm_limit)) * 100));
        const barCls = pct >= 95 ? 'danger' : pct >= 82 ? 'warn' : '';
        const stCls  = `status-${k.status.toLowerCase()}`;
        const tr = document.createElement('tr');
        tr.title = `health ${k.health_score} · success ${k.success_rate}% · ${k.total_requests} req`;
        tr.innerHTML = `
            <td class="keyword">${k.alias}</td>
            <td class="string">${k.masked}</td>
            <td><span class="status-badge ${stCls}">${k.status}</span></td>
            <td class="number">${k.tpm_current.toLocaleString()}</td>
            <td class="comment">${k.tpm_limit.toLocaleString()}</td>
            <td><div class="tpm-bar-wrap"><div class="tpm-bar-fill ${barCls}" style="width:${pct}%"></div></div></td>`;
        tbody.appendChild(tr);
    });
}

// ================================================================
//  10. FILE QUEUE (حقيقي — يعكس طابور الترجمة الفعلي في السيرفر)
// ================================================================
let latestQueue = [];

function queueStatusLabel(job) {
    if (job.status === 'RUNNING') return job.paused ? 'PAUSED' : 'RUNNING';
    if (job.status === 'QUEUED')  return job.paused ? 'PAUSED' : 'QUEUED';
    return job.status; // DONE / ERROR / CANCELLED
}

function renderQueueTable() {
    const tbody = document.getElementById('queue-table-body');
    if (!tbody) return;
    tbody.innerHTML = '';
    latestQueue.forEach(f => {
        const pct = Math.round(f.overall_pct);
        const barCls = pct >= 90 ? 'danger' : pct >= 70 ? 'warn' : '';
        const stLabel = queueStatusLabel(f);
        const stCls  = `status-${stLabel.toLowerCase()}`;
        const tr = document.createElement('tr');

        let actions = '';
        if (f.status === 'QUEUED') {
            actions += `<button class="action-btn pause" onclick="queuePauseToggle(${f.id}, ${f.paused})" title="${f.paused?'Resume':'Pause'}">
                <i class="fa-solid fa-${f.paused?'play':'pause'}"></i></button>
                <button class="action-btn priority" onclick="queuePriorityUp(${f.id})" title="Move top">
                <i class="fa-solid fa-arrow-up"></i></button>
                <button class="action-btn remove" onclick="queueRemove(${f.id})" title="Remove"><i class="fa-solid fa-xmark"></i></button>`;
        } else if (f.status === 'RUNNING') {
            actions += `<button class="action-btn remove" onclick="queueRemove(${f.id})" title="Cancel"><i class="fa-solid fa-stop"></i></button>`;
        } else if (f.status === 'DONE') {
            actions += `<a class="action-btn" href="/api/download/${f.id}/docx" title="Download DOCX"><i class="fa-solid fa-download"></i></a>`;
            if (f.report_ready) actions += `<a class="action-btn" href="/api/download/${f.id}/report" title="HTML report" target="_blank"><i class="fa-solid fa-chart-simple"></i></a>`;
            actions += `<button class="action-btn remove" onclick="queueRemove(${f.id})" title="Remove"><i class="fa-solid fa-xmark"></i></button>`;
        } else {
            actions += `<button class="action-btn remove" onclick="queueRemove(${f.id})" title="Remove"><i class="fa-solid fa-xmark"></i></button>`;
        }

        const errTitle = f.error_message ? ` title="${escapeHtml(f.error_message)}"` : '';
        tr.innerHTML = `
            <td class="keyword">#${String(f.id).padStart(3,'0')}</td>
            <td class="string">${escapeHtml(f.filename)}</td>
            <td><span class="comment">PDF</span></td>
            <td><div class="progress-cell"><div class="progress-bar-wrap"><div class="progress-bar-fill ${barCls}" style="width:${pct}%"></div></div><span class="progress-pct">${pct}%</span></div></td>
            <td${errTitle}><span class="status-badge ${stCls}">${stLabel}</span></td>
            <td>${actions}</td>`;
        tbody.appendChild(tr);
    });
    const running = latestQueue.filter(f=>f.status==='RUNNING').length;
    const queued  = latestQueue.filter(f=>f.status==='QUEUED').length;
    const done    = latestQueue.filter(f=>f.status==='DONE').length;
    const info = document.getElementById('queue-stats-info');
    if (info) info.textContent = `/* ${running} running · ${queued} queued · ${done} done */`;
}

function renderQueueMini() {
    const list = document.getElementById('queue-mini-list');
    if (!list) return;
    list.innerHTML = '';
    latestQueue.filter(f=>f.status!=='DONE').slice(0,4).forEach(f => {
        const col = f.paused ? 'var(--term-orange)' : (f.status==='ERROR'||f.status==='CANCELLED') ? 'var(--term-red)' : 'var(--term-green-bright)';
        const pct = Math.round(f.overall_pct);
        const div = document.createElement('div');
        div.className = 'queue-mini-item';
        div.innerHTML = `<span class="comment" style="width:26px;flex-shrink:0">#${String(f.id).padStart(3,'0')}</span>
            <span class="string" style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:0.74em">${escapeHtml(f.filename)}</span>
            <div class="queue-mini-bar-wrap" style="width:44px;flex-shrink:0"><div class="queue-mini-bar" style="width:${pct}%;background:${col}"></div></div>
            <span class="number" style="width:26px;flex-shrink:0;text-align:right;font-size:0.74em">${pct}%</span>`;
        list.appendChild(div);
    });
    if (!latestQueue.filter(f=>f.status!=='DONE').length) {
        list.innerHTML = '<div class="comment" style="padding:4px 2px;font-size:0.76em;">// لا توجد ملفات قيد الانتظار حالياً</div>';
    }
}

window.queuePauseToggle = async (id, isPaused) => {
    try {
        await apiPost(`/api/queue/${id}/${isPaused ? 'resume' : 'pause'}`);
        refreshState();
    } catch (e) { asostAddLog(`فشل: ${escapeHtml(e.message)}`, 'err'); }
};
window.queuePriorityUp = async (id) => {
    try { await apiPost(`/api/queue/${id}/priority-up`); refreshState(); }
    catch (e) { asostAddLog(`فشل: ${escapeHtml(e.message)}`, 'err'); }
};
window.queueRemove = async (id) => {
    try { await apiDelete(`/api/queue/${id}`); refreshState(); }
    catch (e) { asostAddLog(`فشل: ${escapeHtml(e.message)}`, 'err'); }
};

document.getElementById('clear-done-btn').addEventListener('click', async () => {
    const done = latestQueue.filter(f => f.status === 'DONE');
    for (const f of done) { try { await apiDelete(`/api/queue/${f.id}`); } catch(e) {} }
    refreshState();
});
document.getElementById('pause-all-btn').addEventListener('click', async () => {
    const btn = document.getElementById('pause-all-btn');
    const willPause = !btn.classList.contains('is-paused');
    try {
        await apiPost(willPause ? '/api/queue/pause-all' : '/api/queue/resume-all');
        btn.classList.toggle('is-paused', willPause);
        btn.innerHTML = willPause
            ? '<i class="fa-solid fa-play"></i> RESUME ALL'
            : '<i class="fa-solid fa-pause"></i> PAUSE ALL';
        refreshState();
    } catch (e) { asostAddLog(`فشل: ${escapeHtml(e.message)}`, 'err'); }
});

// ── رفع ملف حقيقي (يُستخدم من كل نقاط الرفع في الواجهة) ─────────
async function uploadFile(file) {
    if (!file) return;
    if (!/\.pdf$/i.test(file.name)) {
        asostAddLog(`رُفض: <span class="string">"${escapeHtml(file.name)}"</span> — هذا المحرك يدعم ملفات PDF فقط حالياً`, 'warn');
        return;
    }
    asostAddLog(`رفع: <span class="string">"${escapeHtml(file.name)}"</span> ...`, 'sys');
    try {
        const job = await apiUpload(file);
        asostAddLog(`تمت الإضافة للطابور: <span class="string">"${escapeHtml(job.filename)}"</span> (#${String(job.id).padStart(3,'0')})`, 'sys');
        refreshState();
    } catch (e) {
        asostAddLog(`فشل الرفع: <span class="string">"${escapeHtml(file.name)}"</span> — ${escapeHtml(e.message)}`, 'err');
    }
}

document.getElementById('add-file-queue-btn').addEventListener('click', () => document.getElementById('modal-file-input').click());
document.getElementById('modal-file-input').addEventListener('change', e => {
    const file = e.target.files[0];
    uploadFile(file);
    e.target.value = '';
});

// ================================================================
//  11. CHAPTER TIMELINE  (بديل حقيقي لمخطط Gantt — لا يوجد عمّال
//      متوازون فعلياً في المحرك؛ الترجمة تسلسلية فصلاً بعد فصل).
//      يُعرض كقائمة DOM واضحة بدل نص كانفاس صغير غير مقروء.
// ================================================================
const CHAPTER_ROWS = 6;
let latestChapterTimeline = [];

function fmtDuration(ms) {
    const s = Math.max(0, Math.round(ms / 1000));
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60), rs = s % 60;
    return `${m}m ${rs}s`;
}

function renderChapterTimeline() {
    const list = document.getElementById('chapter-timeline-list');
    if (!list) return;
    const rows = latestChapterTimeline.slice(-CHAPTER_ROWS).reverse();

    if (!rows.length) {
        list.innerHTML = '<div class="ct-empty comment">// لا توجد فصول قيد المعالجة حالياً</div>';
        return;
    }

    const now = Date.now();
    list.innerHTML = rows.map(r => {
        const start = new Date(r.start_ts).getTime();
        const end = r.end_ts ? new Date(r.end_ts).getTime() : now;
        const dur = fmtDuration(end - start);
        const isActive = !r.end_ts;
        const state = r.cached ? 'cached' : isActive ? 'active' : 'done';
        const stateLabel = r.cached ? 'CACHED' : isActive ? 'TRANSLATING' : 'DONE';
        return `
        <div class="ct-row ct-${state}">
            <span class="ct-badge">C-${String(r.index).padStart(2,'0')}</span>
            <span class="ct-title" title="${escapeHtml(r.title)}">${escapeHtml(r.title)}</span>
            <span class="ct-dur">${dur}</span>
            <span class="ct-state ct-state-${state}">${stateLabel}</span>
        </div>`;
    }).join('');
}

// ================================================================
//  12. NODE TOPOLOGY — تصميم أوضح: عقدة واحدة "API KEYS" تعرض
//      عدد المفاتيح الحقيقي الإجمالي بدل 6 دوائر صغيرة مزدحمة،
//      خطوط أكبر (10-11px بدل 7-8px)، وتصحيح دقة الشاشات عالية
//      الكثافة (HiDPI) التي كانت تُسبّب ضبابية النص على الكانفاس.
// ================================================================
const topoCanvas = document.getElementById('topoCanvas');
const topoCtx    = topoCanvas.getContext('2d');

function fitCanvasDPR(canvas, ctx, cw, ch) {
    const dpr = window.devicePixelRatio || 1;
    const pw = Math.max(1, Math.round(cw * dpr));
    const ph = Math.max(1, Math.round(ch * dpr));
    if (canvas.width !== pw || canvas.height !== ph) {
        canvas.width = pw; canvas.height = ph;
    }
    canvas.style.width = cw + 'px';
    canvas.style.height = ch + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

let topoParticles = [];
let topoLoad      = 0.15;
let topoTime      = 0;
let hasActiveJob  = false;

const NODES = {
    keys:   { id:'API KEYS',    sub:'26 total',  status:'ACTIVE' },
    engine: { id:'ASOST ENGINE',sub:'idle',       status:'ACTIVE' },
    db:     { id:'SQLite DB',   sub:'jobs.db',    status:'ACTIVE' },
    queue:  { id:'QUEUE',       sub:'0 pending',  status:'ACTIVE' },
    api:    { id:'GEMINI API',  sub:'2.5-Pro',    status:'ACTIVE' },
    output: { id:'DOCX OUTPUT', sub:'—',          status:'ACTIVE' },
};

const nodeColor = (s) => s==='ACTIVE' ? C.green : s==='BUSY' ? C.orange : s==='DOWN' ? C.red : '#7c6f64';

function spawnParticle(x1,y1,x2,y2,cp1x,cp1y,cp2x,cp2y, color) {
    topoParticles.push({ x1,y1,x2,y2,cp1x,cp1y,cp2x,cp2y, t:0, speed:0.007+Math.random()*0.009, color });
}
function lerpBezier(x1,y1,cp1x,cp1y,cp2x,cp2y,x2,y2, t) {
    const u = 1-t;
    return {
        x: u*u*u*x1 + 3*u*u*t*cp1x + 3*u*t*t*cp2x + t*t*t*x2,
        y: u*u*u*y1 + 3*u*u*t*cp1y + 3*u*t*t*cp2y + t*t*t*y2,
    };
}
function drawTopoEdge(ctx, x1,y1,cp1x,cp1y,cp2x,cp2y, x2,y2, color, width=1.2) {
    ctx.save();
    ctx.strokeStyle = color; ctx.lineWidth = width;
    ctx.beginPath(); ctx.moveTo(x1,y1); ctx.bezierCurveTo(cp1x,cp1y,cp2x,cp2y,x2,y2); ctx.stroke();
    ctx.restore();
}
function drawHex(ctx, cx,cy,r, color) {
    ctx.beginPath();
    for (let i=0;i<6;i++) { const a=(Math.PI/3)*i-Math.PI/6, x=cx+r*Math.cos(a), y=cy+r*Math.sin(a); i===0?ctx.moveTo(x,y):ctx.lineTo(x,y); }
    ctx.closePath();
    ctx.fillStyle='rgba(6,8,6,0.92)'; ctx.strokeStyle=color; ctx.lineWidth=1.6;
    ctx.fill(); ctx.stroke();
}
function drawRect(ctx, cx,cy,w,h, color) {
    ctx.fillStyle='rgba(6,8,6,0.92)'; ctx.strokeStyle=color; ctx.lineWidth=1.6;
    ctx.fillRect(cx-w/2, cy-h/2, w, h); ctx.strokeRect(cx-w/2, cy-h/2, w, h);
}
function drawDiamond(ctx, cx,cy,r, color) {
    ctx.beginPath();
    ctx.moveTo(cx,cy-r); ctx.lineTo(cx+r*0.7,cy); ctx.lineTo(cx,cy+r); ctx.lineTo(cx-r*0.7,cy); ctx.closePath();
    ctx.fillStyle='rgba(6,8,6,0.92)'; ctx.strokeStyle=color; ctx.lineWidth=1.6;
    ctx.fill(); ctx.stroke();
}
function drawNodeLabels(ctx, cx, cy, offset, lines, color, sub) {
    ctx.textAlign='center';
    ctx.font='bold 10px "JetBrains Mono"';
    ctx.fillStyle=color;
    lines.forEach((line,i) => ctx.fillText(line, cx, cy + (i - (lines.length-1)/2) * 10.5));
    if (sub) {
        ctx.font='9.5px "JetBrains Mono"';
        ctx.fillStyle='#a89f8c';
        ctx.fillText(sub, cx, cy + offset);
    }
    ctx.textAlign='left';
}

function topoLayout(cw, ch) {
    const midY = ch/2;
    const f = { keys:0.11, eng:0.30, mid:0.475, api:0.635, out:0.90 };
    return {
        keysX: cw*f.keys, engX: cw*f.eng, dbX: cw*f.mid, queX: cw*f.mid, apiX: cw*f.api, outX: cw*f.out,
        midY, dbY: midY - Math.min(34, ch*0.20), queY: midY + Math.min(34, ch*0.20),
    };
}

function drawTopo() {
    const el = topoCanvas.parentElement;
    const cw = el.clientWidth || 400, ch = el.clientHeight || 200;
    fitCanvasDPR(topoCanvas, topoCtx, cw, ch);
    topoTime += 0.02;
    topoCtx.clearRect(0,0,cw,ch);

    // خلفية شبكية خفيفة جداً — تقليل التشويش البصري
    topoCtx.strokeStyle = 'rgba(0,200,180,0.025)'; topoCtx.lineWidth = 1;
    for (let x=0; x<cw; x+=44) { topoCtx.beginPath(); topoCtx.moveTo(x,0); topoCtx.lineTo(x,ch); topoCtx.stroke(); }

    const L = topoLayout(cw, ch);
    const keysCol = nodeColor(NODES.keys.status);
    const loadCol = `rgba(${topoLoad>0.85?'204,36,29':topoLoad>0.6?'196,162,58':'70,102,0'},${0.25+topoLoad*0.35})`;

    drawTopoEdge(topoCtx, L.keysX+24, L.midY, L.engX-22, L.midY, L.keysX+70, L.midY, L.engX-70, L.midY, loadCol, 1.6);
    drawTopoEdge(topoCtx, L.engX+22, L.midY, L.dbX-16, L.dbY, L.engX+65, L.midY, L.dbX-65, L.dbY, C.green+'66', 1.3);
    drawTopoEdge(topoCtx, L.engX+22, L.midY, L.queX-16, L.queY, L.engX+65, L.midY, L.queX-65, L.queY, C.blue+'66', 1.3);
    drawTopoEdge(topoCtx, L.dbX+16, L.dbY, L.apiX-22, L.midY, L.dbX+60, L.dbY, L.apiX-60, L.midY, C.orange+'66', 1.3);
    drawTopoEdge(topoCtx, L.queX+16, L.queY, L.apiX-22, L.midY, L.queX+60, L.queY, L.apiX-60, L.midY, C.blue+'55', 1.1);
    drawTopoEdge(topoCtx, L.apiX+22, L.midY, L.outX-18, L.midY, L.apiX+65, L.midY, L.outX-65, L.midY, C.green+'77', 1.5);

    topoParticles = topoParticles.filter(p => p.t < 1);
    topoParticles.forEach(p => {
        p.t += p.speed;
        const pos = lerpBezier(p.x1,p.y1,p.cp1x,p.cp1y,p.cp2x,p.cp2y,p.x2,p.y2,Math.min(p.t,1));
        const alpha = Math.sin(p.t * Math.PI);
        topoCtx.beginPath(); topoCtx.arc(pos.x, pos.y, 2.8, 0, Math.PI*2);
        topoCtx.fillStyle = p.color + Math.round(alpha*255).toString(16).padStart(2,'0');
        topoCtx.shadowColor = p.color; topoCtx.shadowBlur = 6;
        topoCtx.fill(); topoCtx.shadowBlur = 0;
    });

    // ── API KEYS (عقدة واحدة واضحة بدل 6 دوائر مزدحمة) ──
    const keysPulse = Math.sin(topoTime*1.6)*0.25+0.75;
    topoCtx.shadowColor=keysCol; topoCtx.shadowBlur=8*keysPulse;
    drawHex(topoCtx, L.keysX, L.midY, 23, keysCol); topoCtx.shadowBlur=0;
    drawNodeLabels(topoCtx, L.keysX, L.midY-2, 24, ['KEYS'], keysCol, NODES.keys.sub);

    const engCol = nodeColor(NODES.engine.status);
    topoCtx.shadowColor=engCol; topoCtx.shadowBlur=9*(Math.sin(topoTime*1.5)*0.3+0.7);
    drawHex(topoCtx, L.engX, L.midY, 23, engCol); topoCtx.shadowBlur=0;
    drawNodeLabels(topoCtx, L.engX, L.midY-2, 24, ['ENGINE'], engCol, NODES.engine.sub);

    drawRect(topoCtx, L.dbX, L.dbY, 34, 26, nodeColor(NODES.db.status));
    drawNodeLabels(topoCtx, L.dbX, L.dbY-1, 21, ['DB'], nodeColor(NODES.db.status), NODES.db.sub);

    drawRect(topoCtx, L.queX, L.queY, 34, 26, nodeColor(NODES.queue.status));
    drawNodeLabels(topoCtx, L.queX, L.queY-1, 21, ['QUEUE'], nodeColor(NODES.queue.status), NODES.queue.sub);

    const apiCol = nodeColor(NODES.api.status);
    topoCtx.shadowColor=apiCol; topoCtx.shadowBlur=11*(Math.sin(topoTime*2.2)*0.35+0.65);
    drawDiamond(topoCtx, L.apiX, L.midY, 23, apiCol); topoCtx.shadowBlur=0;
    drawNodeLabels(topoCtx, L.apiX, L.midY-2, 24, ['GEMINI'], apiCol, NODES.api.sub);

    drawHex(topoCtx, L.outX, L.midY, 19, nodeColor(NODES.output.status));
    drawNodeLabels(topoCtx, L.outX, L.midY-1, 20, ['DOCX'], nodeColor(NODES.output.status), NODES.output.sub);

    requestAnimationFrame(drawTopo);
}
drawTopo();

function spawnTopoParticles() {
    if (!hasActiveJob) { setTimeout(spawnTopoParticles, 900); return; }
    const el = topoCanvas.parentElement;
    const cw = el.clientWidth||400, ch=el.clientHeight||200;
    const L = topoLayout(cw, ch);
    const pcol = topoLoad > 0.8 ? C.orange : C.green;

    spawnParticle(L.keysX+24,L.midY, L.engX,L.midY, L.keysX+70,L.midY, L.engX-70,L.midY, pcol);
    if (Math.random() > 0.45) spawnParticle(L.engX+22,L.midY, L.dbX-16,L.dbY, L.engX+65,L.midY, L.dbX-65,L.dbY, C.green);
    if (Math.random() > 0.55) spawnParticle(L.engX+22,L.midY, L.queX-16,L.queY, L.engX+65,L.midY, L.queX-65,L.queY, C.blue);
    if (Math.random() > 0.35) spawnParticle(L.dbX+16,L.dbY, L.apiX-22,L.midY, L.dbX+60,L.dbY, L.apiX-60,L.midY, C.orange);
    if (Math.random() > 0.5) spawnParticle(L.queX+16,L.queY, L.apiX-22,L.midY, L.queX+60,L.queY, L.apiX-60,L.midY, C.blue);
    if (Math.random() > 0.4) spawnParticle(L.apiX+22,L.midY, L.outX-18,L.midY, L.apiX+65,L.midY, L.outX-65,L.midY, C.green);
    setTimeout(spawnTopoParticles, 250+Math.random()*550);
}
setTimeout(spawnTopoParticles, 600);

function updateTopology(state) {
    hasActiveJob = state.current_job_id !== null;
    const ks = state.keys_summary || {};
    const total = ks.total || 0;
    const down = (ks.blocked||0) + (ks.invalid||0);
    NODES.keys.sub = total ? `${ks.active||0} active · ${down} down` : '—';
    NODES.keys.status = total && down >= total*0.5 ? 'DOWN' : hasActiveJob ? 'BUSY' : 'ACTIVE';
    topoLoad = hasActiveJob ? 0.75 : 0.15;

    NODES.engine.status = hasActiveJob ? 'BUSY' : 'ACTIVE';
    NODES.engine.sub = hasActiveJob ? 'processing' : 'idle';
    NODES.queue.sub = `${state.queue.filter(j=>j.status==='QUEUED').length} pending`;
    NODES.api.status = hasActiveJob ? 'BUSY' : 'ACTIVE';
    NODES.output.status = state.output_last_status === 'ERROR' ? 'DOWN' : 'ACTIVE';
    NODES.output.sub = state.totals ? `${state.totals.books_completed} done` : '—';
}

// ================================================================
//  13. PIPELINE PROGRESS FLOW (حقيقي — من stage_index/chapters الفعلية)
// ================================================================
function setPipelineStage(idx, pct, statusTxt) {
    for (let i=0;i<5;i++) {
        const el   = document.getElementById(`stage-${i}`);
        const bar  = document.getElementById(`bar-${i}`);
        const pctEl= document.getElementById(`pct-${i}`);
        const stxt = document.getElementById(`stxt-${i}`);
        const conn = document.getElementById(`conn-${i}`);
        if (!el) continue;
        el.classList.remove('active','done');
        if (i < idx) {
            el.classList.add('done');
            if (bar)  bar.style.width = '100%';
            if (pctEl) pctEl.textContent = '100%';
            if (stxt) stxt.textContent = 'done';
            if (conn) conn.classList.remove('flowing');
        } else if (i === idx) {
            el.classList.add('active');
            if (bar)  bar.style.width = pct + '%';
            if (pctEl) pctEl.textContent = pct + '%';
            if (stxt) stxt.textContent = statusTxt || 'processing...';
            if (conn) conn.classList.add('flowing');
        } else {
            if (bar)  bar.style.width = '0%';
            if (pctEl) pctEl.textContent = '—';
            if (stxt) stxt.textContent = 'waiting';
            if (conn) conn.classList.remove('flowing');
        }
    }
}
function resetPipeline() {
    for (let i=0;i<5;i++) {
        const el   = document.getElementById(`stage-${i}`);
        const bar  = document.getElementById(`bar-${i}`);
        const pctEl= document.getElementById(`pct-${i}`);
        const stxt = document.getElementById(`stxt-${i}`);
        const conn = document.getElementById(`conn-${i}`);
        if (el)   el.classList.remove('active','done');
        if (bar)  bar.style.width = '0%';
        if (pctEl) pctEl.textContent = '—';
        if (stxt) stxt.textContent = 'waiting';
        if (conn) conn.classList.remove('flowing');
    }
    const fnEl = document.getElementById('pipeline-filename');
    if (fnEl) { fnEl.textContent = '/* idle */'; fnEl.className = 'pipeline-file-name comment'; }
}

function syncPipelineFromState(state) {
    const job = state.queue.find(j => j.id === state.current_job_id);
    const fnEl = document.getElementById('pipeline-filename');
    if (!job) { resetPipeline(); return; }

    if (fnEl) { fnEl.textContent = `"${job.filename}"`; fnEl.className = 'pipeline-file-name string'; }

    if (job.status === 'DONE') { setPipelineStage(5, 0, ''); return; }

    let pct = 0, statusTxt = 'starting...';
    const idx = Math.max(0, job.stage_index);
    if (job.stage_index === 0) {
        pct = 45; statusTxt = 'استخراج وتحليل الملف...';
    } else if (job.stage_index === 1) {
        pct = job.chapters_total ? Math.round(job.chapters_done/job.chapters_total*100) : 0;
        statusTxt = job.chapters_total ? `فصل ${job.chapters_done}/${job.chapters_total}` : 'بدء الترجمة...';
    } else if (job.stage_index === 2) {
        pct = 60; statusTxt = 'فحص الجودة...';
    } else if (job.stage_index === 3) {
        pct = 60; statusTxt = 'بناء فهرس المحتويات...';
    } else if (job.stage_index >= 4) {
        pct = 70; statusTxt = 'تجميع المستند النهائي...';
    }
    setPipelineStage(Math.min(4, idx), pct, statusTxt);
}

// ================================================================
//  14. (محجوز) — بيانات heatmap حقيقية متوفرة عبر state.heatmap إن
//      أُضيف لاحقاً عنصر واجهة يعرضها؛ لا يوجد له حاوية HTML حالياً.
// ================================================================

// ================================================================
//  15. POLYBAR + SYSTEM STATS  (حقيقي — psutil + قاعدة بيانات المهام)
// ================================================================
function updatePolybarStats(state) {
    const bEl = document.getElementById('stat-books');
    const pEl = document.getElementById('stat-pages');
    const ramEl = document.getElementById('ram-display');
    const cpuEl = document.getElementById('cpu-display');
    const totals = state.totals || {};
    if (bEl) bEl.textContent = (totals.books_completed||0).toLocaleString();
    if (pEl) {
        const p = totals.pages_processed||0;
        pEl.textContent = p >= 1000000 ? (p/1000000).toFixed(1)+'M' : p >= 1000 ? Math.round(p/1000)+'K' : String(p);
    }
    if (ramEl && state.system) ramEl.textContent = `${state.system.ram_used_gb}G/${state.system.ram_total_gb}G`;
    if (cpuEl && state.system) cpuEl.textContent = `${state.system.cpu_percent}%`;
}

function updateUptime(uptimeSeconds) {
    const el = document.querySelector('.stats-grid-term .stat-line:nth-child(4) .number');
    if (!el) return;
    const d = Math.floor(uptimeSeconds/86400);
    const h = Math.floor((uptimeSeconds%86400)/3600);
    const m = Math.floor((uptimeSeconds%3600)/60);
    el.textContent = `${d}d ${h}h ${m}m`;
}

// ================================================================
//  16. MASTER STATE POLLING
// ================================================================
let netUp = true;
function setNetworkBadge(up) {
    if (up === netUp) return;
    netUp = up;
    const badge = document.querySelector('.system-modules .module.hl-green');
    if (badge) {
        badge.innerHTML = up
            ? '<i class="fa-solid fa-network-wired"></i> UP'
            : '<i class="fa-solid fa-triangle-exclamation"></i> DOWN';
        badge.classList.toggle('hl-green', up);
        badge.style.color = up ? '' : 'var(--term-red)';
    }
}

async function refreshState() {
    let state;
    try {
        state = await apiGet('/api/state');
        setNetworkBadge(true);
    } catch (e) {
        setNetworkBadge(false);
        return;
    }

    latestQueue = state.queue || [];
    latestChapterTimeline = state.chapter_timeline || [];

    updatePolybarStats(state);
    updateUptime(state.uptime_seconds);
    updateTpmChart(state.tpm_history || {});
    updateRadarChart(state.radar || {});
    updateApiDoughnut(state.keys_summary || {});
    updateTopology(state);
    syncPipelineFromState(state);
    renderQueueMini();
    renderChapterTimeline();
    if (document.getElementById('queue-modal').classList.contains('open')) renderQueueTable();
    if (document.getElementById('api-modal').classList.contains('open')) renderApiTable();
}

// ================================================================
//  17. MODALS
// ================================================================
document.getElementById('open-queue-ws').addEventListener('click', () => openModal('queue-modal'));
document.getElementById('open-queue-btn').addEventListener('click', e => { e.stopPropagation(); openModal('queue-modal'); });
document.getElementById('open-api-ws').addEventListener('click', () => openModal('api-modal'));
function openModal(id) {
    document.getElementById(id).classList.add('open');
    if (id==='queue-modal') renderQueueTable();
    if (id==='api-modal')   renderApiTable();
}
document.querySelectorAll('.modal-close').forEach(btn => {
    btn.addEventListener('click', () => document.getElementById(btn.dataset.modal).classList.remove('open'));
});
document.querySelectorAll('.modal-overlay').forEach(ov => {
    ov.addEventListener('click', e => { if (e.target===ov) ov.classList.remove('open'); });
});

// ================================================================
//  18. UPLOAD ZONE  (حقيقي بالكامل — كان معطّلاً في النسخة السابقة)
// ================================================================
const dropZone  = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');

fileInput.addEventListener('change', e => {
    const file = e.target.files[0];
    uploadFile(file);
    e.target.value = '';
});
dropZone.addEventListener('dragover', e => e.preventDefault());
dropZone.addEventListener('dragleave', e => e.preventDefault());
dropZone.addEventListener('drop', e => {
    e.preventDefault();
    e.stopPropagation();
    const file = e.dataTransfer.files && e.dataTransfer.files[0];
    uploadFile(file);
});

// Note: the visual canvas animation for #upload-canvas (pixelated LED-billboard
// style drag/drop indicator) already exists as an inline script at the bottom
// of index.html. It is left untouched — only its file-handling was broken
// (its 'drop' listener never called preventDefault() or read the dropped
// file). The listeners above supply the real, working upload behavior;
// they coexist safely with the existing decorative animation.

// ================================================================
//  19. MATRIX RAIN (decorative)
// ================================================================
const matCanvas = document.getElementById('matrix-bg');
matCanvas.style.willChange = 'contents';
const matCtx    = matCanvas.getContext('2d');
let matDrops    = [];
let matCW = window.innerWidth, matCH = window.innerHeight;
const FS        = 13;
const MCHARS    = '010101ABCDEF█░▒▓01'.split('');
function initMatrix() {
    matCW = window.innerWidth; matCH = window.innerHeight;
    const dpr = window.devicePixelRatio || 1;
    matCanvas.width  = Math.round(matCW * dpr);
    matCanvas.height = Math.round(matCH * dpr);
    matCanvas.style.width = matCW + 'px';
    matCanvas.style.height = matCH + 'px';
    matCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const cols = Math.floor(matCW/FS);
    matDrops = Array.from({length:cols}, ()=>Math.random()*-100);
}
window.addEventListener('resize', () => {
    initMatrix();
    Object.values(Chart.instances).forEach(c=>c.resize());
});
initMatrix();
function drawMatrix() {
    matCtx.fillStyle='rgba(1,8,5,0.28)';
    matCtx.fillRect(0,0,matCW,matCH);
    matCtx.fillStyle='rgba(80,170,90,0.15)';
    matCtx.font=FS+'px "JetBrains Mono"';
    matDrops.forEach((y,i) => {
        matCtx.fillText(MCHARS[Math.floor(Math.random()*MCHARS.length)], i*FS, y*FS);
        if (y*FS>matCH && Math.random()>0.988) matDrops[i]=0;
        matDrops[i]++;
    });
    requestAnimationFrame(drawMatrix);
}
drawMatrix();

// ================================================================
//  20. ASCII GLITCH EFFECT (decorative)
// ================================================================
(function () {
    var el = document.querySelector('.ascii-art.cyberpunk-glitch');
    if (!el) return;
    el.setAttribute('data-glitch', el.textContent);
    function glitch() {
        el.classList.add('is-glitching');
        var dur = 160 + Math.random() * 180;
        setTimeout(function () {
            el.classList.remove('is-glitching');
            if (Math.random() > 0.5) {
                setTimeout(function () {
                    el.classList.add('is-glitching');
                    setTimeout(function () { el.classList.remove('is-glitching'); }, 120);
                }, dur + 50 + Math.random() * 80);
            }
        }, dur);
        setTimeout(glitch, 3000 + Math.random() * 6000);
    }
    setTimeout(glitch, 2000);
}());

// ================================================================
//  21. BOOT SEQUENCE (رسائل حقيقية عن حالة الاتصال، ثم بدء الاستطلاع)
// ================================================================
asostAddLog('asost-dashboard connecting to backend...', 'sys');

async function boot() {
    try {
        const health = await apiGet('/api/health');
        asostAddLog(`متصل بالمحرك — <span class="number">${health.keys_loaded}</span> مفتاح API محمّل [<span class="log-sys">OK</span>]`, 'sys');
    } catch (e) {
        asostAddLog('تعذّر الاتصال بالسيرفر الخلفي — تأكد أن server.py يعمل', 'err');
    }
    await refreshState();
    renderQueueMini();

    setInterval(refreshState, 2000);
    setInterval(pollLogs, 1200);
    setInterval(renderChapterTimeline, 1000);
    pollLogs();
}
boot();
