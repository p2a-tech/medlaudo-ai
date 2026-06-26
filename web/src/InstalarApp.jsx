import { useEffect, useState } from "react";

// Banner de instalação do PWA.
// - Android/Chrome: captura o evento beforeinstallprompt e oferece "Instalar".
// - iOS/Safari: não há evento; mostramos as instruções manuais.
// - Some se já estiver instalado (standalone) ou se o usuário dispensar.

const ehIOS = () =>
  /iphone|ipad|ipod/i.test(navigator.userAgent) && !window.MSStream;

const standalone = () =>
  window.matchMedia?.("(display-mode: standalone)").matches ||
  window.navigator.standalone === true;

export default function InstalarApp() {
  const [evento, setEvento] = useState(null); // beforeinstallprompt adiado
  const [mostrar, setMostrar] = useState(false);
  const [dicasIOS, setDicasIOS] = useState(false);

  useEffect(() => {
    if (standalone() || localStorage.getItem("medlaudo_install_dismiss") === "1")
      return;

    const onPrompt = (e) => {
      e.preventDefault();
      setEvento(e);
      setMostrar(true);
    };
    window.addEventListener("beforeinstallprompt", onPrompt);

    // iOS não dispara o evento — oferecemos as instruções manuais.
    if (ehIOS()) setMostrar(true);

    // Some quando o app é instalado.
    const onInstalado = () => setMostrar(false);
    window.addEventListener("appinstalled", onInstalado);

    return () => {
      window.removeEventListener("beforeinstallprompt", onPrompt);
      window.removeEventListener("appinstalled", onInstalado);
    };
  }, []);

  if (!mostrar) return null;

  const instalar = async () => {
    if (evento) {
      evento.prompt();
      const { outcome } = await evento.userChoice;
      setEvento(null);
      if (outcome === "accepted") setMostrar(false);
    } else if (ehIOS()) {
      setDicasIOS(true);
    }
  };

  const dispensar = () => {
    localStorage.setItem("medlaudo_install_dismiss", "1");
    setMostrar(false);
  };

  return (
    <div className="instalar-banner" role="dialog" aria-label="Instalar aplicativo">
      <img className="instalar-icone" src="/icon-192.png" alt="" />
      <div className="instalar-txt">
        <strong>Instalar o MedLaudo·AI</strong>
        {dicasIOS ? (
          <span>
            No Safari: toque em <b>Compartilhar</b> e depois em{" "}
            <b>“Adicionar à Tela de Início”</b>.
          </span>
        ) : (
          <span>Use como app — tela cheia e funciona offline.</span>
        )}
      </div>
      {!dicasIOS && (
        <button className="btn btn-primario instalar-btn" onClick={instalar}>
          Instalar
        </button>
      )}
      <button className="instalar-x" onClick={dispensar} aria-label="Dispensar">
        ✕
      </button>
    </div>
  );
}
