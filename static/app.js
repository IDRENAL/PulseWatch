// PulseWatch frontend — vanilla JS, без сборки

// ─── i18n: ru/en через data-i18n атрибут ───────────────────────────────────

const LANG_KEY = "pulsewatch.lang";
const THEME_KEY = "pulsewatch.theme";

const I18N = {
    ru: {
        "logout": "Logout",
        "cancel": "Отмена",
        "refresh": "Обновить",
        "load": "Загрузить",
        "tab.servers": "Серверы",
        "tab.rules": "Правила",
        "tab.events": "События",
        "tab.aggregates": "Агрегаты",
        "tab.logs": "Логи",
        "tab.audit": "История",
        "audit.title": "История действий",
        "audit.filter.action": "Действие:",
        "audit.empty": "Записей нет.",
        "audit.col.when": "Когда",
        "audit.col.action": "Действие",
        "audit.col.resource": "Объект",
        "audit.col.ip": "IP",
        "login.title": "Вход",
        "login.email": "Email",
        "login.password": "Пароль",
        "login.submit": "Войти",
        "login.forgot": "Забыли пароль?",
        "login.forgot.prompt": "Введи email — пришлём ссылку для сброса пароля",
        "login.forgot.sent": "Если такой email зарегистрирован, ссылка для сброса отправлена.",
        "login.totp": "Код 2FA",
        "login.totp.required": "Введи 6-значный код из приложения 2FA",
        "profile.title": "Профиль",
        "profile.totp.label": "2FA:",
        "profile.totp.on": "включено",
        "profile.totp.off": "выключено",
        "profile.totp.enable": "Включить 2FA",
        "profile.totp.disable": "Выключить 2FA",
        "profile.totp.scan": "Отсканируй QR в приложении (Google Authenticator, Authy и т.п.):",
        "profile.totp.manual": "Или вручную:",
        "profile.totp.code": "Код из приложения",
        "profile.totp.confirm": "Подтвердить",
        "profile.totp.disable.prompt": "Введи пароль для отключения 2FA",
        "rules.title": "Алерт-правила",
        "rules.create": "Создать правило",
        "rules.submit": "Создать",
        "rules.field.server": "Сервер",
        "rules.field.name": "Имя",
        "rules.field.metric_type": "Тип метрики",
        "rules.field.container": "Имя контейнера (пусто = любой)",
        "rules.field.metric": "Метрика",
        "rules.field.operator": "Оператор",
        "rules.field.threshold": "Порог",
        "rules.field.cooldown": "Cooldown (сек)",
        "rules.field.channels": "Каналы:",
        "filter.server": "Сервер:",
        "filter.all": "все",
        "filter.period": "Период:",
        "period.fivemin": "5 минут",
        "period.hourly": "час",
        "period.daily": "день",
        "logs.title": "Журнал логов",
        "logs.connect": "Подключить",
        "logs.disconnect": "Отключить",
        "logs.clear": "Очистить",
        "theme.dark": "Тёмная",
        "theme.light": "Светлая",
        "loading": "Загрузка…",
        "servers.empty": "У тебя нет зарегистрированных серверов. Зарегистрируй через POST /servers/register.",
        "servers.never": "ни разу",
        "servers.last_seen": "last seen:",
        "servers.agent": "agent:",
        "servers.status.active": "✅ active",
        "servers.status.inactive": "⏸ inactive",
        "servers.realtime": "реал-тайм",
        "rules.empty": "У тебя нет правил. Создавай через POST /alerts/rules.",
        "rules.action.off": "выкл",
        "rules.action.on": "вкл",
        "rules.action.del": "удалить",
        "rules.confirm.delete": "Удалить правило #",
        "events.empty": "Событий не найдено.",
        "events.status.open": "открыто",
        "events.status.resolved": "закрыто",
        "events.threshold": "порог",
        "error.prefix": "Ошибка",
        "login.error.fallback": "Ошибка входа",
    },
    en: {
        "logout": "Logout",
        "cancel": "Cancel",
        "refresh": "Refresh",
        "load": "Load",
        "tab.servers": "Servers",
        "tab.rules": "Rules",
        "tab.events": "Events",
        "tab.aggregates": "Aggregates",
        "tab.logs": "Logs",
        "tab.audit": "Audit",
        "audit.title": "Audit history",
        "audit.filter.action": "Action:",
        "audit.empty": "No entries.",
        "audit.col.when": "When",
        "audit.col.action": "Action",
        "audit.col.resource": "Resource",
        "audit.col.ip": "IP",
        "login.title": "Sign in",
        "login.email": "Email",
        "login.password": "Password",
        "login.submit": "Sign in",
        "login.forgot": "Forgot password?",
        "login.forgot.prompt": "Enter your email — we'll send a reset link",
        "login.forgot.sent": "If this email is registered, a reset link has been sent.",
        "login.totp": "2FA code",
        "login.totp.required": "Enter the 6-digit code from your 2FA app",
        "profile.title": "Profile",
        "profile.totp.label": "2FA:",
        "profile.totp.on": "on",
        "profile.totp.off": "off",
        "profile.totp.enable": "Enable 2FA",
        "profile.totp.disable": "Disable 2FA",
        "profile.totp.scan": "Scan the QR with an app (Google Authenticator, Authy, ...):",
        "profile.totp.manual": "Or enter manually:",
        "profile.totp.code": "Code from app",
        "profile.totp.confirm": "Confirm",
        "profile.totp.disable.prompt": "Enter your password to disable 2FA",
        "rules.title": "Alert rules",
        "rules.create": "Create rule",
        "rules.submit": "Create",
        "rules.field.server": "Server",
        "rules.field.name": "Name",
        "rules.field.metric_type": "Metric type",
        "rules.field.container": "Container name (empty = any)",
        "rules.field.metric": "Metric",
        "rules.field.operator": "Operator",
        "rules.field.threshold": "Threshold",
        "rules.field.cooldown": "Cooldown (sec)",
        "rules.field.channels": "Channels:",
        "filter.server": "Server:",
        "filter.all": "all",
        "filter.period": "Period:",
        "period.fivemin": "5 min",
        "period.hourly": "hour",
        "period.daily": "day",
        "logs.title": "Journal logs",
        "logs.connect": "Connect",
        "logs.disconnect": "Disconnect",
        "logs.clear": "Clear",
        "theme.dark": "Dark",
        "theme.light": "Light",
        "loading": "Loading…",
        "servers.empty": "You have no registered servers. Register via POST /servers/register.",
        "servers.never": "never",
        "servers.last_seen": "last seen:",
        "servers.agent": "agent:",
        "servers.status.active": "✅ active",
        "servers.status.inactive": "⏸ inactive",
        "servers.realtime": "real-time",
        "rules.empty": "You have no rules. Create one via POST /alerts/rules.",
        "rules.action.off": "off",
        "rules.action.on": "on",
        "rules.action.del": "del",
        "rules.confirm.delete": "Delete rule #",
        "events.empty": "No events found.",
        "events.status.open": "open",
        "events.status.resolved": "resolved",
        "events.threshold": "threshold",
        "error.prefix": "Error",
        "login.error.fallback": "Login error",
    },
};

let currentLang = localStorage.getItem(LANG_KEY) || (navigator.language?.startsWith("en") ? "en" : "ru");
let currentTheme = localStorage.getItem(THEME_KEY) || "dark";

function t(key) {
    return I18N[currentLang]?.[key] ?? I18N.ru[key] ?? key;
}

function applyTranslations() {
    document.querySelectorAll("[data-i18n]").forEach((el) => {
        el.textContent = t(el.dataset.i18n);
    });
    document.documentElement.lang = currentLang;
}

function setLang(lang) {
    currentLang = lang;
    localStorage.setItem(LANG_KEY, lang);
    applyTranslations();
    // Перерисовать табы которые рисуются программно (rules/events table, logs button)
    updateLogsToggleButton();
}

// ─── Темы: dark/light, persist в localStorage, чарты перерисовываются ──────

function applyTheme() {
    document.documentElement.dataset.theme = currentTheme;
}

function setTheme(theme) {
    currentTheme = theme;
    localStorage.setItem(THEME_KEY, theme);
    applyTheme();
    // Перерисовать все чарты с новой палитрой
    refreshChartColors();
}

function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function chartPalette() {
    return {
        text: cssVar("--text-secondary"),
        textBright: cssVar("--text-primary"),
        grid: cssVar("--bg-tertiary"),
        tooltip: cssVar("--bg-secondary"),
    };
}

function refreshChartColors() {
    for (const chart of [currentChart, aggregatesChart]) {
        if (!chart) continue;
        const p = chartPalette();
        chart.options.scales.y.ticks.color = p.text;
        chart.options.scales.y.grid.color = p.grid;
        chart.options.scales.x.ticks.color = p.text;
        chart.options.scales.x.grid.color = p.grid;
        chart.options.plugins.legend.labels.color = p.textBright;
        chart.options.plugins.tooltip.backgroundColor = p.tooltip;
        chart.update("none");
    }
}

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

async function login(email, password, totpCode = null) {
    const body = new URLSearchParams();
    body.set("username", email);
    body.set("password", password);
    if (totpCode) body.set("totp_code", totpCode);

    const response = await fetch("/auth/login", {
        method: "POST",
        headers: {"Content-Type": "application/x-www-form-urlencoded"},
        body,
    });

    if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        // Сервер шлёт detail="TOTP_REQUIRED" когда нужен второй фактор —
        // прокидываем как есть, чтобы UI показал поле для кода
        throw new Error(detail.detail || `${t("login.error.fallback")} (${response.status})`);
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

async function fetchAuditLog(limit = 100) {
    const response = await apiFetch(`/audit/me?limit=${limit}`);
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
    else if (name === "audit") loadAuditTab();
}

// ─── Servers tab ────────────────────────────────────────────────────────────

function renderServers(servers) {
    const container = document.getElementById("servers-list");
    container.innerHTML = "";

    if (servers.length === 0) {
        const empty = document.createElement("p");
        empty.className = "empty";
        empty.textContent = t("servers.empty");
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
        : t("servers.never");
    const statusClass = server.is_active ? "status-active" : "status-inactive";
    const statusText = server.is_active ? t("servers.status.active") : t("servers.status.inactive");
    const version = server.agent_version ?? "—";

    card.innerHTML = `
        <div class="server-card-header">
            <span class="server-name">${escapeHtml(server.name)}</span>
            <span class="server-id">#${server.id}</span>
        </div>
        <div class="server-meta">
            <div class="${statusClass}">${statusText}</div>
            <div>${t("servers.last_seen")} ${escapeHtml(lastSeen)}</div>
            <div>${t("servers.agent")} ${escapeHtml(version)}</div>
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
        `${server.name} (#${server.id}) — ${t("servers.realtime")}`;

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
    const p = chartPalette();
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
                y: {min: 0, max: 100, ticks: {color: p.text}, grid: {color: p.grid}},
                x: {ticks: {color: p.text, maxRotation: 0, autoSkip: true}, grid: {color: p.grid}},
            },
            plugins: {
                legend: {labels: {color: p.textBright}},
                tooltip: {backgroundColor: p.tooltip},
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
        errorEl.textContent = `${t("error.prefix")} ${response.status}: ${JSON.stringify(detail.detail || detail)}`;
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
    wrap.innerHTML = `<p class="empty">${t("loading")}</p>`;

    const rules = await fetchRules();
    if (rules.length === 0) {
        wrap.innerHTML = `<p class="empty">${t("rules.empty")}</p>`;
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
                        <button class="btn-small btn-secondary" data-action="toggle">${r.is_active ? t("rules.action.off") : t("rules.action.on")}</button>
                        <button class="btn-small btn-secondary" data-action="delete">${t("rules.action.del")}</button>
                    </td>
                </tr>
            `;
        })
        .join("");

    wrap.innerHTML = `
        <div class="table-wrap">
            <table>
                <thead>
                    <tr><th>id</th><th>name</th><th>server</th><th>type</th><th>condition</th><th>state</th><th></th></tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        </div>
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
                if (!confirm(`${t("rules.confirm.delete")}${ruleId}?`)) return;
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
    wrap.innerHTML = `<p class="empty">${t("loading")}</p>`;

    const serverId = document.getElementById("events-server-filter").value || null;
    const events = await fetchEvents({serverId, limit: 100});
    if (events.length === 0) {
        wrap.innerHTML = `<p class="empty">${t("events.empty")}</p>`;
        return;
    }

    const rows = events
        .map((e) => {
            const statusClass = e.resolved_at ? "status-resolved" : "status-open";
            const statusText = e.resolved_at ? t("events.status.resolved") : t("events.status.open");
            const resolvedAt = e.resolved_at ? new Date(e.resolved_at).toLocaleString() : "—";
            return `
                <tr>
                    <td>#${e.id}</td>
                    <td>#${e.server_id}${e.container_name ? ` / ${escapeHtml(e.container_name)}` : ""}</td>
                    <td>#${e.rule_id}</td>
                    <td>${e.metric_value} (${t("events.threshold")} ${e.threshold_value})</td>
                    <td class="${statusClass}">${statusText}</td>
                    <td>${new Date(e.created_at).toLocaleString()}</td>
                    <td>${escapeHtml(resolvedAt)}</td>
                </tr>
            `;
        })
        .join("");

    wrap.innerHTML = `
        <div class="table-wrap">
            <table>
                <thead>
                    <tr><th>id</th><th>server</th><th>rule</th><th>value</th><th>status</th><th>created</th><th>resolved</th></tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        </div>
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
    btn.textContent = currentLogsWs ? t("logs.disconnect") : t("logs.connect");
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

// ─── Profile modal + TOTP ──────────────────────────────────────────────────

let currentUser = null;

async function openProfileModal() {
    currentUser = await fetchMe();
    if (!currentUser) return;

    document.getElementById("profile-email").textContent = currentUser.email;
    renderTotpStatus();
    document.getElementById("totp-setup-area").hidden = true;
    document.getElementById("profile-modal").hidden = false;
}

function closeProfileModal() {
    document.getElementById("profile-modal").hidden = true;
}

function renderTotpStatus() {
    const enabled = !!currentUser?.totp_enabled;
    document.getElementById("totp-status-text").textContent = enabled
        ? t("profile.totp.on")
        : t("profile.totp.off");
    document.getElementById("totp-enable-btn").hidden = enabled;
    document.getElementById("totp-disable-btn").hidden = !enabled;
}

async function startTotpSetup() {
    const response = await apiFetch("/auth/me/totp/setup", {method: "POST"});
    if (!response.ok) return;
    const data = await response.json();

    document.getElementById("totp-secret").textContent = data.secret;
    renderQrCode(data.otpauth_url, "totp-qr");
    document.getElementById("totp-confirm-code").value = "";
    document.getElementById("totp-error").hidden = true;
    document.getElementById("totp-setup-area").hidden = false;
}

function renderQrCode(text, elementId) {
    const target = document.getElementById(elementId);
    target.innerHTML = "";
    // qrcode-generator: typeNumber=0 → авто, "M" — средний уровень коррекции
    const qr = qrcode(0, "M");
    qr.addData(text);
    qr.make();
    // createImgTag(cellSize=4, margin=4) — 4px на ячейку, тонкая рамка
    target.innerHTML = qr.createImgTag(4, 4);
}

async function confirmTotpEnable() {
    const code = document.getElementById("totp-confirm-code").value.trim();
    if (!code) return;

    const errorEl = document.getElementById("totp-error");
    errorEl.hidden = true;

    const response = await apiFetch("/auth/me/totp/enable", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({code}),
    });
    if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        errorEl.textContent = detail.detail || `${t("error.prefix")} ${response.status}`;
        errorEl.hidden = false;
        return;
    }
    currentUser = await response.json();
    document.getElementById("totp-setup-area").hidden = true;
    renderTotpStatus();
}

async function disableTotp() {
    const password = prompt(t("profile.totp.disable.prompt"));
    if (!password) return;
    const response = await apiFetch("/auth/me/totp/disable", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({password}),
    });
    if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        alert(detail.detail || `${t("error.prefix")} ${response.status}`);
        return;
    }
    currentUser = await response.json();
    renderTotpStatus();
}

// ─── Audit tab ──────────────────────────────────────────────────────────────

let auditCache = [];  // последний загруженный список — фильтруем клиент-сайд

async function loadAuditTab() {
    const wrap = document.getElementById("audit-table-wrap");
    wrap.innerHTML = `<p class="empty">${t("loading")}</p>`;
    auditCache = await fetchAuditLog(200);
    refreshAuditActionFilter();
    renderAuditTable();
}

function refreshAuditActionFilter() {
    const sel = document.getElementById("audit-action-filter");
    const current = sel.value;
    const actions = [...new Set(auditCache.map((e) => e.action))].sort();
    sel.innerHTML = `<option value="">${t("filter.all")}</option>`;
    for (const a of actions) {
        const opt = document.createElement("option");
        opt.value = a;
        opt.textContent = a;
        sel.appendChild(opt);
    }
    sel.value = actions.includes(current) ? current : "";
}

function renderAuditTable() {
    const wrap = document.getElementById("audit-table-wrap");
    const filter = document.getElementById("audit-action-filter").value;
    const entries = filter ? auditCache.filter((e) => e.action === filter) : auditCache;

    if (entries.length === 0) {
        wrap.innerHTML = `<p class="empty">${t("audit.empty")}</p>`;
        return;
    }

    const rows = entries
        .map((e) => {
            const resource = e.resource_type
                ? `${escapeHtml(e.resource_type)}${e.resource_id ? ` #${e.resource_id}` : ""}`
                : "—";
            return `
                <tr>
                    <td>${escapeHtml(new Date(e.created_at).toLocaleString())}</td>
                    <td>${escapeHtml(e.action)}</td>
                    <td>${resource}</td>
                    <td>${escapeHtml(e.ip_address || "—")}</td>
                </tr>
            `;
        })
        .join("");

    wrap.innerHTML = `
        <div class="table-wrap">
            <table>
                <thead>
                    <tr>
                        <th>${t("audit.col.when")}</th>
                        <th>${t("audit.col.action")}</th>
                        <th>${t("audit.col.resource")}</th>
                        <th>${t("audit.col.ip")}</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        </div>
    `;
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
    // i18n init: применяем сохранённый язык + слушаем смену
    const langSel = document.getElementById("lang-switcher");
    langSel.value = currentLang;
    langSel.addEventListener("change", (e) => setLang(e.target.value));
    applyTranslations();

    // theme init: тема уже применена inline-скриптом в <head>, тут только селектор
    const themeSel = document.getElementById("theme-switcher");
    themeSel.value = currentTheme;
    themeSel.addEventListener("change", (e) => setTheme(e.target.value));
    applyTheme();

    document.getElementById("login-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const email = document.getElementById("login-email").value;
        const password = document.getElementById("login-password").value;
        const totpCode = document.getElementById("login-totp").value || null;
        const errorEl = document.getElementById("login-error");
        errorEl.hidden = true;

        try {
            await login(email, password, totpCode);
            const user = await fetchMe();
            if (user) renderDashboard(user);
            else renderLogin();
        } catch (err) {
            if (err.message === "TOTP_REQUIRED") {
                document.getElementById("login-totp-wrap").hidden = false;
                errorEl.textContent = t("login.totp.required");
                errorEl.hidden = false;
                document.getElementById("login-totp").focus();
            } else {
                errorEl.textContent = err.message;
                errorEl.hidden = false;
            }
        }
    });

    document.getElementById("logout-btn").addEventListener("click", logout);

    // Profile modal handlers
    document.getElementById("profile-btn").addEventListener("click", openProfileModal);
    document.getElementById("profile-close").addEventListener("click", closeProfileModal);
    document.getElementById("totp-enable-btn").addEventListener("click", startTotpSetup);
    document.getElementById("totp-disable-btn").addEventListener("click", disableTotp);
    document.getElementById("totp-confirm-btn").addEventListener("click", confirmTotpEnable);

    // «Забыли пароль?» — prompt email, POST /auth/forgot-password
    document.getElementById("forgot-password-link").addEventListener("click", async (e) => {
        e.preventDefault();
        const email = prompt(t("login.forgot.prompt"));
        if (!email) return;
        try {
            await fetch("/auth/forgot-password", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({email}),
            });
        } catch (err) {
            // 200 даже при unknown email — нет смысла раскрывать ошибки сети тут
        }
        const info = document.getElementById("login-info");
        info.textContent = t("login.forgot.sent");
        info.hidden = false;
    });

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

    // Audit tab handlers
    document.getElementById("audit-refresh").addEventListener("click", loadAuditTab);
    document.getElementById("audit-action-filter").addEventListener("change", renderAuditTable);

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
