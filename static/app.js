// PulseWatch frontend — vanilla JS, без сборки

// ─── Хранение токенов ───────────────────────────────────────────────────────

const STORAGE_KEY = "pulsewatch.tokens";

function getTokens() {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
}

function setTokens(tokens) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(tokens));
}

function clearTokens() {
    localStorage.removeItem(STORAGE_KEY);
}

// ─── HTTP-обёртка с авто-refresh ────────────────────────────────────────────

async function apiFetch(url, options = {}) {
    const tokens = getTokens();
    const headers = {...(options.headers || {})};
    if (tokens?.access_token) {
        headers.Authorization = `Bearer ${tokens.access_token}`;
    }

    let response = await fetch(url, {...options, headers});

    if (response.status === 401 && tokens?.refresh_token) {
        const refreshed = await tryRefresh(tokens.refresh_token);
        if (refreshed) {
            headers.Authorization = `Bearer ${refreshed.access_token}`;
            response = await fetch(url, {...options, headers});
        } else {
            clearTokens();
            renderLogin();
        }
    }

    return response;
}

async function tryRefresh(refreshToken) {
    const response = await fetch("/auth/refresh", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({refresh_token: refreshToken}),
    });
    if (!response.ok) return null;
    const tokens = await response.json();
    setTokens(tokens);
    return tokens;
}

// ─── Auth-операции ──────────────────────────────────────────────────────────

async function login(email, password) {
    const body = new URLSearchParams();
    body.set("username", email);
    body.set("password", password);

    const response = await fetch("/auth/login", {
        method: "POST",
        headers: {"Content-Type": "application/x-www-form-urlencoded"},
        body,
    });

    if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.detail || `Ошибка входа (${response.status})`);
    }

    const tokens = await response.json();
    setTokens(tokens);
    return tokens;
}

async function logout() {
    closeMetricsWs();
    closeLogsWs();
    const tokens = getTokens();
    if (tokens?.refresh_token) {
        await fetch("/auth/logout", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({refresh_token: tokens.refresh_token}),
        }).catch(() => {});
    }
    clearTokens();
    renderLogin();
}

async function fetchMe() {
    const response = await apiFetch("/auth/me");
    if (!response.ok) return null;
    return response.json();
}

// ─── API: servers/rules/events/aggregates ───────────────────────────────────

async function fetchServers() {
    const response = await apiFetch("/servers/me");
    return response.ok ? response.json() : [];
}

async function fetchMetrics(serverId, limit = 60) {
    const response = await apiFetch(`/servers/${serverId}/metrics?limit=${limit}`);
    return response.ok ? response.json() : [];
}

async function fetchRules() {
    const response = await apiFetch("/alerts/rules");
    return response.ok ? response.json() : [];
}

async function createRule(payload) {
    return apiFetch("/alerts/rules", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
    });
}

async function patchRule(ruleId, fields) {
    return apiFetch(`/alerts/rules/${ruleId}`, {
        method: "PATCH",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(fields),
    });
}

async function deleteRule(ruleId) {
    return apiFetch(`/alerts/rules/${ruleId}`, {method: "DELETE"});
}

async function fetchEvents({serverId = null, limit = 100} = {}) {
    const params = new URLSearchParams({limit: String(limit)});
    if (serverId) params.set("server_id", String(serverId));
    const response = await apiFetch(`/alerts/events?${params}`);
    return response.ok ? response.json() : [];
}

async function fetchAggregates(serverId, period, limit = 100) {
    const response = await apiFetch(
        `/servers/${serverId}/metrics/aggregate?period=${period}&limit=${limit}`
    );
    return response.ok ? response.json() : [];
}

// ─── Состояние ──────────────────────────────────────────────────────────────

const MAX_POINTS = 60;
let serversCache = [];          // последняя загрузка /servers/me
let currentTab = "servers";
let currentChart = null;
let aggregatesChart = null;
let selectedServerId = null;
let currentMetricsWs = null;
let currentLogsWs = null;

// ─── Вспомогательные ────────────────────────────────────────────────────────

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str == null ? "" : String(str);
    return div.innerHTML;
}

function wsUrl(path, params = {}) {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const tokens = getTokens();
    const qs = new URLSearchParams({...params, token: tokens?.access_token ?? ""});
    return `${proto}://${location.host}${path}?${qs}`;
}

// ─── Tab switching ──────────────────────────────────────────────────────────

function setTab(name) {
    currentTab = name;
    document.querySelectorAll(".tab").forEach((el) => {
        el.classList.toggle("active", el.dataset.tab === name);
    });
    document.querySelectorAll(".tab-view").forEach((el) => {
        el.hidden = el.id !== `view-${name}`;
    });

    // На смене таба останавливаем активные WS, чтобы не оставлять «висячих»
    if (name !== "servers") closeMetricsWs();
    if (name !== "logs") closeLogsWs();

    // Lazy-load: подгружаем данные при первом открытии
    if (name === "rules") loadRulesTab();
    else if (name === "events") loadEventsTab();
    else if (name === "aggregates") initAggregatesTab();
    else if (name === "logs") initLogsTab();
}

// ─── Servers tab ────────────────────────────────────────────────────────────

function renderServers(servers) {
    const container = document.getElementById("servers-list");
    container.innerHTML = "";

    if (servers.length === 0) {
        const empty = document.createElement("p");
        empty.className = "empty";
        empty.textContent = "У тебя нет зарегистрированных серверов. Зарегистрируй через POST /servers/register.";
        container.appendChild(empty);
        return;
    }

    for (const server of servers) {
        container.appendChild(serverCard(server));
    }
}

function serverCard(server) {
    const card = document.createElement("div");
    card.className = "server-card";
    card.dataset.serverId = server.id;

    const lastSeen = server.last_seen_at
        ? new Date(server.last_seen_at).toLocaleString()
        : "ни разу";
    const statusClass = server.is_active ? "status-active" : "status-inactive";
    const statusText = server.is_active ? "✅ active" : "⏸ inactive";
    const version = server.agent_version ?? "—";

    card.innerHTML = `
        <div class="server-card-header">
            <span class="server-name">${escapeHtml(server.name)}</span>
            <span class="server-id">#${server.id}</span>
        </div>
        <div class="server-meta">
            <div class="${statusClass}">${statusText}</div>
            <div>last seen: ${escapeHtml(lastSeen)}</div>
            <div>agent: ${escapeHtml(version)}</div>
        </div>
    `;

    card.addEventListener("click", () => selectServer(server));
    return card;
}

async function selectServer(server) {
    selectedServerId = server.id;

    document.querySelectorAll(".server-card").forEach((el) => {
        el.classList.toggle("selected", Number(el.dataset.serverId) === server.id);
    });

    document.getElementById("detail-panel").hidden = false;
    document.getElementById("detail-title").textContent =
        `${server.name} (#${server.id}) — реал-тайм`;

    const metrics = await fetchMetrics(server.id, MAX_POINTS);
    metrics.reverse();
    renderChart(metrics);
    openMetricsWs(server.id);
}

function renderChart(metrics) {
    const ctx = document.getElementById("metrics-chart");
    const labels = metrics.map((m) => new Date(m.collected_at).toLocaleTimeString());
    const cpu = metrics.map((m) => m.cpu_percent);
    const mem = metrics.map((m) => m.memory_percent);
    const disk = metrics.map((m) => m.disk_percent);

    if (currentChart) currentChart.destroy();
    currentChart = new Chart(ctx, lineChartConfig(labels, [
        {label: "CPU %", data: cpu, color: "#f38ba8"},
        {label: "Memory %", data: mem, color: "#89b4fa"},
        {label: "Disk %", data: disk, color: "#a6e3a1"},
    ]));
}

function lineChartConfig(labels, series) {
    return {
        type: "line",
        data: {
            labels,
            datasets: series.map((s) => ({
                label: s.label,
                data: s.data,
                borderColor: s.color,
                backgroundColor: "transparent",
                tension: 0.2,
            })),
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {mode: "index", intersect: false},
            scales: {
                y: {min: 0, max: 100, ticks: {color: "#a6adc8"}, grid: {color: "#313244"}},
                x: {ticks: {color: "#a6adc8", maxRotation: 0, autoSkip: true}, grid: {color: "#313244"}},
            },
            plugins: {
                legend: {labels: {color: "#cdd6f4"}},
                tooltip: {backgroundColor: "#181825"},
            },
        },
    };
}

function openMetricsWs(serverId) {
    closeMetricsWs();
    const tokens = getTokens();
    if (!tokens?.access_token) return;

    const ws = new WebSocket(wsUrl(`/ws/metrics/${serverId}`));
    currentMetricsWs = ws;

    ws.onmessage = (event) => {
        if (selectedServerId !== serverId) return;
        try {
            const payload = JSON.parse(event.data);
            if (payload.type === "metric") appendMetricPoint(payload);
        } catch (err) {
            console.warn("ws: bad payload", err);
        }
    };

    ws.onclose = async (event) => {
        if (currentMetricsWs !== ws) return;
        if (event.code === 1008 && tokens?.refresh_token) {
            const refreshed = await tryRefresh(tokens.refresh_token);
            if (refreshed && selectedServerId === serverId) {
                openMetricsWs(serverId);
            }
        }
    };
}

function closeMetricsWs() {
    if (currentMetricsWs) {
        currentMetricsWs.onmessage = null;
        currentMetricsWs.onclose = null;
        currentMetricsWs.onerror = null;
        try { currentMetricsWs.close(); } catch {}
        currentMetricsWs = null;
    }
}

function appendMetricPoint(metric) {
    if (!currentChart) return;
    const label = new Date(metric.collected_at).toLocaleTimeString();
    const data = currentChart.data;
    data.labels.push(label);
    data.datasets[0].data.push(metric.cpu_percent);
    data.datasets[1].data.push(metric.memory_percent);
    data.datasets[2].data.push(metric.disk_percent);
    while (data.labels.length > MAX_POINTS) {
        data.labels.shift();
        for (const ds of data.datasets) ds.data.shift();
    }
    currentChart.update("none");
}

// ─── Rules tab ──────────────────────────────────────────────────────────────

const SYSTEM_FIELDS = ["cpu_percent", "memory_percent", "disk_percent"];
const DOCKER_FIELDS = ["cpu_percent", "memory_usage_mb", "memory_limit_mb"];

function initRuleFormSelectors() {
    const serverSel = document.getElementById("rule-server");
    serverSel.innerHTML = "";
    for (const s of serversCache) {
        const opt = document.createElement("option");
        opt.value = s.id;
        opt.textContent = `#${s.id} ${s.name}`;
        serverSel.appendChild(opt);
    }
    updateRuleMetricFields();
}

function updateRuleMetricFields() {
    const type = document.getElementById("rule-metric-type").value;
    const fields = type === "docker" ? DOCKER_FIELDS : SYSTEM_FIELDS;
    document.getElementById("rule-container-wrap").hidden = type !== "docker";
    const sel = document.getElementById("rule-metric-field");
    sel.innerHTML = "";
    for (const f of fields) {
        const opt = document.createElement("option");
        opt.value = f;
        opt.textContent = f;
        sel.appendChild(opt);
    }
}

async function submitRuleForm(e) {
    e.preventDefault();
    const errorEl = document.getElementById("rules-new-error");
    errorEl.hidden = true;

    const channels = [];
    if (document.getElementById("rule-channel-telegram").checked) channels.push("telegram");
    if (document.getElementById("rule-channel-email").checked) channels.push("email");

    const payload = {
        server_id: Number(document.getElementById("rule-server").value),
        name: document.getElementById("rule-name").value.trim(),
        metric_type: document.getElementById("rule-metric-type").value,
        metric_field: document.getElementById("rule-metric-field").value,
        operator: document.getElementById("rule-operator").value,
        threshold_value: Number(document.getElementById("rule-threshold").value),
        cooldown_seconds: Number(document.getElementById("rule-cooldown").value),
        notification_channels: channels,
    };
    if (payload.metric_type === "docker") {
        const container = document.getElementById("rule-container").value.trim();
        if (container) payload.container_name = container;
    }

    const response = await createRule(payload);
    if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        errorEl.textContent = `Ошибка ${response.status}: ${JSON.stringify(detail.detail || detail)}`;
        errorEl.hidden = false;
        return;
    }
    document.getElementById("rules-new-form").reset();
    document.getElementById("rules-new-form").hidden = true;
    document.getElementById("rules-new-toggle").hidden = false;
    loadRulesTab();
}

async function loadRulesTab() {
    initRuleFormSelectors();
    const wrap = document.getElementById("rules-table-wrap");
    wrap.innerHTML = '<p class="empty">Загрузка…</p>';

    const rules = await fetchRules();
    if (rules.length === 0) {
        wrap.innerHTML = '<p class="empty">У тебя нет правил. Создавай через POST /alerts/rules.</p>';
        return;
    }

    const serverNameById = Object.fromEntries(serversCache.map((s) => [s.id, s.name]));
    const rows = rules
        .map((r) => {
            const stateClass = r.is_active ? "status-on" : "status-off";
            const stateText = r.is_active ? "on" : "off";
            const serverName = serverNameById[r.server_id] ?? `#${r.server_id}`;
            const container = r.container_name ? ` <span class="server-id">(${escapeHtml(r.container_name)})</span>` : "";
            return `
                <tr data-rule-id="${r.id}">
                    <td>#${r.id}</td>
                    <td>${escapeHtml(r.name)}</td>
                    <td>${escapeHtml(serverName)}${container}</td>
                    <td>${escapeHtml(r.metric_type)}</td>
                    <td>${escapeHtml(r.metric_field)} ${escapeHtml(r.operator)} ${r.threshold_value}</td>
                    <td class="${stateClass}">${stateText}</td>
                    <td>
                        <button class="btn-small btn-secondary" data-action="toggle">${r.is_active ? "off" : "on"}</button>
                        <button class="btn-small btn-secondary" data-action="delete">del</button>
                    </td>
                </tr>
            `;
        })
        .join("");

    wrap.innerHTML = `
        <table>
            <thead>
                <tr><th>id</th><th>name</th><th>server</th><th>type</th><th>condition</th><th>state</th><th></th></tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>
    `;

    // Привязываем обработчики
    wrap.querySelectorAll("button[data-action]").forEach((btn) => {
        btn.addEventListener("click", async (e) => {
            const tr = e.target.closest("tr");
            const ruleId = Number(tr.dataset.ruleId);
            const action = btn.dataset.action;
            if (action === "toggle") {
                const rule = rules.find((r) => r.id === ruleId);
                await patchRule(ruleId, {is_active: !rule.is_active});
            } else if (action === "delete") {
                if (!confirm(`Удалить правило #${ruleId}?`)) return;
                await deleteRule(ruleId);
            }
            loadRulesTab();
        });
    });
}

// ─── Events tab ─────────────────────────────────────────────────────────────

function initEventsServerFilter() {
    const sel = document.getElementById("events-server-filter");
    const current = sel.value;
    sel.innerHTML = '<option value="">все</option>';
    for (const s of serversCache) {
        const opt = document.createElement("option");
        opt.value = s.id;
        opt.textContent = `#${s.id} ${s.name}`;
        sel.appendChild(opt);
    }
    sel.value = current;
}

async function loadEventsTab() {
    initEventsServerFilter();
    await renderEvents();
}

async function renderEvents() {
    const wrap = document.getElementById("events-table-wrap");
    wrap.innerHTML = '<p class="empty">Загрузка…</p>';

    const serverId = document.getElementById("events-server-filter").value || null;
    const events = await fetchEvents({serverId, limit: 100});
    if (events.length === 0) {
        wrap.innerHTML = '<p class="empty">Событий не найдено.</p>';
        return;
    }

    const rows = events
        .map((e) => {
            const statusClass = e.resolved_at ? "status-resolved" : "status-open";
            const statusText = e.resolved_at ? "resolved" : "open";
            const resolvedAt = e.resolved_at ? new Date(e.resolved_at).toLocaleString() : "—";
            return `
                <tr>
                    <td>#${e.id}</td>
                    <td>#${e.server_id}${e.container_name ? ` / ${escapeHtml(e.container_name)}` : ""}</td>
                    <td>#${e.rule_id}</td>
                    <td>${e.metric_value} (порог ${e.threshold_value})</td>
                    <td class="${statusClass}">${statusText}</td>
                    <td>${new Date(e.created_at).toLocaleString()}</td>
                    <td>${escapeHtml(resolvedAt)}</td>
                </tr>
            `;
        })
        .join("");

    wrap.innerHTML = `
        <table>
            <thead>
                <tr><th>id</th><th>server</th><th>rule</th><th>value</th><th>status</th><th>created</th><th>resolved</th></tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>
    `;
}

// ─── Aggregates tab ─────────────────────────────────────────────────────────

function initAggregatesTab() {
    const sel = document.getElementById("aggregates-server");
    const current = sel.value;
    sel.innerHTML = "";
    for (const s of serversCache) {
        const opt = document.createElement("option");
        opt.value = s.id;
        opt.textContent = `#${s.id} ${s.name}`;
        sel.appendChild(opt);
    }
    sel.value = current || (serversCache[0]?.id ?? "");
}

async function loadAggregatesChart() {
    const serverId = document.getElementById("aggregates-server").value;
    const period = document.getElementById("aggregates-period").value;
    if (!serverId) return;

    const data = await fetchAggregates(serverId, period, 100);
    // API отдаёт в порядке desc — переворачиваем для графика
    data.reverse();

    const labels = data.map((d) => new Date(d.period_start).toLocaleString());
    const ctx = document.getElementById("aggregates-chart");

    if (aggregatesChart) aggregatesChart.destroy();
    aggregatesChart = new Chart(ctx, lineChartConfig(labels, [
        {label: "CPU avg", data: data.map((d) => d.avg_cpu), color: "#f38ba8"},
        {label: "Memory avg", data: data.map((d) => d.avg_memory), color: "#89b4fa"},
        {label: "Disk avg", data: data.map((d) => d.avg_disk), color: "#a6e3a1"},
    ]));
}

// ─── Logs tab ───────────────────────────────────────────────────────────────

function initLogsTab() {
    const sel = document.getElementById("logs-server");
    const current = sel.value;
    sel.innerHTML = "";
    for (const s of serversCache) {
        const opt = document.createElement("option");
        opt.value = s.id;
        opt.textContent = `#${s.id} ${s.name}`;
        sel.appendChild(opt);
    }
    sel.value = current || (serversCache[0]?.id ?? "");
    updateLogsToggleButton();
}

function updateLogsToggleButton() {
    const btn = document.getElementById("logs-toggle");
    btn.textContent = currentLogsWs ? "Отключить" : "Подключить";
}

function toggleLogsWs() {
    if (currentLogsWs) {
        closeLogsWs();
    } else {
        const serverId = document.getElementById("logs-server").value;
        if (serverId) openLogsWs(Number(serverId));
    }
    updateLogsToggleButton();
}

function openLogsWs(serverId) {
    closeLogsWs();
    const tokens = getTokens();
    if (!tokens?.access_token) return;

    const ws = new WebSocket(wsUrl(`/ws/logs/${serverId}`));
    currentLogsWs = ws;

    ws.onmessage = (event) => {
        const stream = document.getElementById("logs-stream");
        stream.textContent += event.data + "\n";
        stream.scrollTop = stream.scrollHeight;
    };

    ws.onclose = async (event) => {
        if (currentLogsWs !== ws) return;
        currentLogsWs = null;
        updateLogsToggleButton();
        if (event.code === 1008 && tokens?.refresh_token) {
            const refreshed = await tryRefresh(tokens.refresh_token);
            if (refreshed) openLogsWs(serverId);
            updateLogsToggleButton();
        }
    };
}

function closeLogsWs() {
    if (currentLogsWs) {
        currentLogsWs.onmessage = null;
        currentLogsWs.onclose = null;
        currentLogsWs.onerror = null;
        try { currentLogsWs.close(); } catch {}
        currentLogsWs = null;
    }
}

// ─── Login/Dashboard ────────────────────────────────────────────────────────

function renderLogin() {
    document.getElementById("login-view").hidden = false;
    document.querySelectorAll(".tab-view").forEach((el) => (el.hidden = true));
    document.getElementById("tabs").hidden = true;
    document.getElementById("user-bar").hidden = true;
    document.getElementById("login-error").hidden = true;
    document.getElementById("login-form").reset();
}

async function renderDashboard(user) {
    document.getElementById("login-view").hidden = true;
    document.getElementById("tabs").hidden = false;
    document.getElementById("user-bar").hidden = false;
    document.getElementById("user-email").textContent = user.email;

    serversCache = await fetchServers();
    renderServers(serversCache);
    setTab("servers");
}

// ─── Init ───────────────────────────────────────────────────────────────────

async function init() {
    document.getElementById("login-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const email = document.getElementById("login-email").value;
        const password = document.getElementById("login-password").value;
        const errorEl = document.getElementById("login-error");
        errorEl.hidden = true;

        try {
            await login(email, password);
            const user = await fetchMe();
            if (user) renderDashboard(user);
            else renderLogin();
        } catch (err) {
            errorEl.textContent = err.message;
            errorEl.hidden = false;
        }
    });

    document.getElementById("logout-btn").addEventListener("click", logout);

    // Tabs
    document.querySelectorAll(".tab").forEach((btn) => {
        btn.addEventListener("click", () => setTab(btn.dataset.tab));
    });

    // Rules tab handlers — форма создания
    document.getElementById("rules-new-toggle").addEventListener("click", () => {
        document.getElementById("rules-new-form").hidden = false;
        document.getElementById("rules-new-toggle").hidden = true;
        initRuleFormSelectors();
    });
    document.getElementById("rules-new-cancel").addEventListener("click", () => {
        document.getElementById("rules-new-form").hidden = true;
        document.getElementById("rules-new-toggle").hidden = false;
    });
    document.getElementById("rule-metric-type").addEventListener("change", updateRuleMetricFields);
    document.getElementById("rules-new-form").addEventListener("submit", submitRuleForm);

    // Events tab handlers
    document.getElementById("events-refresh").addEventListener("click", renderEvents);
    document.getElementById("events-server-filter").addEventListener("change", renderEvents);

    // Aggregates tab handlers
    document.getElementById("aggregates-load").addEventListener("click", loadAggregatesChart);

    // Logs tab handlers
    document.getElementById("logs-toggle").addEventListener("click", toggleLogsWs);
    document.getElementById("logs-clear").addEventListener("click", () => {
        document.getElementById("logs-stream").textContent = "";
    });

    if (getTokens()) {
        const user = await fetchMe();
        if (user) {
            renderDashboard(user);
            return;
        }
    }
    renderLogin();
}

init();
