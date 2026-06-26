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

function ListaAchados({ achados }) {
  if (!achados) return null;
  const presentes = Object.entries(achados).filter(
    ([, a]) => a.presenca !== "ausente"
  );
  if (presentes.length === 0)
    return <p className="vazio">Nenhum achado relevante detectado.</p>;

  return (
    <ul className="achados">
      {presentes.map(([campo, a]) => (
        <li key={campo} className={`achado achado-${a.presenca}`}>
          <div className="achado-topo">
            <strong>{ROTULOS[campo] || campo}</strong>
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
              <span className="confianca">{Math.round(a.confianca * 100)}%</span>
            </span>
          </div>
          {a.descricao && <p className="achado-desc">{a.descricao}</p>}
        </li>
      ))}
    </ul>
  );
}

function Detalhe({ id, onMudou }) {
  const [exame, setExame] = useState(null);

  useEffect(() => {
    if (!id) return;
    api.obterExame(id).then(setExame).catch(() => setExame(null));
  }, [id]);

  if (!id) return <div className="detalhe vazio-central">Selecione um exame na worklist.</div>;
  if (!exame) return <div className="detalhe vazio-central">Carregando…</div>;

  const laudo = exame.laudo_final || exame.laudo_ia;

  const assinar = async () => {
    await api.assinar(id, "Dr. Revisor");
    onMudou();
    api.obterExame(id).then(setExame);
  };
  const rejeitar = async () => {
    await api.rejeitar(id, "Dr. Revisor");
    onMudou();
    api.obterExame(id).then(setExame);
  };

  return (
    <div className="detalhe">
      <div className="viewer">
        <img src={api.imagemUrl(id)} alt="Radiografia de tórax" />
      </div>

      <div className="laudo">
        <div className="laudo-cabecalho">
          <h2>Rascunho de laudo</h2>
          {laudo?.validado_por_medico ? (
            <Badge tom="ok">Assinado</Badge>
          ) : (
            <Badge tom="alerta">Gerado por IA — não validado</Badge>
          )}
        </div>

        {exame.critico && (
          <div className="banner-critico">
            ⚠ Achado(s) crítico(s): {(laudo?.achados_criticos || []).join(", ")}
          </div>
        )}

        <section>
          <h3>Qualidade técnica</h3>
          <p>
            {laudo?.qualidade_tecnica?.incidencia || "—"} ·{" "}
            {laudo?.qualidade_tecnica?.adequada ? "adequada" : "inadequada"}
            {laudo?.qualidade_tecnica?.observacoes
              ? ` — ${laudo.qualidade_tecnica.observacoes}`
              : ""}
          </p>
        </section>

        <section>
          <h3>Achados</h3>
          <ListaAchados achados={laudo?.achados} />
        </section>

        <section>
          <h3>Impressão</h3>
          <p className="impressao">{laudo?.impressao || "—"}</p>
        </section>

        {!laudo?.validado_por_medico && (
          <div className="acoes">
            <button className="btn btn-primario" onClick={assinar}>
              Assinar laudo
            </button>
            <button className="btn btn-secundario" onClick={rejeitar}>
              Rejeitar rascunho
            </button>
          </div>
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
