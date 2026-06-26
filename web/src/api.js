// Cliente HTTP fino para a API do MedLaudo-AI.
const BASE = import.meta.env.VITE_API_URL || "http://localhost:8080";

// Token JWT do médico autenticado (persistido entre reloads).
let token = localStorage.getItem("medlaudo_token") || null;

export function setToken(t) {
  token = t;
  if (t) localStorage.setItem("medlaudo_token", t);
  else localStorage.removeItem("medlaudo_token");
}
export function temToken() {
  return !!token;
}

function authHeaders(extra = {}) {
  return token ? { ...extra, Authorization: `Bearer ${token}` } : extra;
}

async function json(resp) {
  if (resp.status === 401 || resp.status === 403) {
    setToken(null); // token expirou/ inválido -> volta ao login
    throw new Error("nao_autenticado");
  }
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

export const api = {
  base: BASE,
  login: (email, senha) =>
    fetch(`${BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, senha }),
    }).then(json),
  listarExames: () => fetch(`${BASE}/exames`).then(json),
  obterExame: (id) => fetch(`${BASE}/exames/${id}`).then(json),
  imagemUrl: (id) => `${BASE}/exames/${id}/imagem`,
  pdfUrl: (id) => `${BASE}/exames/${id}/laudo.pdf`,
  dicomUrl: (id) => `${BASE}/exames/${id}/laudo.dcm`,
  enviarDicom: (arquivo) => {
    const fd = new FormData();
    fd.append("arquivo", arquivo);
    return fetch(`${BASE}/exames`, { method: "POST", body: fd }).then(json);
  },
  editarLaudo: (id, laudo) =>
    fetch(`${BASE}/exames/${id}/laudo`, {
      method: "PUT",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(laudo),
    }).then(json),
  assinar: (id) =>
    fetch(`${BASE}/exames/${id}/assinar`, {
      method: "POST",
      headers: authHeaders(),
    }).then(json),
  rejeitar: (id) =>
    fetch(`${BASE}/exames/${id}/rejeitar`, {
      method: "POST",
      headers: authHeaders(),
    }).then(json),
  enviarPacs: (id) =>
    fetch(`${BASE}/exames/${id}/enviar-pacs`, {
      method: "POST",
      headers: authHeaders(),
    }).then(json),
  metricas: () => fetch(`${BASE}/metricas`).then(json),
};
