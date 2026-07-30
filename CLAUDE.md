# Contrôle Parental Intelligent

Projet perso de Cédric : un contrôle parental « intelligent » pour le réseau de la maison.
Objectif double :
1. **Bloquer** les sites sensibles (porno, violence…).
2. **Conditionner** l'accès à d'autres contenus (ex. YouTube gaming) à la réussite d'un
   **exercice de révision** : on propose de quitter la page ou de faire un quiz ; si le
   quiz est réussi, l'accès est débloqué temporairement.

## Réseau

- **Livebox** Orange : passerelle + DHCP, conservée. Elle **ne permet pas** de changer le DNS
  distribué par DHCP → le DNS est donc configuré **par appareil**.
- **DGX Spark** (`192.168.1.51`, IP fixe) : héberge le serveur. Doit rester allumé.
- 2 PC Windows (contrôle total, comptes non-admin prévus) + 1 téléphone **Android**.

## Architecture en paliers

| Palier | Contenu | État |
|---|---|---|
| 0 | Filtrage DNS réseau (AdGuard Home) | ✅ PC faits, reste le tél. Android |
| 1 | Backend Rust : moteur de décision (`/decision`) + règles SQLite | ✅ fait |
| 2 | Extension navigateur cliente du backend | 🔨 en cours |
| 4 | Moteur de quiz (3 niveaux) + déblocage temporel + messages perso | ✅ fait |
| 3 | Logique YouTube (catégorie via YouTube Data API) | ✅ fait |
| 5 | Durcissement (comptes non-admin, DNS verrouillé, extension forcée, dashboard) | à venir |

## Palier 0 — AdGuard Home (sur le DGX)

- Conteneur Docker `adguardhome`, conf dans `~/adguardhome/{work,conf}`.
- DNS sur `192.168.1.51:53`, admin AdGuard sur **http://192.168.1.51:8080** (le backend Rust, lui, est sur le `:8090`).
- Configuré : DNS amont = **Cloudflare for Families** `1.1.1.3`/`1.0.0.3` (+ Quad9 `dns10`), listes
  `https://nsfw.oisd.nl` + StevenBlack porn, navigation sécurisée, SafeSearch Google ON.
  **YouTube Mode restreint DÉSACTIVÉ** : c'est notre quiz qui gère YouTube. Il fallait DEUX choses :
  (1) `safe_search.youtube: false` dans AdGuardHome.yaml, ET (2) **changer le DNS amont** : l'ancien
  AdGuard Family `94.140.14.15/16` forçait `www.youtube.com → restrictmoderate.youtube.com` côté résolveur
  (Cloudflare for Families bloque porno/malware SANS forcer le Mode restreint). Édité via
  `docker exec adguardhome sed -i ...` + `docker restart adguardhome` (le restart vide aussi le cache DNS).
  Tradeoff : YouTube ne masque plus auto le « mature » ; protection = quiz par catégorie + blocklists + Cloudflare Families.
- **Pièges** : les navigateurs (Firefox/Chrome) utilisent leur propre DNS-over-HTTPS qui
  contourne AdGuard → à désactiver. La Livebox sert aussi un DNS **IPv6** qui contourne →
  désactiver IPv6 sur la carte réseau (ou le forcer aussi).

## Palier 1 — Backend Rust (`./`, `./src/main.rs`)

- Rust 1.95, edition 2024. Deps : `axum 0.8`, `tokio`, `serde`, `rusqlite 0.40` (feature `bundled`),
  `tower-http` (feature `cors`, `CorsLayer::permissive()` pour l'extension).
- Serveur sur `0.0.0.0:8090`.
- Base SQLite `controle_parental.db` (ignorée par git), amorcée si vide. Tables :
  - `regles(domaine UNIQUE, action CHECK IN ('block','quiz'))`
  - `questions(niveau CHECK simple|moyen|difficile, enonce, choix JSON, bonne_reponse index)` — **(re)chargée
    au démarrage depuis `questions.json`** (~3700 Q : **~1186-1278/niveau**, **5 choix** chacune). Régénérable via
    `python3 tools/generer_questions.py`. Composition/niveau = **900 maths** (`MATH_CIBLE`, calculées, exactes)
    + **~286-378 sujets curés** : capitales (≈70, 2 sens), continents, vocabulaire anglais (~220 mots EN↔FR),
    **nombres en lettres** (fonction `en_lettres`, règles FR, 2 sens), sciences (symboles, planètes, corps),
    français (pluriels, antonymes, **féminins masc↔fém**, conjugaison présent + imparfait). Distracteurs de la
    même catégorie. Pour + de « sujets » : enrichir les dicts curés du générateur (maths figées à `MATH_CIBLE`).
  - `deblocages(ip, domaine, expire_at unix-secs, PK(ip,domaine))` — déblocages temporaires **par appareil** :
    l'IP du client (via `ConnectInfo<SocketAddr>`) est la clé, donc débloquer sur un PC ne débloque pas les autres.
- Connexion partagée via `Arc<Mutex<Connection>>` en axum `State`.
- Durées de déblocage : dans **`config.json`** (racine projet), lu à l'exécution → **modifiable à chaud**
  (pas de recompilation). Source unique : `duree_minutes()` le lit pour l'application réelle, et la page
  `pages/quiz.html` le lit via `GET /config` pour afficher les libellés (toujours cohérents). Défaut 2/5/10 min si absent.
- Message de blocage perso dans la const `MESSAGE_BLOCAGE` ("Site bloqué par papa 😂").

### Routes

- `GET  /health` → `"ok"`
- `POST /decision`  body `{domaine, url}` → `{action: "allow"|"block"|"quiz", message, restant_sec?}`.
  Ordre : déblocage actif (allow + `restant_sec` = secondes restantes) > règle (block prioritaire sur quiz) > allow par défaut.
- `GET  /quiz/question?niveau=simple|moyen|difficile` → une question au hasard `{id, niveau, enonce, choix}` (sans la réponse).
- `POST /quiz/valider`  body `{question_id, choix (index), domaine}` → `{ok, duree_min, message, bonne}` ;
  si correct, crée un déblocage du domaine de la règle pour la durée du niveau, **scoped à l'IP de l'appareil**.
  `bonne` = index de la bonne réponse, renvoyé pour que la page la révèle après le 2ᵉ échec.

### Anti-triche du quiz (`pages/quiz.html`)

- **5 choix** au lieu de 3 ; ordre de la bonne réponse mélangé à la génération.
- **2 essais** par question ; au 2ᵉ échec → révélation de la bonne réponse + **délai de 10 s** + **question suivante**
  (impossible de rester sur une question jusqu'à tomber juste). Déblocage uniquement sur une bonne réponse.
- Anti-répétition (Set `dejaVues`) pour ne pas reproposer une question juste vue.
- Tout en page/données → modifiable **sans recompiler** (questions/délai/nb choix) et **sans re-signer** l'extension.
- `GET  /regles` / `POST /regles` → liste / ajoute-modifie une règle à chaud (upsert).
- `GET  /config` → niveaux + durées (depuis `config.json`), consommé par `pages/quiz.html`.

### Lancer / tester

```bash
cargo run                       # serveur sur :8090
curl -s localhost:8090/regles
pkill -x controle_parent        # arrêter (nom tronqué à 15 car. ;
                                #  ne PAS utiliser `pkill -f`, il matche sa propre ligne de commande)
```

## Palier 2 — Extension (`./extension/`) — ✅ FONCTIONNE de bout en bout (testé Firefox)

- Manifest V3. `content.js` détecte le domaine + l'URL, demande une décision via `background.js`,
  puis affiche l'écran de blocage perso ou l'UI de quiz (choix difficulté → question → validation).
- `background.js` est un **proxy API générique** : `{type:"api", path, body?}` → fetch vers le backend.
  Le `fetch` part du **background** (pas du content script) pour contourner le *mixed content*.
- URL du backend en haut de `background.js` (`BACKEND = "http://192.168.1.51:8090"`).
- **Navigation SPA** : `content.js` surveille les changements d'URL (setInterval 1,2 s) pour
  re-vérifier quand on change de vidéo YouTube sans recharger.

## Palier 3 — Intelligence YouTube (`src/main.rs`) — ✅ fait

- Clé YouTube Data API chargée via env `CONTROLE_YT_API_KEY` ou fichier `youtube_api.key` (gitignoré).
- Pour une page YouTube avec clé : `/decision` extrait l'ID vidéo (`watch?v=`, `/shorts/`, `youtu.be/`),
  interroge l'API pour la **catégorie**, et décide. Cache en table `categories_videos`.
- `CATEGORIES_QUIZ = ["20","24","23"]` (Jeux vidéo, Divertissement, Comédie) → quiz ; le reste → allow.
- Accueil/recherche YouTube (pas d'ID vidéo) → allow (navigation libre). Sans clé → quiz systématique.
- Client HTTP : `reqwest` (features `json`, `rustls` — TLS sans openssl système, build via cmake).

## Déploiement / signature de l'extension (palier 5 en cours)

- Signée en **auto-distribution (unlisted)** sur addons.mozilla.org → `.xpi` signé (id `controle-parental@maison.local`).
- Manifeste : `data_collection_permissions: { required: ["none"] }` requis par Firefox ; `strict_min_version` 128.
- Empaqueter : `cd extension && zip -r -FS ../controle_parental.zip manifest.json background.js content.js`.
- **Mise à jour** = bump `version` dans manifest.json → re-zip → re-signer AMO → réinstaller le `.xpi`.
- Verrouillage non-désinstallable (NON encore appliqué) : `deploiement/policies.json` (force_installed) à
  copier dans `C:\Program Files\Mozilla Firefox\distribution\policies.json`.

### Pièges MV3 résolus (ordre dans lequel ils sont apparus)

1. **`background.service_worker` désactivé sous Firefox** → mettre **les deux** clés :
   `service_worker` (Chrome) + `scripts` (Firefox), le même `background.js` marche pour les deux.
2. **Pare-feu** : `ufw` est actif sur le DGX. AdGuard (Docker) le contourne, mais le backend
   Rust natif y est soumis. Le port 8090 doit être joignable depuis le LAN
   (`sudo ufw allow from 192.168.1.0/24 to any port 8090 proto tcp` si besoin).
3. **CORS** : Firefox traite le fetch comme cross-origine → ajouté `CorsLayer::permissive()` au backend.
4. **LE vrai blocage** : la **CSP de l'extension** MV3 interdit les connexions sortantes par défaut
   (`connect-src` retombe sur `default-src 'none'`). Fix dans le manifeste :
   `"content_security_policy": { "extension_pages": "... connect-src 'self' http://192.168.1.51:8090" }`.
- Debug : `about:debugging` → « Inspecter » l'extension = console du background ; les logs `[CP]`
  du content script sont dans la console **de la page**. Recharger l'extension après toute modif du manifeste.

## Architecture « pages servies par le serveur » (v0.4.0 — la clé pour ne plus re-signer)

- L'extension est désormais **minimale et stable** : `content.js` demande `/decision`, et si
  `block`/`quiz`, **redirige l'onglet** vers une page du backend (pas d'iframe → évite le
  *mixed content* ET la CSP de YouTube ; pas besoin de HTTPS).
  - quiz : `→ http://192.168.1.51:8090/ecran/quiz?retour=<url>&domaine=<hostname>`
  - block : `→ /ecran/blocage`
- Les pages sont dans **`pages/quiz.html`** et **`pages/blocage.html`**, **lues sur le disque à
  chaque requête** (handlers `ecran_quiz`/`ecran_blocage`). Donc : éditer la page = éditer le
  fichier + rafraîchir. **Aucune recompilation, aucune re-signature.**
- La page de quiz appelle `/quiz/question` et `/quiz/valider` en **same-origin** (backend) →
  pas de CORS/CSP. À la réussite, elle redirige vers `retour`.
- **Boucle de dev pour la page** : ouvrir directement
  `http://192.168.1.51:8090/ecran/quiz?retour=https://exemple.com&domaine=www.youtube.com`
  dans un navigateur, éditer `pages/quiz.html`, rafraîchir. Pas besoin de l'extension pour itérer.
- ⚠️ Le backend doit tourner (`./target/release/controle_parental` depuis le dossier projet, ou
  le service systemd) car les pages sont servies par lui.

### Coupure à l'expiration (v0.5.0)

- `/decision` renvoie `restant_sec` quand l'accès vient d'un déblocage temporaire.
- `content.js` arme un **minuteur précis** : à l'expiration il rappelle `verifier()` → si la vidéo doit
  redevenir bloquée, ça **redirige vers le quiz (= stoppe la lecture)** ; sinon (contenu autorisé) rien.
- Avertissement ~1 min avant via une petite bannière jaune (`#cp-banniere`).
- Expiration en **heure absolue** (table `deblocages.expire_at`) → mettre la vidéo en pause ne prolonge pas.

### Reprise au bon endroit (v0.6.0)

- Avant de rediriger vers le quiz, `content.js` lit `document.querySelector("video").currentTime` et
  injecte `&t=<sec>` dans l'URL de retour (`urlRetourAvecTemps()`) → YouTube **reprend là où on en était**
  après une bonne réponse (au lieu de recommencer à 0). Uniquement pour les domaines YouTube.
- ⚠️ Logique dans l'extension → toute modif nécessite une **re-signature** (version actuelle **0.6.0**).
- Note : 0.6.0 = changement de `content.js` uniquement, **pas** de recompilation du backend.

## Conventions

- Commentaires et messages en **français** (projet d'apprentissage Rust de Cédric).
- Identifiants de code en anglais quand c'est l'usage (ex. variantes d'enum).
