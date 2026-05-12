// PulseWatch — обработка страницы /reset-password?token=...

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
    const confirm = document.getElementById("confirm-password").value;

    if (newPassword !== confirm) {
        errorEl.textContent = "Пароли не совпадают";
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
        errorEl.textContent = detail.detail || `Ошибка ${response.status}`;
        errorEl.hidden = false;
        return;
    }

    form.querySelector("button").disabled = true;
    document.getElementById("new-password").disabled = true;
    document.getElementById("confirm-password").disabled = true;
    successEl.hidden = false;
});
