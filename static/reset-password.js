// PulseWatch — обработка страницы /reset-password?token=...

const I18N = {
    ru: {
        "title": "Сброс пароля",
        "no_token": "В ссылке нет токена. Открой ссылку из email-сообщения.",
        "new_password": "Новый пароль (минимум 6 символов)",
        "confirm_password": "Подтверди пароль",
        "submit": "Сменить пароль",
        "success_html": 'Пароль обновлён. <a href="/">Войти</a>',
        "mismatch": "Пароли не совпадают",
        "error_prefix": "Ошибка",
    },
    en: {
        "title": "Reset password",
        "no_token": "The link is missing a token. Open the link from your email.",
        "new_password": "New password (minimum 6 characters)",
        "confirm_password": "Confirm password",
        "submit": "Change password",
        "success_html": 'Password updated. <a href="/">Sign in</a>',
        "mismatch": "Passwords don't match",
        "error_prefix": "Error",
    },
};

const lang = localStorage.getItem("pulsewatch.lang")
    || (navigator.language?.startsWith("en") ? "en" : "ru");

function t(key) {
    return I18N[lang]?.[key] ?? I18N.ru[key] ?? key;
}

// Применяем переводы к статичным узлам
document.documentElement.lang = lang;
document.getElementById("title").textContent = t("title");
document.getElementById("no-token-msg").textContent = t("no_token");
document.getElementById("label-new").textContent = t("new_password");
document.getElementById("label-confirm").textContent = t("confirm_password");
document.getElementById("submit-btn").textContent = t("submit");
document.getElementById("success").innerHTML = t("success_html");

const params = new URLSearchParams(location.search);
const token = params.get("token");

const form = document.getElementById("reset-form");
const noTokenMsg = document.getElementById("no-token-msg");
const errorEl = document.getElementById("error");
const successEl = document.getElementById("success");

if (!token) {
    form.hidden = true;
    noTokenMsg.hidden = false;
}

form.addEventListener("submit", async (e) => {
    e.preventDefault();
    errorEl.hidden = true;

    const newPassword = document.getElementById("new-password").value;
    const confirmPassword = document.getElementById("confirm-password").value;

    if (newPassword !== confirmPassword) {
        errorEl.textContent = t("mismatch");
        errorEl.hidden = false;
        return;
    }

    const response = await fetch("/auth/reset-password", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({token, new_password: newPassword}),
    });

    if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        errorEl.textContent = detail.detail || `${t("error_prefix")} ${response.status}`;
        errorEl.hidden = false;
        return;
    }

    form.querySelector("button").disabled = true;
    document.getElementById("new-password").disabled = true;
    document.getElementById("confirm-password").disabled = true;
    successEl.hidden = false;
});
