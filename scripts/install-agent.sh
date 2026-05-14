#!/usr/bin/env bash
# PulseWatch agent installer for Debian/Ubuntu.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/IDRENAL/PulseWatch/master/scripts/install-agent.sh \
#     | sudo PW_URL=http://192.168.0.4:8000 PW_KEY=<api-key> bash
#
# Or interactive:
#   curl -fsSL https://raw.githubusercontent.com/IDRENAL/PulseWatch/master/scripts/install-agent.sh \
#     | sudo bash
#
# Re-running is safe: existing /etc/pulsewatch/agent.env is preserved.

set -euo pipefail

PW_REPO="${PW_REPO:-IDRENAL/PulseWatch}"
PW_BRANCH="${PW_BRANCH:-master}"
PW_INSTALL_DIR="${PW_INSTALL_DIR:-/opt/pulsewatch}"
PW_ETC_DIR="${PW_ETC_DIR:-/etc/pulsewatch}"
PW_USER="${PW_USER:-pulsewatch}"
PW_SERVICE="${PW_SERVICE:-pulsewatch-agent}"

RAW_URL="https://raw.githubusercontent.com/${PW_REPO}/${PW_BRANCH}"

AGENT_FILES=(
    "agent/__init__.py"
    "agent/agent.py"
    "agent/config.py"
    "agent/sender.py"
    "agent/logs_streamer.py"
    "agent/collectors/__init__.py"
    "agent/collectors/system.py"
    "agent/collectors/docker_collector.py"
    "agent/collectors/logs_collector.py"
    "agent/requirements.txt"
)

red()   { printf "\033[0;31m%s\033[0m\n" "$*"; }
green() { printf "\033[0;32m%s\033[0m\n" "$*"; }
blue()  { printf "\033[0;34m%s\033[0m\n" "$*"; }

die() { red "❌ $*"; exit 1; }

[[ $EUID -eq 0 ]] || die "Запусти под root (sudo)"
command -v apt-get >/dev/null || die "Поддерживаются только Debian/Ubuntu (нужен apt-get)"
command -v curl >/dev/null || die "Нужен curl: apt-get install -y curl"

blue "▶ Устанавливаю системные пакеты"
apt-get update -qq
apt-get install -y -qq python3 python3-venv ca-certificates >/dev/null

if ! id -u "$PW_USER" >/dev/null 2>&1; then
    blue "▶ Создаю пользователя $PW_USER"
    useradd --system --shell /usr/sbin/nologin --home-dir "$PW_INSTALL_DIR" "$PW_USER"
fi

mkdir -p "$PW_INSTALL_DIR" "$PW_ETC_DIR"

blue "▶ Скачиваю файлы агента из ${PW_REPO}@${PW_BRANCH}"
for rel in "${AGENT_FILES[@]}"; do
    dst="${PW_INSTALL_DIR}/${rel}"
    mkdir -p "$(dirname "$dst")"
    curl -fsSL "${RAW_URL}/${rel}" -o "$dst" || die "Не смог скачать ${rel}"
done

blue "▶ Поднимаю venv и ставлю зависимости"
if [[ ! -d "${PW_INSTALL_DIR}/.venv" ]]; then
    python3 -m venv "${PW_INSTALL_DIR}/.venv"
fi
"${PW_INSTALL_DIR}/.venv/bin/pip" install --quiet --upgrade pip
"${PW_INSTALL_DIR}/.venv/bin/pip" install --quiet -r "${PW_INSTALL_DIR}/agent/requirements.txt"

# Конфиг: не перезатираем существующие значения, добавляем недостающие
ENV_FILE="${PW_ETC_DIR}/agent.env"
touch "$ENV_FILE"
chmod 600 "$ENV_FILE"

get_env() { grep -E "^${1}=" "$ENV_FILE" 2>/dev/null | tail -n1 | cut -d= -f2- | tr -d '"'; }

EXIST_URL="$(get_env AGENT_API_URL || true)"
EXIST_KEY="$(get_env AGENT_API_KEY || true)"

PW_URL="${PW_URL:-${EXIST_URL:-}}"
PW_KEY="${PW_KEY:-${EXIST_KEY:-}}"

if [[ -z "$PW_URL" ]]; then
    read -rp "URL бэкенда PulseWatch (например http://192.168.0.4:8000): " PW_URL
fi
if [[ -z "$PW_KEY" ]]; then
    read -rp "API-ключ сервера (из UI после регистрации): " PW_KEY
fi

[[ -n "$PW_URL" && -n "$PW_KEY" ]] || die "PW_URL и PW_KEY обязательны"

blue "▶ Обновляю ${ENV_FILE} (остальные ключи не трогаю)"
sed -i "/^AGENT_API_URL=/d; /^AGENT_API_KEY=/d" "$ENV_FILE"
{
    echo "AGENT_API_URL=${PW_URL}"
    echo "AGENT_API_KEY=${PW_KEY}"
} >> "$ENV_FILE"
chmod 600 "$ENV_FILE"
chown root:"$PW_USER" "$ENV_FILE"

blue "▶ Устанавливаю systemd-юнит"
install -m 644 "${PW_INSTALL_DIR}/agent/pulsewatch-agent.service" "/etc/systemd/system/${PW_SERVICE}.service"
chown -R "$PW_USER":"$PW_USER" "$PW_INSTALL_DIR"

systemctl daemon-reload
systemctl enable --now "$PW_SERVICE"

blue "▶ Жду 15с и проверяю, что метрики уходят"
sleep 15

if ! systemctl is-active --quiet "$PW_SERVICE"; then
    red "❌ Сервис не запустился. Смотри: journalctl -u ${PW_SERVICE} -n 50"
    exit 1
fi

# Проверка через бэкенд: дёрнем /servers/me — last_seen_at должен быть свежим.
# Без логина не сможем — пропустим, ограничимся локальной проверкой статуса.
green "✅ Агент запущен и активен"
green "   Логи: journalctl -u ${PW_SERVICE} -f"
green "   Конфиг: ${ENV_FILE}"
green "   Открой UI и убедись, что сервер появился со свежим last_seen"
