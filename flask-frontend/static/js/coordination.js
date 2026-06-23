// coordination.js — algoritmo Bully con acciones funcionales

let nodesData = window.__INITIAL_NODES__ || [];
let coordinatorData = window.__INITIAL_COORDINATOR__ || null;
let activeNodeId = null;
let topoResizeObserver = null;

function traducirEstado(state) {
    const estados = {
        LEADER: 'LÍDER',
        FOLLOWER: 'SEGUIDOR',
        DISCONNECTED: 'DESCONECTADO',
        STABLE: 'ESTABLE',
        ELECTION: 'ELECCIÓN'
    };
    return estados[state] || state;
}

// ── Bootstrap ───────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    if (nodesData.length === 0) {
        await refreshData();
    } else {
        renderCoordinator();
        renderTable();
        drawTopology();
    }
    await refreshTimeline();

    setInterval(async () => {
        await refreshData();
        await refreshTimeline();
    }, 4000);

    const forceElectionBtn = document.getElementById('forceElectionBtn');
    if (forceElectionBtn) forceElectionBtn.addEventListener('click', forceGlobalElection);

    const exportLogsBtn = document.getElementById('exportLogsBtn');
    if (exportLogsBtn) exportLogsBtn.addEventListener('click', exportLogs);
    initActionMenu();
    initTopologyResize();
});

function initTopologyResize() {
    const container = document.getElementById('topologyContainer');
    if (!container) return;
    topoResizeObserver = new ResizeObserver(() => drawTopology());
    topoResizeObserver.observe(container);
}

// ── Data ─────────────────────────────────────────────────────────────────────
async function refreshData() {
    try {
        const resp = await fetch('/coordination/data');
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        nodesData = data.nodes;
        coordinatorData = data.coordinator;
        renderCoordinator();
        renderTable();
        drawTopology();
    } catch (e) {
        console.error('[coordination] refreshData error:', e);
    }
}

// ── Tarjeta del coordinador ──────────────────────────────────────────────────────────
function renderCoordinator() {
    if (!coordinatorData) return;
    const nameEl = document.getElementById('coordinatorName');
    const ind    = document.getElementById('stateIndicator');
    const txt    = document.getElementById('stateText');
    if (nameEl) nameEl.textContent = coordinatorData.name;
    const isStable = coordinatorData.state === 'STABLE';
    if (ind) ind.className = `w-3 h-3 rounded-full animate-pulse ${isStable ? 'bg-tertiary' : 'bg-[#f59e0b]'}`;
    if (txt) txt.textContent = traducirEstado(coordinatorData.state);
}

// ── Registro de nodos ───────────────────────────────────────────────────
function renderTable() {
    const tbody = document.getElementById('nodeTableBody');
    if (!tbody) return;

    tbody.innerHTML = nodesData.map(node => {
        const isDead   = node.state === 'DISCONNECTED';
        const isPaused = node.paused === true;
        const stateLabel = isPaused && node.state !== 'LEADER' ? 'PAUSADO' : traducirEstado(node.state);

        const badgeClass = node.state === 'LEADER'
            ? 'bg-primary/10 text-primary'
            : isDead
                ? 'bg-error/10 text-error'
                : isPaused
                    ? 'bg-[#f59e0b]/10 text-[#f59e0b]'
                    : 'bg-surface-container-high text-on-surface-variant';

        const statusText  = isDead ? 'desconectado' : isPaused ? 'pausado' : 'en línea';
        const statusColor = isDead ? 'text-error' : isPaused ? 'text-[#f59e0b]' : 'text-tertiary';

        return `
        <tr class="border-b border-outline-variant hover:bg-surface-container-highest transition-colors ${isDead || isPaused ? 'opacity-70' : ''}">
            <td class="py-4 px-5 font-medium text-sm ${isDead ? 'text-on-surface-variant' : 'text-on-surface'}">${node.name}</td>
            <td class="py-4 px-5">
                <span class="inline-flex items-center gap-1 px-2 py-1 rounded font-label text-xs ${badgeClass}">
                    ${node.state === 'LEADER' ? '<span class="material-symbols-outlined text-[12px]">star</span>' : ''}
                    ${stateLabel}
                </span>
            </td>
            <td class="py-4 px-5 text-on-surface-variant">${node.priority}</td>
            <td class="py-4 px-5 ${statusColor} font-medium text-sm">${statusText}</td>
            <td class="py-4 px-5 text-right">
                <button class="node-actions-btn p-1 rounded text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high transition-colors"
                        data-node-id="${node.name}" aria-label="Acciones del nodo">
                    <span class="material-symbols-outlined text-[18px]">more_vert</span>
                </button>
            </td>
        </tr>`;
    }).join('');

    const active = nodesData.filter(n => n.state !== 'DISCONNECTED' && !n.paused).length;
    const countEl = document.getElementById('activeNodesCount');
    if (countEl) countEl.textContent = `${active} nodos activos`;
}

// ── Menú de acciones ───────────────────────────────────────────────────────────────
function initActionMenu() {
    const menu = document.getElementById('nodeActionMenu');
    if (!menu) return;

    document.getElementById('nodeTableBody').addEventListener('click', e => {
        const btn = e.target.closest('.node-actions-btn');
        if (!btn) return;
        e.stopPropagation();
        activeNodeId = btn.dataset.nodeId;

        const node = nodesData.find(n => n.name === activeNodeId);
        const toggleBtn = menu.querySelector('[data-action="disconnect"]');
        if (node && toggleBtn) {
            toggleBtn.textContent = node.paused ? '▶ Reanudar nodo' : '⏸ Pausar nodo';
        }

        const rect  = btn.getBoundingClientRect();
        const menuW = 180;
        const left  = rect.right + 6 + menuW > window.innerWidth
            ? rect.left - menuW - 6 : rect.right + 6;
        menu.style.left    = `${left + window.scrollX}px`;
        menu.style.top     = `${rect.top + window.scrollY}px`;
        menu.style.display = 'block';
    });

    document.addEventListener('click', e => {
        if (!e.target.closest('#nodeActionMenu')) menu.style.display = 'none';
    });

    menu.querySelectorAll('.menu-item').forEach(item => {
        item.addEventListener('click', e => {
            e.stopPropagation();
            menu.style.display = 'none';
            handleNodeAction(item.dataset.action, activeNodeId);
        });
    });
}

async function handleNodeAction(action, nodeId) {
    if (!nodeId) return;
    switch (action) {
        case 'details': {
            const node = nodesData.find(n => n.name === nodeId);
            if (node) {
                const status = node.paused ? 'PAUSADO' : traducirEstado(node.state);
                showToast(`${node.name}: ${status} — prioridad ${node.priority}`, 5000, 'info');
            }
            break;
        }
        case 'force-election': {
            showToast(`Forzando elección en ${nodeId}…`, 1500, 'info');
            try {
                const res  = await fetch('/api/force-election', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({node: nodeId})
                });
                const data = await res.json();
                if (res.ok && data.success) {
                    showToast(`Elección iniciada en ${nodeId}`, 2500, 'success');
                    // Refrescamos varias veces para ver cómo termina la elección
                    setTimeout(async () => { await refreshData(); await refreshTimeline(); }, 1500);
                    setTimeout(async () => { await refreshData(); await refreshTimeline(); }, 3500);
                } else {
                    showToast(data.error || 'No se pudo forzar la elección', 3000, 'error');
                }
            } catch { showToast('Error de conexión', 3000, 'error'); }
            break;
        }
        case 'disconnect': {
            const node = nodesData.find(n => n.name === nodeId);
            const verb = node?.paused ? 'Reanudando' : 'Pausando';
            const wasLeader = node?.state === 'LEADER';
            showToast(`${verb} ${nodeId}…`, 1200, 'info');
            try {
                const res  = await fetch(`/api/node/${encodeURIComponent(nodeId)}/toggle`, {method: 'POST'});
                const data = await res.json();
                if (res.ok && (data.success || data.warning)) {
                    // Optimistic update
                    const idx = nodesData.findIndex(n => n.name === nodeId);
                    if (idx !== -1) {
                        nodesData[idx] = {...nodesData[idx], paused: data.paused};
                        renderTable();
                        drawTopology();
                    }
                    if (data.paused && wasLeader) {
                        showToast(`${nodeId} pausado — iniciando elección Bully…`, 3000, 'info');
                    } else if (!data.paused) {
                        showToast(`${nodeId} reanudado — volviendo al clúster…`, 3000, 'info');
                    } else {
                        showToast(data.message || `Estado del nodo actualizado`, 2500, 'success');
                    }
                    // Refrescamos varias veces porque Bully puede tardar unos segundos
                    setTimeout(async () => { await refreshData(); await refreshTimeline(); }, 1200);
                    setTimeout(async () => { await refreshData(); await refreshTimeline(); }, 3000);
                    setTimeout(async () => { await refreshData(); await refreshTimeline(); }, 6000);
                } else {
                    showToast(data.error || 'No se pudo cambiar el estado del nodo', 3000, 'error');
                }
            } catch { showToast('Error de conexión', 3000, 'error'); }
            break;
        }
        case 'refresh': {
            showToast('Actualizando…', 1200, 'info');
            await refreshData();
            await refreshTimeline();
            showToast('Información del nodo actualizada', 2000, 'success');
            break;
        }
    }
}

// ── Elección global ───────────────────────────────────────────────────────────
async function forceGlobalElection() {
    showToast('Enviando señal de elección global…', 1500, 'info');
    try {
        const res  = await fetch('/api/force-election', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({})
        });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast('Señal de elección Bully enviada a los nodos', 2500, 'success');
            setTimeout(async () => { await refreshData(); await refreshTimeline(); }, 1800);
            setTimeout(async () => { await refreshData(); await refreshTimeline(); }, 4000);
        } else {
            showToast(data.error || 'Solicitud fallida', 3000, 'error');
        }
    } catch { showToast('Error de conexión', 3000, 'error'); }
}

// ── Exportar registros ───────────────────────────────────────────────────────────────
async function exportLogs() {
    try {
        const res = await fetch('/api/export-logs');
        if (res.ok) {
            const blob = await res.blob();
            const url  = URL.createObjectURL(blob);
            const a    = document.createElement('a');
            a.href = url; a.download = 'coordination-logs.txt';
            document.body.appendChild(a); a.click(); a.remove();
            URL.revokeObjectURL(url);
            showToast('Registros exportados', 2200, 'success');
        } else {
            showToast('No hay registros disponibles', 3000, 'info');
        }
    } catch { showToast('Error de conexión', 3000, 'error'); }
}

// ── Línea de eventos ────────────────────────────────────────────────────────────
async function refreshTimeline() {
    try {
        const resp = await fetch('/api/events');
        if (!resp.ok) return;
        const events = await resp.json();
        const el = document.getElementById('timelineContent');
        if (!el) return;

        if (!events || events.length === 0) {
            el.innerHTML = `<p class="text-on-surface-variant text-sm text-center py-8">Aún no hay eventos registrados.<br>
                <span class="text-xs opacity-60">Los eventos aparecerán después de usar las acciones de los nodos.</span></p>`;
            return;
        }

        const iconMap = {election: 'how_to_vote', failure: 'error', sync: 'sync'};
        const dotMap  = {election: 'bg-primary',  failure: 'bg-error',  sync: 'bg-tertiary'};

        el.innerHTML = `<div class="relative border-l-2 border-outline-variant ml-3 space-y-5">
            ${events.map(ev => {
                const dot     = dotMap[ev.type]  || 'bg-surface-container-high border border-outline';
                const icon    = iconMap[ev.type] || 'info';
                const timeStr = ev.timestamp
                    ? new Date(ev.timestamp).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit'})
                    : ev.time || '';
                return `
                <div class="relative pl-6">
                    <div class="absolute -left-[9px] top-1.5 w-4 h-4 rounded-full ${dot} ring-4 ring-surface-container-low"></div>
                    <div class="flex items-start justify-between gap-2">
                        <div class="flex-1 min-w-0">
                            <p class="font-label text-xs text-on-surface-variant mb-0.5">${timeStr}</p>
                            <p class="font-medium text-sm text-on-surface leading-snug">${ev.title}</p>
                            <p class="text-xs text-on-surface-variant mt-0.5 leading-snug">${ev.description}</p>
                        </div>
                        <span class="material-symbols-outlined text-[14px] text-on-surface-variant opacity-50 mt-1 shrink-0">${icon}</span>
                    </div>
                </div>`;
            }).join('')}
        </div>`;
        el.scrollTop = 0;
    } catch (e) {
        console.error('[coordination] refreshTimeline error:', e);
    }
}

// ── Canvas de topología ───────────────────────────────────────────────────────────
function drawTopology() {
    const canvas    = document.getElementById('topologyCanvas');
    const container = document.getElementById('topologyContainer');
    if (!canvas || !container) return;
    const W = container.clientWidth;
    const H = container.clientHeight;
    if (W === 0 || H === 0) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width  = W * dpr; canvas.height = H * dpr;
    canvas.style.width = W + 'px'; canvas.style.height = H + 'px';
    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, W, H);

    const styles = getComputedStyle(document.documentElement);
    const css = (name, fallback) => (styles.getPropertyValue(name).trim() || fallback);
    const isDark = document.documentElement.classList.contains('dark');
    const colorPrimary = css('--color-primary', '#7c3aed');
    const colorSurfaceHigh = css('--color-surface-container-high', isDark ? '#18181b' : '#eef4ff');
    const colorSurfaceHighest = css('--color-surface-container-highest', isDark ? '#1e1e22' : '#e0ecff');
    const colorOutline = css('--color-outline', isDark ? '#52525b' : '#94a3b8');
    const colorText = css('--color-on-surface', isDark ? '#fafafa' : '#0f172a');
    const colorMuted = css('--color-on-surface-variant', isDark ? '#a1a1aa' : '#475569');
    const colorError = css('--color-error', '#ef4444');
    const colorWarning = '#f59e0b';

    if (!nodesData || nodesData.length === 0) {
        ctx.fillStyle = colorMuted; ctx.font = '14px Geist, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('No hay nodos disponibles', W / 2, H / 2);
        return;
    }

    const cx = W / 2, cy = H / 2;
    const leader = nodesData.find(n => n.state === 'LEADER' && !n.paused);
    const others = nodesData.filter(n => !(n.state === 'LEADER' && !n.paused));

    const nodeRadius = Math.min(W, H) * 0.12;
    const orbitR     = Math.min(W, H) * 0.34;
    const positions  = {};
    if (leader) positions[leader.name] = {x: cx, y: cy};

    const angleStep = others.length > 0 ? (2 * Math.PI) / others.length : 0;
    others.forEach((n, i) => {
        const angle = angleStep * i - Math.PI / 2;
        positions[n.name] = {x: cx + orbitR * Math.cos(angle), y: cy + orbitR * Math.sin(angle)};
    });

    // Conexiones: líder → seguidores
    others.forEach(n => {
        const from   = leader ? positions[leader.name] : {x: cx, y: cy};
        const to     = positions[n.name];
        const isDead   = n.state === 'DISCONNECTED';
        const isPaused = n.paused === true;
        ctx.beginPath(); ctx.moveTo(from.x, from.y); ctx.lineTo(to.x, to.y);
        ctx.lineWidth   = isDead || isPaused ? 1 : 1.5;
        ctx.strokeStyle = isDead ? colorError : isPaused ? colorWarning : colorOutline;
        ctx.setLineDash(isDead || isPaused ? [4, 4] : [5, 3]);
        ctx.stroke(); ctx.setLineDash([]);

        if (!isDead && !isPaused && leader) {
            const mx = (from.x + to.x) / 2, my = (from.y + to.y) / 2;
            const dx = to.x - from.x, dy = to.y - from.y;
            const len = Math.sqrt(dx*dx + dy*dy);
            const nx = dx/len, ny = dy/len, aL = 7;
            ctx.beginPath();
            ctx.moveTo(mx, my);
            ctx.lineTo(mx - aL*nx + aL*0.4*(-ny), my - aL*ny + aL*0.4*nx);
            ctx.moveTo(mx, my);
            ctx.lineTo(mx - aL*nx - aL*0.4*(-ny), my - aL*ny - aL*0.4*nx);
            ctx.strokeStyle = colorPrimary; ctx.lineWidth = 1.5; ctx.stroke();
        }
    });

    // Conexiones entre seguidores
    for (let i = 0; i < others.length; i++) {
        for (let j = i + 1; j < others.length; j++) {
            const a = positions[others[i].name], b = positions[others[j].name];
            ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y);
            ctx.strokeStyle = colorOutline; ctx.lineWidth = 1;
            ctx.setLineDash([2, 6]); ctx.stroke(); ctx.setLineDash([]);
        }
    }

    const drawNode = (node, isLeader) => {
        const pos    = positions[node.name]; if (!pos) return;
        const r      = isLeader ? nodeRadius * 1.25 : nodeRadius;
        const isDead   = node.state === 'DISCONNECTED';
        const isPaused = node.paused === true;

        if (isLeader) {
            const grd = ctx.createRadialGradient(pos.x, pos.y, r*0.5, pos.x, pos.y, r*2);
            grd.addColorStop(0, isDark ? 'rgba(124,58,237,0.25)' : 'rgba(37,99,235,0.20)'); grd.addColorStop(1, 'rgba(37,99,235,0)');
            ctx.beginPath(); ctx.arc(pos.x, pos.y, r*2, 0, 2*Math.PI);
            ctx.fillStyle = grd; ctx.fill();
        }

        ctx.beginPath(); ctx.arc(pos.x, pos.y, r, 0, 2*Math.PI);
        ctx.fillStyle = isLeader ? colorPrimary : isDead ? (isDark ? '#1f1f1f' : '#f1f5f9') : isPaused ? (isDark ? '#292524' : '#fff7ed') : colorSurfaceHigh;
        ctx.fill();
        ctx.lineWidth   = isLeader ? 3 : 2;
        ctx.strokeStyle = isLeader ? colorPrimary : isDead ? colorError : isPaused ? colorWarning : colorOutline;
        ctx.stroke();

        ctx.fillStyle    = isDead ? colorMuted : colorText;
        ctx.font         = `bold ${isLeader ? 15 : 13}px Geist, system-ui, sans-serif`;
        ctx.textAlign    = 'center'; ctx.textBaseline = 'middle';
        ctx.fillText(node.short_name, pos.x, pos.y);

        const stateLabel = isPaused && !isLeader ? 'PAUSADO' : traducirEstado(node.state);
        ctx.fillStyle    = isLeader ? colorPrimary : isDead ? colorError : isPaused ? colorWarning : colorMuted;
        ctx.font         = `${isLeader ? 10 : 9}px Geist, system-ui, sans-serif`;
        ctx.textBaseline = 'top';
        ctx.fillText(stateLabel, pos.x, pos.y + r + 5);

        if (isLeader) {
            ctx.fillStyle = colorWarning; ctx.font = '12px sans-serif';
            ctx.textBaseline = 'bottom';
            ctx.fillText('👑', pos.x, pos.y - r - 2);
        }
    };

    nodesData.filter(n => n.state === 'DISCONNECTED').forEach(n => drawNode(n, false));
    nodesData.filter(n => n.state !== 'DISCONNECTED' && !(n.state === 'LEADER' && !n.paused)).forEach(n => drawNode(n, false));
    if (leader) drawNode(leader, true);
}

// ── Utilidad de notificaciones ─────────────────────────────────────────────────────────────
function showToast(message, duration = 3000, type = 'info') {
    if (window._showToast) { window._showToast(message, duration, type); return; }
    const existing = document.getElementById('_coord_toast');
    if (existing) existing.remove();
    const colors = {
        info:    'bg-surface-container border-outline-variant text-on-surface',
        success: 'bg-tertiary/10 border-tertiary/30 text-tertiary',
        error:   'bg-error/10 border-error/30 text-error'
    };
    const t = document.createElement('div');
    t.id = '_coord_toast';
    t.className = `fixed bottom-6 right-6 z-[200] px-4 py-3 rounded-lg border shadow-lg text-sm font-medium ${colors[type] || colors.info}`;
    t.textContent = message;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), duration);
}