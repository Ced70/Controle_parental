// Service worker / event page de l'extension.
//
// Rôle : relayer les appels au backend. Le content script ne peut pas appeler
// directement le backend HTTP (contexte page HTTPS + CSP), mais le background, lui,
// le peut (host_permissions + connect-src déclaré dans le manifeste).
//
// Protocole : le content script envoie { type: "api", path, body? }.
//   - sans `body`  -> requête GET
//   - avec `body`  -> requête POST (JSON)
// La réponse renvoyée est { ok: true, data } ou { ok: false, error }.

// Adresse du backend Rust. À adapter si le DGX change d'IP.
const BACKEND = "http://192.168.1.51:8090";

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "api") return;

  const options = { method: message.body !== undefined ? "POST" : "GET", headers: {} };
  if (message.body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(message.body);
  }

  fetch(BACKEND + message.path, options)
    .then((r) => r.json())
    .then((data) => sendResponse({ ok: true, data }))
    .catch((err) => {
      console.warn("[CP-bg] appel backend échoué :", message.path, err);
      sendResponse({ ok: false, error: String(err) });
    });

  // true = réponse asynchrone (garde le canal de message ouvert).
  return true;
});
