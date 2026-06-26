// Cliente HTTP fino para a API do MedLaudo-AI.
const BASE = import.meta.env.VITE_API_URL || "http://localhost:8080";

async function json(resp) {
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

export const api = {
  base: BASE,
  listarExames: () => fetch(`${BASE}/exames`).then(json),
  obterExame: (id) => fetch(`${BASE}/exames/${id}`).then(json),
  imagemUrl: (id) => `${BASE}/exames/${id}/imagem`,
  enviarDicom: (arquivo) => {
    const fd = new FormData();
    fd.append("arquivo", arquivo);
    return fetch(`${BASE}/exames`, { method: "POST", body: fd }).then(json);
  },
  assinar: (id, medico) =>
    fetch(`${BASE}/exames/${id}/assinar?medico=${encodeURIComponent(medico)}`, {
      method: "POST",
    }).then(json),
  rejeitar: (id, medico) =>
    fetch(`${BASE}/exames/${id}/rejeitar?medico=${encodeURIComponent(medico)}`, {
      method: "POST",
    }).then(json),
  metricas: () => fetch(`${BASE}/metricas`).then(json),
};
