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

    // Access протух — пробуем refresh и повторяем запрос
    if (response.status === 401 && tokens?.refresh_token) {
        const refreshed = await tryRefresh(tokens.refresh_token);
        if (refreshed) {
            headers.Authorization = `Bearer ${refreshed.access_token}`;
            response = await fetch(url, {...options, headers});
        } else {
            // refresh тоже не сработал — выкидываем юзера на login
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
    const tokens = getTokens();
    if (tokens?.refresh_token) {
        // Best-effort, не ждём ответа критично
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

async function fetchServers() {
    const response = await apiFetch("/servers/me");
    if (!response.ok) return [];
    return response.json();
}

async function fetchMetrics(serverId, limit = 60) {
    const response = await apiFetch(`/servers/${serverId}/metrics?limit=${limit}`);
    if (!response.ok) return [];
    return response.json();
}

// ─── Рендеринг (минимум — переключение видимости секций) ────────────────────

function renderLogin() {
    document.getElementById("login-view").hidden = false;
    document.getElementById("dashboard-view").hidden = true;
    document.getElementById("user-bar").hidden = true;
    document.getElementById("login-error").hidden = true;
    document.getElementById("login-form").reset();
}

async function renderDashboard(user) {
    document.getElementById("login-view").hidden = true;
    document.getElementById("dashboard-view").hidden = false;
    document.getElementById("user-bar").hidden = false;
    document.getElementById("user-email").textContent = user.email;

    const servers = await fetchServers();
    renderServers(servers);
}

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

// ─── Detail panel + Chart.js + WebSocket ───────────────────────────────────

const MAX_POINTS = 60;

let currentChart = null;       // экземпляр Chart, нужен чтобы destroy перед новым
let selectedServerId = null;   // id выбранного сервера
let currentWs = null;          // открытый WebSocket, нужен чтобы закрыть при смене

async function selectServer(server) {
    selectedServerId = server.id;

    // Подсветка выбранной карточки
    document.querySelectorAll(".server-card").forEach((el) => {
        el.classList.toggle("selected", Number(el.dataset.serverId) === server.id);
    });

    document.getElementById("detail-panel").hidden = false;
    document.getElementById("detail-title").textContent =
        `${server.name} (#${server.id}) — реал-тайм`;

    const metrics = await fetchMetrics(server.id, MAX_POINTS);
    // API возвращает новые-сверху; для графика хотим старое-слева, новое-справа
    metrics.reverse();
    renderChart(metrics);
    openMetricsWs(server.id);
}

function openMetricsWs(serverId) {
    // Закрываем предыдущее соединение, если было
    closeMetricsWs();

    const tokens = getTokens();
    if (!tokens?.access_token) return;

    const wsProto = location.protocol === "https:" ? "wss" : "ws";
    const url = `${wsProto}://${location.host}/ws/metrics/${serverId}?token=${encodeURIComponent(tokens.access_token)}`;
    const ws = new WebSocket(url);
    currentWs = ws;

    ws.onmessage = (event) => {
        if (selectedServerId !== serverId) return;  // пользователь успел переключиться
        try {
            const payload = JSON.parse(event.data);
            if (payload.type === "metric") {
                appendPoint(payload);
            }
        } catch (err) {
            console.warn("ws: bad payload", err);
        }
    };

    ws.onclose = async (event) => {
        if (currentWs !== ws) return;  // уже заменили — игнорируем

        // Code 1008 → server refused (вероятно протухший access). Пробуем refresh
        // и переподключиться один раз.
        if (event.code === 1008 && tokens?.refresh_token) {
            const refreshed = await tryRefresh(tokens.refresh_token);
            if (refreshed && selectedServerId === serverId) {
                openMetricsWs(serverId);
            }
        }
    };

    ws.onerror = () => {
        // Логируем; полноценный reconnect-loop делать не будем для учебного проекта
        console.warn("ws: error");
    };
}

function closeMetricsWs() {
    if (currentWs) {
        currentWs.onmessage = null;
        currentWs.onclose = null;
        currentWs.onerror = null;
        try {
            currentWs.close();
        } catch {
            // already closed
        }
        currentWs = null;
    }
}

function appendPoint(metric) {
    if (!currentChart) return;

    const label = new Date(metric.collected_at).toLocaleTimeString();
    const data = currentChart.data;
    data.labels.push(label);
    data.datasets[0].data.push(metric.cpu_percent);
    data.datasets[1].data.push(metric.memory_percent);
    data.datasets[2].data.push(metric.disk_percent);

    // Скользящее окно: оставляем только последние MAX_POINTS
    while (data.labels.length > MAX_POINTS) {
        data.labels.shift();
        for (const ds of data.datasets) ds.data.shift();
    }

    currentChart.update("none");  // 'none' = без анимации, для плавного real-time
}

function renderChart(metrics) {
    const ctx = document.getElementById("metrics-chart");

    const labels = metrics.map((m) => new Date(m.collected_at).toLocaleTimeString());
    const cpu = metrics.map((m) => m.cpu_percent);
    const mem = metrics.map((m) => m.memory_percent);
    const disk = metrics.map((m) => m.disk_percent);

    // Уничтожаем предыдущий график, иначе они накладываются на canvas
    if (currentChart) currentChart.destroy();

    currentChart = new Chart(ctx, {
        type: "line",
        data: {
            labels,
            datasets: [
                {label: "CPU %", data: cpu, borderColor: "#f38ba8", backgroundColor: "transparent", tension: 0.2},
                {label: "Memory %", data: mem, borderColor: "#89b4fa", backgroundColor: "transparent", tension: 0.2},
                {label: "Disk %", data: disk, borderColor: "#a6e3a1", backgroundColor: "transparent", tension: 0.2},
            ],
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
    });
}

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = String(str);
    return div.innerHTML;
}

// ─── Точка входа ────────────────────────────────────────────────────────────

async function init() {
    // Login form submit
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

    // Logout button
    document.getElementById("logout-btn").addEventListener("click", logout);

    // Если уже залогинены — сразу рисуем дашборд
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
