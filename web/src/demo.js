// Modo demonstração: seed estático + "API" client-side com o MESMO formato da
// API real. Permite logar e navegar o sistema sem backend (ex.: no deploy
// Vercel sem GPU). Os dados são fictícios e ficam só na memória do navegador.

const CREDENCIAL_DEMO = { email: "demo@medlaudo.ai", senha: "demo" };
const MEDICO_DEMO = { id: "demo", nome: "Dr. Demonstração", crm: "DEMO-RS" };

// Imagem de raio-X estilizada (SVG inline) para o viewer — claramente um
// placeholder de demonstração, não uma imagem clínica real.
const RAIOX_SVG = `<svg xmlns='http://www.w3.org/2000/svg' width='500' height='500'>
<rect width='500' height='500' fill='#0a0a0a'/>
<g fill='none' stroke='#9aa6b2' stroke-width='3' opacity='0.55'>
<path d='M250 70 V430'/>
${Array.from({ length: 9 })
  .map((_, i) => {
    const y = 110 + i * 32;
    return `<path d='M250 ${y} Q150 ${y + 18} 70 ${y + 70}'/><path d='M250 ${y} Q350 ${y + 18} 430 ${y + 70}'/>`;
  })
  .join("")}
</g>
<ellipse cx='250' cy='360' rx='70' ry='90' fill='#1b1b1b' opacity='0.6'/>
<text x='250' y='480' fill='#5b6b7b' font-family='sans-serif' font-size='16'
 text-anchor='middle'>RADIOGRAFIA — DEMONSTRAÇÃO</text>
</svg>`;
const RAIOX_DATA_URL = `data:image/svg+xml;utf8,${encodeURIComponent(RAIOX_SVG)}`;

function achado(p = {}) {
  return {
    presenca: "ausente",
    lateralidade: "nao_aplicavel",
    gravidade: "normal",
    descricao: null,
    confianca: 0,
    ...p,
  };
}

function laudoBase(extra = {}) {
  return {
    qualidade_tecnica: { adequada: true, incidencia: "PA", observacoes: "Inspiração adequada." },
    achados: {
      consolidacao: achado(),
      opacidade_intersticial: achado(),
      nodulo_ou_massa: achado(),
      atelectasia: achado(),
      derrame_pleural: achado(),
      pneumotorax: achado(),
      cardiomegalia: achado(),
      alargamento_mediastinal: achado(),
      congestao_pulmonar: achado(),
      fratura: achado(),
      dispositivos: achado(),
    },
    impressao: "",
    achados_criticos: [],
    gerado_por_ia: true,
    validado_por_medico: false,
    ...extra,
  };
}

const CRITICOS = { pneumotorax: "Pneumotórax", derrame_pleural: "Derrame pleural volumoso" };
function recalcularCriticos(achados) {
  const out = [];
  for (const [campo, rotulo] of Object.entries(CRITICOS)) {
    const a = achados[campo];
    if (a?.presenca === "presente" && ["moderado", "acentuado", "critico"].includes(a.gravidade))
      out.push(rotulo);
  }
  return out;
}

// Estado inicial (recriado a cada ativação do modo demo).
function seed() {
  const l1 = laudoBase({
    achados: {
      ...laudoBase().achados,
      derrame_pleural: achado({
        presenca: "presente", lateralidade: "direita", gravidade: "moderado",
        descricao: "Velamento do seio costofrênico direito.", confianca: 0.78,
      }),
      cardiomegalia: achado({
        presenca: "indeterminado", gravidade: "leve",
        descricao: "Índice cardiotorácico no limite superior.", confianca: 0.55,
      }),
    },
    impressao:
      "Derrame pleural de pequeno a moderado volume à direita. Área cardíaca no limite superior. " +
      "Correlacionar clinicamente. [RASCUNHO GERADO POR IA — NÃO VALIDADO]",
    achados_criticos: ["Derrame pleural volumoso"],
  });
  const l2 = laudoBase({
    impressao: "Tórax sem alterações pleuropulmonares agudas. [RASCUNHO GERADO POR IA — NÃO VALIDADO]",
  });
  return [
    {
      id: "demo-001", status: "rascunho_pronto", critico: true, modalidade: "DX",
      incidencia: "PA", criado_em: "2026-06-26T12:00:00Z",
      laudo_ia: structuredClone(l1), laudo_final: null, medico_responsavel: null,
    },
    {
      id: "demo-002", status: "rascunho_pronto", critico: false, modalidade: "DX",
      incidencia: "PA", criado_em: "2026-06-26T11:30:00Z",
      laudo_ia: structuredClone(l2), laudo_final: null, medico_responsavel: null,
    },
  ];
}

let _exames = seed();
function reset() {
  _exames = seed();
}
function ok(v) {
  return Promise.resolve(v);
}
function buscar(id) {
  return _exames.find((e) => e.id === id);
}

export const credenciaisDemo = CREDENCIAL_DEMO;
export const medicoDemo = MEDICO_DEMO;
export function ehLoginDemo(email, senha) {
  return email === CREDENCIAL_DEMO.email && senha === CREDENCIAL_DEMO.senha;
}

// "API" demo — mesma assinatura da real (web/src/api.js).
export const demoApi = {
  reset,
  login: () => ok({ token: "demo-token", medico: MEDICO_DEMO }),
  listarExames: () =>
    ok(
      [..._exames]
        .sort((a, b) => Number(b.critico) - Number(a.critico) || b.criado_em.localeCompare(a.criado_em))
        .map(({ laudo_ia, laudo_final, medico_responsavel, ...resumo }) => resumo)
    ),
  obterExame: (id) => ok(structuredClone(buscar(id) || null)),
  imagemUrl: () => RAIOX_DATA_URL,
  pdfUrl: () => "#",
  dicomUrl: () => "#",
  editarLaudo: (id, laudo) => {
    const e = buscar(id);
    laudo.achados_criticos = recalcularCriticos(laudo.achados);
    e.laudo_final = structuredClone(laudo);
    e.critico = laudo.achados_criticos.length > 0;
    e.status = "em_revisao";
    e.medico_responsavel = MEDICO_DEMO.nome;
    return ok({ ok: true, achados_criticos: laudo.achados_criticos });
  },
  assinar: (id) => {
    const e = buscar(id);
    const final = structuredClone(e.laudo_final || e.laudo_ia || {});
    final.validado_por_medico = true;
    final.assinado_por_crm = MEDICO_DEMO.crm;
    e.laudo_final = final;
    e.medico_responsavel = MEDICO_DEMO.nome;
    e.status = "assinado";
    return ok({ ok: true, pacs: { ok: true, detalhe: "(demonstração) envio ao PACS simulado" } });
  },
  rejeitar: (id) => {
    buscar(id).status = "rejeitado";
    return ok({ ok: true });
  },
  enviarPacs: () => ok({ ok: true, detalhe: "(demonstração) envio ao PACS simulado" }),
  metricas: () => {
    const total = _exames.length;
    const assinados = _exames.filter((e) => e.status === "assinado").length;
    return ok({
      total_exames: total,
      assinados,
      rejeitados: _exames.filter((e) => e.status === "rejeitado").length,
      criticos_detectados: _exames.filter((e) => e.critico).length,
      taxa_aproveitamento: total ? Number((assinados / total).toFixed(3)) : 0,
    });
  },
};
