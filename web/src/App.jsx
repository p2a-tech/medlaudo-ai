import { useEffect, useState, useCallback } from "react";
import { api } from "./api.js";

// Rótulos legíveis para os campos do schema de achados.
const ROTULOS = {
  consolidacao: "Consolidação",
  opacidade_intersticial: "Opacidade intersticial",
  nodulo_ou_massa: "Nódulo ou massa",
  atelectasia: "Atelectasia",
  derrame_pleural: "Derrame pleural",
  pneumotorax: "Pneumotórax",
  cardiomegalia: "Cardiomegalia",
  alargamento_mediastinal: "Alargamento mediastinal",
  congestao_pulmonar: "Congestão pulmonar",
  fratura: "Fratura",
  dispositivos: "Dispositivos",
};
// Ordem de exibição = ordem da leitura sistemática.
const CAMPOS_ACHADO = Object.keys(ROTULOS);

const PRESENCAS = ["ausente", "presente", "indeterminado"];
const LATERALIDADES = ["nao_aplicavel", "direita", "esquerda", "bilateral"];
const GRAVIDADES = ["normal", "leve", "moderado", "acentuado", "critico"];

function Badge({ children, tom }) {
  return <span className={`badge badge-${tom}`}>{children}</span>;
}

function StatusOffline() {
  return (
    <div className="banner-erro">
      API offline. Suba o backend com <code>docker compose up</code> (modo mock
      roda sem GPU) ou <code>uvicorn app.main:app</code> dentro de <code>api/</code>.
    </div>
  );
}

// ---- Visão somente-leitura (após assinatura) -------------------------------

function ListaAchados({ achados }) {
  if (!achados) return null;
  const presentes = CAMPOS_ACHADO.filter(
    (c) => achados[c] && achados[c].presenca !== "ausente"
  );
  if (presentes.length === 0)
    return <p className="vazio">Nenhum achado relevante.</p>;

  return (
    <ul className="achados">
      {presentes.map((campo) => {
        const a = achados[campo];
        return (
          <li key={campo} className={`achado achado-${a.presenca}`}>
            <div className="achado-topo">
              <strong>{ROTULOS[campo]}</strong>
              <span className="achado-meta">
                {a.presenca === "indeterminado" && (
                  <Badge tom="alerta">indeterminado</Badge>
                )}
                {a.lateralidade !== "nao_aplicavel" && (
                  <Badge tom="neutro">{a.lateralidade}</Badge>
                )}
                <Badge tom={a.gravidade === "critico" ? "critico" : "neutro"}>
                  {a.gravidade}
                </Badge>
              </span>
            </div>
            {a.descricao && <p className="achado-desc">{a.descricao}</p>}
          </li>
        );
      })}
    </ul>
  );
}

// ---- Editor campo a campo (antes da assinatura) ----------------------------

function AchadoEditor({ campo, achado, ia, onChange }) {
  const set = (chave, valor) => onChange(campo, { ...achado, [chave]: valor });
  const editado =
    ia &&
    (ia.presenca !== achado.presenca ||
      ia.gravidade !== achado.gravidade ||
      ia.lateralidade !== achado.lateralidade ||
      (ia.descricao || "") !== (achado.descricao || ""));

  return (
    <div className={`achado-edit ${achado.presenca !== "ausente" ? "ativo" : ""}`}>
      <div className="achado-edit-topo">
        <label className="achado-nome">
          {ROTULOS[campo]}
          {editado && <span className="tag-editado" title="Alterado pelo médico">●</span>}
        </label>
        <select
          value={achado.presenca}
          onChange={(e) => set("presenca", e.target.value)}
          className={`sel sel-${achado.presenca}`}
        >
          {PRESENCAS.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </div>

      {achado.presenca !== "ausente" && (
        <div className="achado-edit-campos">
          <select
            value={achado.lateralidade}
            onChange={(e) => set("lateralidade", e.target.value)}
            className="sel"
          >
            {LATERALIDADES.map((l) => (
              <option key={l} value={l}>
                {l === "nao_aplicavel" ? "lado n/a" : l}
              </option>
            ))}
          </select>
          <select
            value={achado.gravidade}
            onChange={(e) => set("gravidade", e.target.value)}
            className={`sel ${achado.gravidade === "critico" ? "sel-critico" : ""}`}
          >
            {GRAVIDADES.map((g) => (
              <option key={g} value={g}>
                {g}
              </option>
            ))}
          </select>
          <input
            className="inp"
            placeholder="descrição"
            value={achado.descricao || ""}
            onChange={(e) => set("descricao", e.target.value)}
          />
        </div>
      )}
    </div>
  );
}

function Detalhe({ id, onMudou }) {
  const [exame, setExame] = useState(null);
  const [edicao, setEdicao] = useState(null); // cópia de trabalho do laudo
  const [salvando, setSalvando] = useState(false);

  const recarregar = useCallback(() => {
    if (!id) return;
    api
      .obterExame(id)
      .then((e) => {
        setExame(e);
        setEdicao(structuredClone(e.laudo_final || e.laudo_ia || null));
      })
      .catch(() => setExame(null));
  }, [id]);

  useEffect(() => {
    recarregar();
  }, [recarregar]);

  if (!id)
    return <div className="detalhe vazio-central">Selecione um exame na worklist.</div>;
  if (!exame) return <div className="detalhe vazio-central">Carregando…</div>;

  const assinado = !!exame.laudo_final?.validado_por_medico;
  const ia = exame.laudo_ia;

  const setAchado = (campo, novo) =>
    setEdicao((prev) => ({
      ...prev,
      achados: { ...prev.achados, [campo]: novo },
    }));

  const salvar = async (depois) => {
    setSalvando(true);
    try {
      await api.editarLaudo(id, edicao, "Dr. Revisor");
      if (depois) await depois();
      onMudou();
      recarregar();
    } finally {
      setSalvando(false);
    }
  };

  const assinar = () => salvar(() => api.assinar(id, "Dr. Revisor"));
  const rejeitar = async () => {
    await api.rejeitar(id, "Dr. Revisor");
    onMudou();
    recarregar();
  };

  // Pré-visualização de criticidade enquanto edita (cálculo idêntico ao backend).
  const criticosLocais = edicao
    ? CAMPOS_ACHADO.filter(
        (c) =>
          (c === "pneumotorax" || c === "derrame_pleural") &&
          edicao.achados[c]?.presenca === "presente" &&
          ["moderado", "acentuado", "critico"].includes(edicao.achados[c]?.gravidade)
      ).map((c) => ROTULOS[c])
    : [];

  return (
    <div className="detalhe">
      <div className="viewer">
        <img src={api.imagemUrl(id)} alt="Radiografia de tórax" />
      </div>

      <div className="laudo">
        <div className="laudo-cabecalho">
          <h2>Laudo</h2>
          {assinado ? (
            <Badge tom="ok">Assinado · {exame.medico_responsavel}</Badge>
          ) : (
            <Badge tom="alerta">Rascunho IA — não validado</Badge>
          )}
        </div>

        {criticosLocais.length > 0 && (
          <div className="banner-critico">
            ⚠ Achado(s) crítico(s): {criticosLocais.join(", ")}
          </div>
        )}

        {/* -------- Modo somente-leitura (assinado) -------- */}
        {assinado && edicao && (
          <>
            <section>
              <h3>Qualidade técnica</h3>
              <p>
                {edicao.qualidade_tecnica?.incidencia || "—"} ·{" "}
                {edicao.qualidade_tecnica?.adequada ? "adequada" : "inadequada"}
              </p>
            </section>
            <section>
              <h3>Achados</h3>
              <ListaAchados achados={edicao.achados} />
            </section>
            <section>
              <h3>Impressão</h3>
              <p className="impressao">{edicao.impressao || "—"}</p>
            </section>
            <div className="downloads">
              <a className="btn btn-secundario" href={api.pdfUrl(id)} target="_blank" rel="noreferrer">
                ⬇ Baixar PDF
              </a>
              <a className="btn btn-secundario" href={api.dicomUrl(id)}>
                ⬇ DICOM p/ PACS
              </a>
            </div>
          </>
        )}

        {/* -------- Modo edição (não assinado) -------- */}
        {!assinado && edicao && (
          <>
            <section>
              <h3>Qualidade técnica</h3>
              <div className="qt-edit">
                <input
                  className="inp"
                  placeholder="incidência (PA/AP/perfil)"
                  value={edicao.qualidade_tecnica?.incidencia || ""}
                  onChange={(e) =>
                    setEdicao((p) => ({
                      ...p,
                      qualidade_tecnica: {
                        ...p.qualidade_tecnica,
                        incidencia: e.target.value,
                      },
                    }))
                  }
                />
                <label className="check">
                  <input
                    type="checkbox"
                    checked={edicao.qualidade_tecnica?.adequada ?? true}
                    onChange={(e) =>
                      setEdicao((p) => ({
                        ...p,
                        qualidade_tecnica: {
                          ...p.qualidade_tecnica,
                          adequada: e.target.checked,
                        },
                      }))
                    }
                  />
                  adequada
                </label>
              </div>
            </section>

            <section>
              <h3>Achados</h3>
              {CAMPOS_ACHADO.map((campo) => (
                <AchadoEditor
                  key={campo}
                  campo={campo}
                  achado={edicao.achados[campo]}
                  ia={ia?.achados?.[campo]}
                  onChange={setAchado}
                />
              ))}
            </section>

            <section>
              <h3>Impressão</h3>
              <textarea
                className="txt"
                rows={4}
                value={edicao.impressao || ""}
                onChange={(e) =>
                  setEdicao((p) => ({ ...p, impressao: e.target.value }))
                }
              />
            </section>

            <div className="acoes">
              <button
                className="btn btn-secundario"
                disabled={salvando}
                onClick={() => salvar()}
              >
                {salvando ? "Salvando…" : "Salvar rascunho"}
              </button>
              <button className="btn btn-primario" disabled={salvando} onClick={assinar}>
                Assinar laudo
              </button>
              <button className="btn btn-perigo" disabled={salvando} onClick={rejeitar}>
                Rejeitar
              </button>
            </div>
            <p className="nota-ia">
              ● marca campos alterados em relação ao rascunho da IA.{" "}
              <a className="link-pdf" href={api.pdfUrl(id)} target="_blank" rel="noreferrer">
                Pré-visualizar PDF (rascunho)
              </a>
            </p>
          </>
        )}
      </div>
    </div>
  );
}

export default function App() {
  const [exames, setExames] = useState([]);
  const [online, setOnline] = useState(true);
  const [selecionado, setSelecionado] = useState(null);

  const carregar = useCallback(() => {
    api
      .listarExames()
      .then((lista) => {
        setExames(lista);
        setOnline(true);
      })
      .catch(() => setOnline(false));
  }, []);

  useEffect(() => {
    carregar();
  }, [carregar]);

  const enviar = async (e) => {
    const arquivo = e.target.files?.[0];
    if (!arquivo) return;
    try {
      const r = await api.enviarDicom(arquivo);
      carregar();
      setSelecionado(r.id);
    } catch {
      setOnline(false);
    }
  };

  return (
    <div className="app">
      <header className="topo">
        <div className="marca">
          MedLaudo<span>·AI</span>
          <small>Assistente de laudo — Raio-X de tórax</small>
        </div>
        <label className="btn btn-primario upload">
          + Enviar DICOM
          <input type="file" accept=".dcm,application/dicom" onChange={enviar} hidden />
        </label>
      </header>

      {!online && <StatusOffline />}

      <main className="layout">
        <aside className="worklist">
          <h2>Worklist</h2>
          {exames.length === 0 && <p className="vazio">Nenhum exame ainda.</p>}
          <ul>
            {exames.map((e) => (
              <li
                key={e.id}
                className={`item ${selecionado === e.id ? "ativo" : ""} ${
                  e.critico ? "item-critico" : ""
                }`}
                onClick={() => setSelecionado(e.id)}
              >
                <div className="item-topo">
                  <span className="item-mod">{e.modalidade}</span>
                  {e.critico && <Badge tom="critico">crítico</Badge>}
                </div>
                <div className="item-status">{e.status}</div>
                <div className="item-id">{e.id.slice(0, 8)}</div>
              </li>
            ))}
          </ul>
        </aside>

        <Detalhe id={selecionado} onMudou={carregar} />
      </main>
    </div>
  );
}
