// coordination.js - v2 funcional

let nodesData = window.__INITIAL_NODES__ || [];
let coordinatorData = window.__INITIAL_COORDINATOR__ || null;
let refreshInterval;

document.addEventListener('DOMContentLoaded', async () => {
    if (nodesData.length === 0) {
        await refreshData();
    } else {
        updateUI();
    }
    refreshTimeline();
    refreshInterval = setInterval(async () => {
        await refreshData();
        refreshTimeline();
    }, 4000);

    document.getElementById('forceElectionBtn').addEventListener('click', forceGlobalElection);
    document.getElementById('exportLogsBtn').addEventListener('click', exportLogs);
    setupNodeActionMenu();
});

function setupNodeActionMenu() {
    const nodeMenu = document.getElementById('nodeActionMenu');
    const newMenu = nodeMenu.cloneNode(true);
    nodeMenu.parentNode.replaceChild(newMenu, nodeMenu);

    document.addEventListener('click', (e) => {
        if (!e.target.closest('#nodeActionMenu')) newMenu.style.display = 'none';
    });

    document.getElementById('nodeTableBody').addEventListener('click', (e) => {
        const btn = e.target.closest('.node-actions-btn');
        if (!btn) return;
        e.stopPropagation();
        const nodeId = btn.dataset.nodeId;
        const rect = btn.getBoundingClientRect();
        newMenu.dataset.nodeId = nodeId;
        newMenu.style.left = `${rect.right + 6}px`;
        newMenu.style.top = `${rect.top}px`;
        newMenu.style.display = 'block';
    });

    newMenu.querySelectorAll('.menu-item').forEach(item => {
        item.addEventListener('click', async (e) => {
            const action = item.dataset.action;
            const nodeId = newMenu.dataset.nodeId;
            newMenu.style.display = 'none';
            await handleNodeAction(action, nodeId);
        });
    });
}

async function handleNodeAction(action, nodeId) {
    switch (action) {
        case 'details': {
            const node = nodesData.find(n => n.name === nodeId);
            if (node) showToast(`${node.name}: ${node.state} — priority ${node.priority}`, 5000, 'info');
            break;
        }
        case 'force-election': {
            try {
                const res = await fetch('/api/force-election', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({node: nodeId})
                });
                const data = await res.json();
                if (res.ok && data.success) {
                    showToast('Election forced on ' + nodeId, 2500, 'success');
                    setTimeout(refreshData, 1500);
                } else {
                    showToast(data.error || 'Force election failed', 3000, 'error');
                }
            } catch { showToast('Network error'); }
            break;
        }
        case 'disconnect': {
            try {
                const res = await fetch(`/api/node/${encodeURIComponent(nodeId)}/toggle`, { method: 'POST' });
                const data = await res.json();
                if (res.ok && data.success) {
                    showToast(data.message || 'Toggled node connection', 2200, 'success');
                    setTimeout(refreshData, 1000);
                } else {
                    showToast(data.error || 'Action failed', 3000, 'error');
                }
            } catch { showToast('Network error'); }
            break;
        }
        case 'refresh': {
            showToast('Refreshing node info...', 1800, 'info');
            await refreshData();
            break;
        }
    }
}

async function forceGlobalElection() {
    try {
        const res = await fetch('/api/force-election', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({}) });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast('Global election requested', 2200, 'success');
            setTimeout(refreshData, 1500);
        } else {
            showToast(data.error || 'Request failed', 3000, 'error');
        }
    } catch { showToast('Network error', 3000, 'error'); }
}

async function exportLogs() {
    try {
        const res = await fetch('/api/export-logs');
        if (res.ok) {
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'coordination-logs.txt';
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);
            showToast('Logs exported', 2200, 'success');
        } else {
            showToast('No logs available', 3000, 'info');
        }
    } catch { showToast('Network error', 3000, 'error'); }
}

async function refreshData() {
    try {
        const resp = await fetch('/coordination/data');
        if (!resp.ok) throw new Error('Failed to fetch');
        const data = await resp.json();
        nodesData = data.nodes;
        coordinatorData = data.coordinator;
        updateUI();
    } catch (e) {
        console.error('Error refreshing data:', e);
    }
}

function updateUI() {
    if (nodesData.length === 0) return;

    // Actualizar tarjeta del coordinador
    if (coordinatorData) {
        document.getElementById('coordinatorName').textContent = coordinatorData.name;
        const stateIndicator = document.getElementById('stateIndicator');
        const stateText = document.getElementById('stateText');
        stateIndicator.className = `w-3 h-3 rounded-full ${coordinatorData.state === 'STABLE' ? 'bg-tertiary animate-pulse' : 'bg-[#f59e0b] animate-pulse'}`;
        stateText.textContent = coordinatorData.state;
    }

    // Actualizar tabla de nodos
    const tbody = document.getElementById('nodeTableBody');
    tbody.innerHTML = nodesData.map(node => `
        <tr class="border-b border-outline-variant hover:bg-surface-container-highest transition-colors ${node.state === 'DISCONNECTED' ? 'bg-error-container/10' : ''}">
            <td class="py-4 px-5 font-body text-sm ${node.state === 'DISCONNECTED' ? 'text-on-surface-variant opacity-60' : 'text-on-surface font-medium'}">${node.name}</td>
            <td class="py-4 px-5"><span class="inline-flex items-center px-2 py-1 rounded font-label text-xs ${node.state === 'LEADER' ? 'bg-primary/10 text-primary' : node.state === 'FOLLOWER' ? 'bg-surface-container-high text-on-surface-variant' : 'bg-surface-container-highest text-on-surface-variant opacity-60'}">${node.state}</span></td>
            <td class="py-4 px-5 ${node.state === 'DISCONNECTED' ? 'text-on-surface-variant opacity-60' : 'text-on-surface-variant'}">${node.priority}</td>
            <td class="py-4 px-5 ${node.state === 'DISCONNECTED' ? 'text-error' : 'text-on-surface-variant'}">${node.uptime || '-'}</td>
            <td class="py-4 px-5 text-right"><button class="node-actions-btn text-on-surface-variant hover:text-on-surface" data-node-id="${node.name}"><span class="material-symbols-outlined text-[18px]">more_vert</span></button></td>
        </tr>
    `).join('');

    const activeCount = nodesData.filter(n => n.state !== 'DISCONNECTED').length;
    document.getElementById('activeNodesCount').textContent = `${activeCount} Active Nodes`;

    // Redibujar topología y reasignar eventos de menú
    drawTopology();
    setupNodeActionMenu();
}

async function refreshTimeline() {
    try {
        const resp = await fetch('/api/events');
        if (!resp.ok) return;
        const events = await resp.json();
        const timeline = document.getElementById('timelineContent');
        if (!events || events.length === 0) {
            timeline.innerHTML = '<p class="text-on-surface-variant text-sm">No events recorded yet.</p>';
            return;
        }
        timeline.innerHTML = `
            <div class="relative border-l border-outline-variant ml-3 space-y-6">
                ${events.map(ev => `
                    <div class="relative pl-6">
                        <div class="absolute w-3 h-3 rounded-full -left-[6.5px] top-1.5 ring-4 ring-surface-container-low
                            ${ev.type === 'election' ? 'bg-primary' : ev.type === 'failure' ? 'bg-error-container border border-error' : 'bg-surface-container-high border border-outline'}"></div>
                        <p class="font-label text-xs text-on-surface-variant mb-1">${new Date(ev.timestamp).toLocaleString()}</p>
                        <p class="font-body text-sm text-on-surface font-medium">${ev.title}</p>
                        <p class="font-body text-sm text-on-surface-variant mt-1">${ev.description}</p>
                    </div>
                `).join('')}
            </div>
        `;
    } catch (e) {
        console.error('Error fetching events:', e);
    }
}

function drawTopology() {
    const canvas = document.getElementById('topologyCanvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const container = document.getElementById('topologyContainer');
    canvas.width = container.clientWidth;
    canvas.height = container.clientHeight;

    if (nodesData.length === 0) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.font = '14px Geist, sans-serif';
        ctx.fillStyle = '#a1a1aa';
        ctx.textAlign = 'center';
        ctx.fillText('No nodes available', canvas.width/2, canvas.height/2);
        return;
    }

    const centerX = canvas.width / 2, centerY = canvas.height / 2;
    const radius = Math.min(canvas.width, canvas.height) * 0.35;
    const nodeRadius = 28;
    const leader = nodesData.find(n => n.state === 'LEADER');
    const followers = nodesData.filter(n => n.state === 'FOLLOWER');
    const down = nodesData.filter(n => n.state === 'DISCONNECTED');
    const allPeripheral = [...followers, ...down];
    const angleStep = (2 * Math.PI) / (allPeripheral.length || 1);

    const leaderPos = { x: centerX, y: centerY };
    allPeripheral.forEach((node, i) => {
        const angle = angleStep * i - Math.PI / 2;
        node.x = centerX + radius * Math.cos(angle);
        node.y = centerY + radius * Math.sin(angle);
    });

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Líneas
    ctx.setLineDash([5, 3]);
    followers.forEach(node => {
        ctx.beginPath();
        ctx.moveTo(leaderPos.x, leaderPos.y);
        ctx.lineTo(node.x, node.y);
        ctx.strokeStyle = '#52525b';
        ctx.stroke();
    });
    ctx.setLineDash([2, 4]);
    down.forEach(node => {
        ctx.beginPath();
        ctx.moveTo(leaderPos.x, leaderPos.y);
        ctx.lineTo(node.x, node.y);
        ctx.strokeStyle = '#ba1a1a';
        ctx.stroke();
    });
    ctx.setLineDash([]);

    const drawNode = (node, isLeader = false) => {
        const r = isLeader ? nodeRadius * 1.3 : nodeRadius;
        ctx.beginPath();
        ctx.arc(node.x, node.y, r, 0, 2*Math.PI);
        ctx.fillStyle = isLeader ? '#7c3aed' : (node.state === 'FOLLOWER' ? '#27272a' : '#3b1111');
        ctx.fill();
        ctx.strokeStyle = isLeader ? '#a78bfa' : (node.state === 'FOLLOWER' ? '#52525b' : '#ba1a1a');
        ctx.lineWidth = 3;
        ctx.stroke();
        ctx.fillStyle = '#fafafa';
        ctx.font = 'bold 14px Geist, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(node.short_name, node.x, node.y);
        ctx.fillStyle = '#a1a1aa';
        ctx.font = '10px Geist, sans-serif';
        ctx.fillText(node.state, node.x, node.y + r + 12);
    };
    down.forEach(drawNode);
    followers.forEach(drawNode);
    if (leader) drawNode(leader, true);
}