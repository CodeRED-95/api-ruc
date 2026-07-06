const STORAGE_KEY = "sunat_admin_key";

const el = (id) => document.getElementById(id);
const adminKeyInput = el("adminKey");
const saveAdminKeyBtn = el("saveAdminKey");
const clearAdminKeyBtn = el("clearAdminKey");
const createForm = el("createForm");
const tokensBody = el("tokensBody");
const statusBox = el("status");
const createMessage = el("createMessage");
const tokenDialog = el("tokenDialog");
const tokenDialogText = el("tokenDialogText");
const tokenDialogCopy = el("tokenDialogCopy");
const tokenDialogClose = el("tokenDialogClose");
const refreshBtn = el("refreshBtn");

function setStatus(message, error = false) {
  statusBox.textContent = message;
  statusBox.style.color = error ? "#fb7185" : "";
}

function setCreateMessage(message, error = false) {
  createMessage.textContent = message;
  createMessage.style.color = error ? "#fb7185" : "";
}

function getAdminKey() {
  return adminKeyInput.value.trim();
}

function saveLocalAdminKey() {
  localStorage.setItem(STORAGE_KEY, getAdminKey());
  setStatus("Admin key guardada localmente en el navegador.");
}

function loadLocalAdminKey() {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved) adminKeyInput.value = saved;
}

function clearLocalAdminKey() {
  localStorage.removeItem(STORAGE_KEY);
  adminKeyInput.value = "";
  setStatus("Admin key eliminada del navegador.");
}

function adminHeaders() {
  const key = getAdminKey();
  if (!key) throw new Error("Debes ingresar X-Admin-Key");
  return {
    "Content-Type": "application/json",
    "X-Admin-Key": key,
  };
}

async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      alert("Copiado");
      return true;
    }

    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();

    const ok = document.execCommand("copy");
    document.body.removeChild(textarea);

    if (ok) {
      alert("Copiado");
      return true;
    }

    alert("No se pudo copiar. Selecciona el token y cópialo manualmente.");
    return false;
  } catch (error) {
    alert("No se pudo copiar. Selecciona el token y cópialo manualmente.");
    return false;
  }
}

async function apiFetch(url, options = {}) {
  const headers = { ...(options.headers || {}), ...adminHeaders() };
  const response = await fetch(url, { ...options, headers });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = data.detail || data.message || `Error ${response.status}`;
    throw new Error(message);
  }
  return data;
}

function formatDate(value) {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

function statusPill(active) {
  return active
    ? '<span class="pill ok">Activo</span>'
    : '<span class="pill off">Desactivado</span>';
}

function tokenActions(token) {
  const enableLabel = token.is_active ? "Desactivar" : "Activar";
  const enableAction = token.is_active ? "disable" : "enable";
  return `
    <div class="actions-cell">
      <button type="button" data-action="${enableAction}" data-id="${token.id}">${enableLabel}</button>
      <button type="button" data-action="delete" data-id="${token.id}">Eliminar</button>
    </div>
  `;
}

function rowHtml(token) {
  return `
    <tr>
      <td>${token.id}</td>
      <td>${token.nombre || ""}</td>
      <td><code>${token.token_preview || ""}</code></td>
      <td>${statusPill(token.is_active)}</td>
      <td>${token.total_requests ?? 0}<br><small class="muted">Hoy: ${token.requests_today ?? "-"}</small><br><small class="muted">Min: ${token.requests_this_minute ?? "-"}</small></td>
      <td>${token.daily_limit ?? token.limite_diario ?? "-"}</td>
      <td>${token.minute_limit ?? token.limite_por_minuto ?? "-"}</td>
      <td>${formatDate(token.created_at || token.fecha_creacion)}</td>
      <td>${formatDate(token.last_used_at || token.ultimo_uso)}</td>
      <td>${tokenActions(token)}</td>
    </tr>
  `;
}

async function loadTokens() {
  setStatus("Cargando tokens...");
  const tokens = await apiFetch("/admin/tokens", { method: "GET" });
  tokensBody.innerHTML = tokens.map(rowHtml).join("") || `<tr><td colspan="10">Sin tokens</td></tr>`;
  setStatus(`Tokens cargados: ${tokens.length}`);
}

async function createToken(payload) {
  const token = await apiFetch("/admin/tokens", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  tokenDialogText.textContent = token.api_key || "";
  tokenDialog.showModal();
  setCreateMessage("Token generado correctamente.");
  await loadTokens();
}

async function runAction(action, id) {
  const map = {
    disable: { url: `/admin/tokens/${id}/disable`, method: "PATCH" },
    enable: { url: `/admin/tokens/${id}/enable`, method: "PATCH" },
    delete: { url: `/admin/tokens/${id}`, method: "DELETE" },
    refresh: { url: `/admin/tokens/${id}`, method: "GET" },
  };
  const item = map[action];
  if (!item) return;
  if (action === "delete" && !confirm("¿Eliminar este token?")) return;
  if (action === "refresh") {
    const token = await apiFetch(item.url, { method: item.method });
    setStatus(`Token ${id} actualizado.`);
    return token;
  }
  await apiFetch(item.url, { method: item.method });
  setStatus(`Acción aplicada: ${action} sobre token ${id}.`);
  await loadTokens();
}

tokensBody.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const { action, id } = button.dataset;
  try {
    await runAction(action, id);
  } catch (error) {
    setStatus(error.message, true);
  }
});

createForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await createToken({
      nombre: el("nombre").value.trim(),
      descripcion: el("descripcion").value.trim(),
      daily_limit: Number(el("dailyLimit").value || 1000),
      minute_limit: Number(el("minuteLimit").value || 60),
    });
  } catch (error) {
    setCreateMessage(error.message, true);
  }
});

saveAdminKeyBtn.addEventListener("click", saveLocalAdminKey);
clearAdminKeyBtn.addEventListener("click", clearLocalAdminKey);
refreshBtn.addEventListener("click", async () => {
  try {
    await loadTokens();
  } catch (error) {
    setStatus(error.message, true);
  }
});
tokenDialogClose.addEventListener("click", () => {
  tokenDialog.close();
});
tokenDialog.addEventListener("click", (event) => {
  if (event.target === tokenDialog) {
    tokenDialog.close();
  }
});
tokenDialogCopy.addEventListener("click", async () => {
  try {
    const token = tokenDialogText.textContent || "";
    if (!token) throw new Error("No hay token para copiar");
    await copyText(token);
    setCreateMessage("Token generado copiado.");
  } catch (error) {
    setCreateMessage(error.message, true);
  }
});

loadLocalAdminKey();
loadTokens().catch((error) => setStatus(error.message, true));
