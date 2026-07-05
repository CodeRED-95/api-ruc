const form = document.getElementById("ruc-form");
const output = document.getElementById("output");
const statusEl = document.getElementById("status");

function render(value) {
  output.textContent = JSON.stringify(value, null, 2);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const apiKey = document.getElementById("apiKey").value.trim();
  const ruc = document.getElementById("ruc").value.trim();
  statusEl.textContent = "Consultando...";
  try {
    const response = await fetch(`/ruc/${encodeURIComponent(ruc)}`, {
      headers: { "X-API-Key": apiKey }
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      statusEl.textContent = data.detail || `Error ${response.status}`;
      render(data);
      return;
    }
    statusEl.textContent = "Consulta exitosa";
    render(data);
  } catch (error) {
    statusEl.textContent = "Error de red o servidor";
    render({ error: String(error) });
  }
});
