const adminForm = document.getElementById("admin-form");
const adminOutput = document.getElementById("adminOutput");
const adminStatus = document.getElementById("adminStatus");

adminForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const apiKey = document.getElementById("adminKey").value.trim();
  const nombre = document.getElementById("nombre").value.trim();
  const descripcion = document.getElementById("descripcion").value.trim();
  const limite_diario = Number(document.getElementById("limiteDiario").value || 1000);
  const limite_por_minuto = Number(document.getElementById("limiteMinuto").value || 60);

  adminStatus.textContent = "Generando token...";
  try {
    const response = await fetch("/admin/api-keys", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Admin-Key": apiKey
      },
      body: JSON.stringify({ nombre, descripcion, limite_diario, limite_por_minuto })
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      adminStatus.textContent = data.detail || `Error ${response.status}`;
      adminOutput.textContent = JSON.stringify(data, null, 2);
      return;
    }
    adminStatus.textContent = "Token generado";
    adminOutput.textContent = JSON.stringify(data, null, 2);
  } catch (error) {
    adminStatus.textContent = "Error de red o servidor";
    adminOutput.textContent = JSON.stringify({ error: String(error) }, null, 2);
  }
});
