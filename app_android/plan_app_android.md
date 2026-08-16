# Plan de développement — App Android « YouTube filtré » + identifiant d'appareil

Objectif : une application Android (Kotlin) qui affiche `m.youtube.com` dans une WebView,
et qui applique les décisions du backend Rust existant (`/decision`, `/quiz/*`, `/ecran/*`)
avant chaque navigation. Le scoping des déblocages passe d'une clé « IP » à une clé
« appareil » (identifiant stable fourni par le client), avec rétrocompatibilité totale
pour l'extension Firefox existante (qui continue de ne rien envoyer → repli sur l'IP).

---

## Partie A — Modifications du backend Rust (`src/main.rs`)

Principe directeur : **champ `appareil` optionnel partout**. S'il est absent, on utilise
l'IP comme aujourd'hui. Aucune modification de l'extension n'est nécessaire.

### A.1 Schéma SQLite

Renommer la colonne `ip` de la table `deblocages` en `appareil` (elle contiendra soit une
IP, soit un identifiant d'appareil — c'est juste une clé opaque).

```sql
CREATE TABLE IF NOT EXISTS deblocages (
    appareil  TEXT NOT NULL,
    domaine   TEXT NOT NULL,
    expire_at INTEGER NOT NULL,
    PRIMARY KEY (appareil, domaine)
);
```

Migration dans `init_db()` : détecter l'ancienne colonne et migrer, ou plus simple vu que
les déblocages sont éphémères (≤ 10 min) : `DROP TABLE IF EXISTS deblocages` si l'ancienne
colonne existe, puis recréer. À faire une seule fois via un `PRAGMA table_info(deblocages)`.

### A.2 Requêtes entrantes

```rust
#[derive(Debug, Deserialize)]
struct DecisionRequest {
    domaine: String,
    url: String,
    #[serde(default)]
    appareil: Option<String>,   // NOUVEAU — identifiant d'appareil, optionnel
}

#[derive(Debug, Deserialize)]
struct ValiderRequest {
    question_id: i64,
    choix: i64,
    domaine: String,
    #[serde(default)]
    appareil: Option<String>,   // NOUVEAU
}
```

Petite fonction utilitaire :

```rust
/// Clé identifiant l'appareil : identifiant explicite si fourni, sinon IP source.
fn cle_appareil(appareil: &Option<String>, addr: &SocketAddr) -> String {
    match appareil.as_deref().map(str::trim) {
        Some(a) if !a.is_empty() => format!("id:{a}"),
        _ => format!("ip:{}", addr.ip()),
    }
}
```

Le préfixe `id:`/`ip:` évite toute collision entre un identifiant qui ressemblerait à une IP
et une vraie IP. Utiliser `cle_appareil(...)` dans `decision()` (requête sur `deblocages`)
et dans `quiz_valider()` (INSERT/UPSERT), à la place de `addr.ip().to_string()`.

Validation : refuser (ignorer → repli IP) les identifiants > 64 caractères ou contenant
autre chose que `[A-Za-z0-9_-]`, pour garder la base propre.

### A.3 La page de quiz doit transmettre l'identifiant

La page `pages/quiz.html` appelle `/quiz/valider` en same-origin depuis la WebView. Le
serveur verrait donc l'IP du téléphone (ce qui marcherait sur le LAN), mais pour que le
scoping soit cohérent partout (y compris via VPN/Tailscale où l'IP peut changer), la page
doit propager l'identifiant :

1. L'app Android redirige vers
   `http://SERVEUR:8090/ecran/quiz?retour=<url>&domaine=<hostname>&appareil=<id>`.
2. `pages/quiz.html` lit le paramètre `appareil` de l'URL
   (`new URLSearchParams(location.search).get("appareil")`) et l'ajoute au body JSON de
   `POST /quiz/valider` s'il est non vide.
3. L'extension Firefox, elle, n'ajoute pas ce paramètre → la page n'envoie rien → repli IP.
   **Zéro impact sur l'existant, pas de re-signature.**

### A.4 Tests backend (curl)

```bash
# décision avec identifiant
curl -s localhost:8090/decision -H 'content-type: application/json' \
  -d '{"domaine":"www.youtube.com","url":"https://www.youtube.com/watch?v=xxx","appareil":"tel-enzo"}'

# valider avec identifiant → le déblocage doit être scopé à id:tel-enzo
curl -s localhost:8090/quiz/valider -H 'content-type: application/json' \
  -d '{"question_id":1,"choix":0,"domaine":"www.youtube.com","appareil":"tel-enzo"}'

# vérifier que SANS appareil (extension), le comportement IP est inchangé
```

---

## Partie B — Application Android (Kotlin)

### B.0 Environnement de développement (déjà en place)

- **Poste de dev : Mac (Apple Silicon), Android Studio installé via Homebrew**
  (`brew install --cask android-studio`). Le JDK embarqué de Studio (JetBrains Runtime)
  sert de toolchain — ne pas installer de JDK séparé.
- SDK au chemin standard macOS : `$HOME/Library/Android/sdk` (`ANDROID_HOME`).
  `adb` et les cmdline-tools sont dans le PATH via `~/.zshrc`.
- Si `local.properties` est requis au build, y mettre :
  `sdk.dir=/Users/<user>/Library/Android/sdk` (fichier à gitignorer).
- **Compiler au terminal** : `./gradlew assembleDebug` ;
  **installer sur le téléphone** : `adb install -r app/build/outputs/apk/debug/app-debug.apk`
  (téléphone en débogage USB, vérifier avec `adb devices`).
- Logs de debug : `adb logcat -s ControleParental` (utiliser ce tag dans tous les `Log.d`).
- L'émulateur de Studio peut joindre le serveur LAN `192.168.1.51:8090` directement,
  mais le test de référence reste le **vrai téléphone** (seule vraie IP Wi-Fi propre,
  donc seul test réaliste du scoping par appareil).
- Le backend Rust tourne sur le DGX (`192.168.1.51:8090`), pas sur le Mac. Pour
  développer/tester le backend depuis le Mac : ssh sur le DGX, ou `cargo run` local
  si Rust est installé sur le Mac (optionnel).

### B.1 Choix techniques

- **Kotlin**, `minSdk 26` (Android 8+), `targetSdk` récent. Pas de Compose nécessaire :
  une seule Activity plein écran avec une WebView suffit (éventuellement Compose si préféré,
  mais rester minimal).
- **Aucune dépendance réseau lourde** : `HttpURLConnection` ou OkHttp (léger) pour appeler
  `/decision`. JSON via `org.json` (inclus dans Android) — pas besoin de Moshi/Gson.
- Trafic HTTP en clair vers le serveur LAN → nécessite
  `android:usesCleartextTraffic="true"` **ou mieux** un
  `network_security_config.xml` autorisant le clair uniquement vers l'IP/nom du serveur.

### B.2 Structure du projet

```
app/
├── src/main/
│   ├── AndroidManifest.xml
│   ├── res/xml/network_security_config.xml
│   ├── res/layout/activity_main.xml        (WebView plein écran + overlay chargement)
│   └── java/.../controleparental/
│       ├── MainActivity.kt                 (WebView + interception navigation)
│       ├── Backend.kt                      (client HTTP : POST /decision)
│       ├── DeviceId.kt                     (identifiant d'appareil persistant)
│       └── UrlWatcher.kt                   (détection navigation SPA via JS injecté)
└── build.gradle.kts
```

### B.3 Identifiant d'appareil (`DeviceId.kt`)

- À la première ouverture : générer `UUID.randomUUID()` tronqué (ou un nom lisible
  configurable, ex. `tel-enzo`), stocker dans `SharedPreferences`
  (`context.getSharedPreferences("cp", MODE_PRIVATE)`).
- Optionnel mais recommandé : un écran/dialog de configuration protégé (au premier
  lancement) où le parent saisit le nom de l'appareil et l'URL du backend, stockés en
  SharedPreferences. Défauts : `http://192.168.1.51:8090` + UUID.
- Contrainte de format côté app identique au backend : `[A-Za-z0-9_-]{1,64}`.

### B.4 Cœur : interception de navigation (`MainActivity.kt`)

WebView configurée avec :

```kotlin
webView.settings.apply {
    javaScriptEnabled = true
    domStorageEnabled = true
    mediaPlaybackRequiresUserGesture = false
}
```

Deux mécanismes complémentaires (comme extension MV3 : content.js + surveillance SPA) :

1. **Navigations classiques** — `WebViewClient.shouldOverrideUrlLoading` :
   - Si l'URL cible est le backend (`/ecran/…`) → laisser charger (return false).
   - Sinon : appeler `POST /decision {domaine, url, appareil}` (en coroutine, avec un
     petit écran d'attente) puis :
     - `allow` → charger l'URL.
     - `quiz`  → charger `BACKEND/ecran/quiz?retour=<url>&domaine=<host>&appareil=<id>`.
     - `block` → charger `BACKEND/ecran/blocage`.
   - **En cas d'échec réseau vers le backend : BLOQUER (fail-closed)** — afficher une page
     locale « Serveur injoignable » avec bouton réessayer. C'est le choix sûr.

2. **Navigation SPA YouTube** (changement de vidéo sans rechargement) — `UrlWatcher.kt` :
   injecter au `onPageFinished` un petit script qui poll `location.href` toutes les 1,2 s
   (même stratégie que `content.js`) et notifie l'app via un `JavascriptInterface`
   (`@JavascriptInterface fun onUrlChanged(url: String)`). À chaque changement d'URL :
   même logique de décision ; si `quiz`/`block`, `webView.loadUrl(ecranQuiz)` — la
   redirection plein onglet remplace YouTube, exactement comme sur PC.
   - Alternative/complément : `doUpdateVisitedHistory` capte aussi les pushState ; garder
     le poll JS en filet de sécurité (c'est ce qui a été fiabilisé côté extension).

3. **Retour après quiz réussi** : la page quiz redirige déjà vers `retour` — la WebView
   suit naturellement. Rien à faire.

Détails d'ergonomie :
- Charger `https://m.youtube.com` au démarrage.
- Gérer le bouton back Android → `webView.goBack()`.
- Anti-évasion basique : dans `shouldOverrideUrlLoading`, si le host n'est ni YouTube ni
  le backend, on peut soit appliquer la décision serveur normalement (le backend décide),
  soit restreindre l'app à YouTube + backend uniquement. **Recommandé : laisser le backend
  décider** (cohérent avec l'architecture — les règles vivent dans SQLite).

### B.5 Pas de compte Google (décision ferme)

L'app fonctionne **sans connexion à un compte** : lecture libre de m.youtube.com,
recherche et suggestions marchent sans authentification. Conséquences :
- On évite entièrement le problème « disallowed_useragent » des WebViews.
- Bonus filtrage : pas d'historique/recommandations personnalisées qui pousseraient
  toujours plus de gaming — les suggestions restent génériques.
- Si YouTube affiche un bandeau/invite de connexion, ne pas le suivre ; on peut au besoin
  intercepter les URLs `accounts.google.com` dans `shouldOverrideUrlLoading` et les
  ignorer (return true sans charger) pour que le bouton « Se connecter » soit inerte.

### B.6 Hors du LAN

Le backend n'est joignable qu'à la maison. Avec le fail-closed du B.4, hors de la maison
l'app bloque tout — comportement sûr par défaut. Amélioration prévue (phase ultérieure) :
installer **Tailscale** sur le téléphone et le DGX, et mettre l'IP Tailscale du DGX comme
URL backend dans l'app. C'est précisément le cas où l'identifiant d'appareil devient
indispensable (l'IP vue par le serveur devient l'IP Tailscale, voire varie).

### B.7 Anti-contournement (hors app, à faire côté parent)

L'app ne protège que si c'est la seule porte vers YouTube :
- **Family Link** (ou équivalent) : bloquer/désinstaller l'app YouTube officielle,
  bloquer YouTube dans Chrome (ou bloquer Chrome), interdire l'installation d'apps
  sans validation, empêcher la désinstallation de l'app de contrôle.
- AdGuard/DNS ne peut pas aider finement ici (tout est youtube.com) — ne pas bloquer
  youtube.com au DNS sinon l'app WebView tombe aussi.

---

## Partie C — Ordre de développement conseillé (sessions Claude Code)

1. **Backend d'abord** (30 min) : A.1 → A.4. Vérifier au curl la rétrocompat (sans
   `appareil`) puis le scoping par identifiant. Vérifier que l'extension Firefox
   fonctionne toujours à l'identique.
2. **Page quiz** (15 min) : A.3 — propagation du paramètre `appareil`. Test dans un
   navigateur de bureau avec `?appareil=test-pc` dans l'URL de la page.
3. **App Android squelette** (1 session) : projet Gradle (créé au terminal ou via
   Android Studio), WebView plein écran chargeant m.youtube.com,
   network_security_config, DeviceId, back button. Compiler avec `./gradlew
   assembleDebug` et tester sur le téléphone via `adb install -r` (cf. B.0).
4. **Interception + décision** (1 session) : B.4 complet, fail-closed, écran d'attente.
   Tester : vidéo gaming → quiz ; réussite → retour vidéo ; documentaire → direct.
5. **SPA watcher + finitions** (1 session) : UrlWatcher, changement de vidéo dans l'app,
   neutralisation des liens de connexion Google (B.5).
6. **Durcissement** : Family Link, APK release signé, éventuellement Tailscale.

## Partie D — Critères d'acceptation

- [ ] Extension Firefox inchangée et fonctionnelle (aucun champ `appareil` envoyé → IP).
- [ ] Deux appareils avec le même quiz réussi sur l'un : l'autre reste bloqué.
- [ ] Sur le téléphone : vidéo catégorie 20/23/24 → écran quiz ; bonne réponse → retour
      à la vidéo, minuteur respecté ; expiration → nouveau quiz.
- [ ] Changement de vidéo sans rechargement (clic suggestion) → re-décision en ≤ 2 s.
- [ ] Backend coupé → l'app affiche « serveur injoignable », rien ne passe.
- [ ] L'identifiant survit au redémarrage du téléphone (SharedPreferences).
