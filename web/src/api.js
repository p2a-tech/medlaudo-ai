// Cliente HTTP fino para a API do MedLaudo-AI.
import { demoApi } from "./demo.js";

const BASE = import.meta.env.VITE_API_URL || "http://localhost:8080";

// Token JWT do médico autenticado (persistido entre reloads).
let token = localStorage.getItem("medlaudo_token") || null;

// Modo demonstração: usa o seed estático (sem backend), persistido no navegador.
let demo = localStorage.getItem("medlaudo_demo") === "1";

export function setToken(t) {
  token = t;
  if (t) localStorage.setItem("medlaudo_token", t);
  else localStorage.removeItem("medlaudo_token");
}
export function temToken() {
  return !!token;
}
export function setModoDemo(v) {
  demo = v;
  if (v) localStorage.setItem("medlaudo_demo", "1");
  else localStorage.removeItem("medlaudo_demo");
}
export function modoDemo() {
  return demo;
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

const realApi = {
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

// Roteia para a API demo (seed estático) quando o modo demonstração está ativo.
export const api = new Proxy(realApi, {
  get(target, prop) {
    if (demo && prop in demoApi) return demoApi[prop];
    return target[prop];
  },
});
