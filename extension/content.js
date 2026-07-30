// Extension minimale : demande une décision au backend, redirige vers la page
// du serveur si blocage/quiz, et — nouveauté 0.5.0 — arme un minuteur précis qui
// coupe la lecture (redirige vers le quiz) quand le temps débloqué expire.

(() => {
  const BACKEND = "http://192.168.1.51:8090";

  if (window.top !== window.self) return;
  if (location.hostname === "192.168.1.51") return;

  function api(path, body) {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage({ type: "api", path, body }, (rep) => {
        if (chrome.runtime.lastError || !rep || !rep.ok) resolve(null);
        else resolve(rep.data);
      });
    });
  }

  let enCours = false;
  let derniereUrl = location.href;
  let timerExpiration = null;
  let timerAvert = null;

  function annulerTimers() {
    if (timerExpiration) { clearTimeout(timerExpiration); timerExpiration = null; }
    if (timerAvert) { clearTimeout(timerAvert); timerAvert = null; }
    retirerBanniere();
  }

  function redirige(chemin) {
    location.href = BACKEND + chemin;
  }

  // URL de retour = page courante, en injectant l'instant de lecture de la vidéo
  // (paramètre `t` compris nativement par YouTube) pour reprendre où on en était.
  function urlRetourAvecTemps() {
    let url = location.href;
    try {
      if (/youtube\.com|youtu\.be/.test(location.hostname)) {
        const v = document.querySelector("video");
        if (v && isFinite(v.currentTime) && v.currentTime > 1) {
          const u = new URL(url);
          u.searchParams.set("t", String(Math.floor(v.currentTime)));
          url = u.toString();
        }
      }
    } catch (e) { /* on garde l'URL telle quelle */ }
    return url;
  }

  function versQuiz() {
    redirige(
      "/ecran/quiz?retour=" + encodeURIComponent(urlRetourAvecTemps()) +
      "&domaine=" + encodeURIComponent(location.hostname)
    );
  }

  async function verifier() {
    if (enCours) return;
    enCours = true;
    try {
      annulerTimers();
      const d = await api("/decision", { domaine: location.hostname, url: location.href });
      if (!d) return; // backend injoignable -> on laisse passer
      if (d.action === "block") {
        redirige("/ecran/blocage?retour=" + encodeURIComponent(location.href));
      } else if (d.action === "quiz") {
        versQuiz();
      } else if (typeof d.restant_sec === "number" && d.restant_sec > 0) {
        // Accès autorisé par un déblocage temporaire -> on arme le minuteur.
        armerExpiration(d.restant_sec);
      }
      // "allow" sans restant_sec (ex. vidéo éducative) -> rien à faire
    } finally {
      enCours = false;
    }
  }

  function armerExpiration(restantSec) {
    // Avertissement ~1 min avant la fin (ou tout de suite s'il reste peu).
    const avertDans = (restantSec - 60) * 1000;
    if (avertDans > 0) {
      timerAvert = setTimeout(() => afficherBanniere("⏳ Il te reste 1 minute avant un nouvel exercice !"), avertDans);
    } else if (restantSec > 8) {
      afficherBanniere("⏳ Bientôt la fin du temps débloqué !");
    }
    // À l'expiration : on re-vérifie. Si la vidéo doit être bloquée, ça redirige
    // vers le quiz (ce qui arrête la lecture) ; sinon (contenu autorisé) rien.
    timerExpiration = setTimeout(() => { verifier(); }, restantSec * 1000);
  }

  // -------- Petite bannière d'avertissement (en haut de la page) --------
  function afficherBanniere(texte) {
    retirerBanniere();
    const b = document.createElement("div");
    b.id = "cp-banniere";
    b.textContent = texte;
    Object.assign(b.style, {
      position: "fixed",
      top: "0",
      left: "0",
      right: "0",
      zIndex: "2147483647",
      background: "#eab308",
      color: "#1f2937",
      font: "600 15px system-ui, sans-serif",
      textAlign: "center",
      padding: "8px 12px",
      boxShadow: "0 2px 10px rgba(0,0,0,.3)",
    });
    document.documentElement.appendChild(b);
  }

  function retirerBanniere() {
    const b = document.getElementById("cp-banniere");
    if (b) b.remove();
  }

  // Au chargement.
  verifier();

  // Navigation SPA (YouTube change d'URL sans recharger) : on re-vérifie.
  setInterval(() => {
    if (location.href !== derniereUrl && !enCours) {
      derniereUrl = location.href;
      verifier();
    }
  }, 1200);
})();
