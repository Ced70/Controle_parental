# Contrôle Parental Intelligent

Un contrôle parental « intelligent » auto-hébergé pour le réseau de la maison, qui ne se
contente pas de bloquer : pour accéder aux contenus « non intelligents » (YouTube gaming,
divertissement…), l'enfant doit d'abord **réussir un exercice de révision** (maths,
français, anglais, sciences…). Bonne réponse → accès débloqué quelques minutes. Le niveau
de difficulté choisi détermine la durée du déblocage.

Trois clients pour une même logique centrale :

- une **extension Firefox** (PC) ;
- une **application Android** ([`app_android/`](app_android/)) : YouTube dans une WebView
  filtrée, pensée pour un téléphone d'enfant ;
- un filtrage **DNS** de fond (AdGuard Home) pour les contenus sensibles.

## Architecture

```
                      ┌──────────────────────── serveur maison ────────────────────────┐
                      │                                                                │
  PC (Firefox) ───────┤  Backend Rust (axum) :8090          AdGuard Home (Docker) :53  │
   extension          │  ├─ moteur de décision /decision     └─ blocage DNS des sites  │
                      │  ├─ quiz 3 niveaux + déblocages         sensibles (listes      │
  Téléphone Android ──┤  │  temporaires par appareil            NSFW, SafeSearch…)     │
   app WebView        │  ├─ classification YouTube                                     │
  (app_android/)      │  │  (catégorie via YouTube Data API)                           │
                      │  └─ SQLite (règles, questions,                                 │
                      │     déblocages, politiques)                                    │
                      └────────────────────────────────────────────────────────────────┘
```

À chaque navigation, le client interroge `POST /decision` avec le domaine et l'URL.
Le serveur répond `allow`, `quiz` ou `block` :

- `allow` — la page se charge normalement ;
- `quiz` — le client redirige vers l'écran de quiz servi par le backend ; en cas de
  réussite, le domaine est débloqué N minutes **pour cet appareil uniquement** ;
- `block` — écran de blocage, sans échappatoire.

Pour YouTube, si une clé YouTube Data API est configurée, le serveur classe chaque vidéo
par sa **catégorie** : seules les catégories « non intelligentes » (jeux vidéo,
divertissement, comédie — configurable dans `src/main.rs`) déclenchent le quiz ; un
documentaire passe directement. Sans clé API, tout YouTube déclenche le quiz.

## Contenu du dépôt

| Dossier / fichier | Rôle |
|---|---|
| `src/main.rs` | Backend Rust complet (axum + rusqlite, un seul fichier) |
| `pages/quiz.html`, `pages/blocage.html` | Écrans servis par le backend, **modifiables à chaud** (relus à chaque requête) |
| `config.json` | Niveaux de quiz : libellé, durée de déblocage, couleur — modifiable à chaud |
| `questions.json` | Banque de questions (~3700, 5 choix), rechargée au démarrage |
| `tools/generer_questions.py` | Générateur de la banque (maths calculées + sujets curés) |
| `extension/` | Extension Firefox MV3 (manifest, background, content script) |
| `app_android/` | Application Android « NathouTube » (Kotlin, WebView) |
| `deploiement/` | Script de lancement, unité systemd, policies.json Firefox |

## Le backend en 5 minutes

Prérequis : Rust (édition 2024). Puis :

```bash
cargo run --release
# → Serveur contrôle parental en écoute sur http://0.0.0.0:8090
```

Au premier démarrage, la base SQLite `controle_parental.db` est créée et amorcée
(règles d'exemple + questions). Optionnel mais recommandé pour YouTube : une clé
[YouTube Data API v3](https://console.cloud.google.com/apis/) dans le fichier
`youtube_api.key` (ou la variable d'env `CONTROLE_YT_API_KEY`).

### API

| Route | Rôle |
|---|---|
| `POST /decision` | `{domaine, url, appareil?}` → `{action: allow\|quiz\|block, message, restant_sec?}` |
| `GET /ecran/quiz?retour=…&domaine=…&appareil=…` | Écran de quiz (HTML) |
| `GET /ecran/blocage` | Écran de blocage (HTML) |
| `GET /quiz/question?niveau=simple\|moyen\|difficile` | Tire une question au hasard |
| `POST /quiz/valider` | `{question_id, choix, domaine, appareil?}` → déblocage si bonne réponse |
| `GET /config` | Niveaux et durées (pour l'écran de quiz) |
| `GET`/`POST /regles` | Liste / ajoute une règle `{domaine, action: block\|quiz}` |
| `GET`/`POST /politiques` | Politiques par appareil (voir ci-dessous) |
| `GET /health` | Sonde de vie |

### Identification des appareils

Les déblocages sont **scopés par appareil** : réussir un quiz sur un PC ne débloque pas
les autres. La clé d'appareil est :

- l'identifiant envoyé dans le champ optionnel `appareil` (format `[A-Za-z0-9_-]{1,64}`),
  préfixé `id:` — c'est ce que fait l'app Android ;
- sinon, repli sur l'**IP source**, préfixée `ip:` — c'est le cas de l'extension Firefox,
  qui n'envoie rien. Aucune migration des clients existants n'est nécessaire.

### Politiques par appareil (blocage net, sans quiz)

Pour retirer l'option quiz à un appareil donné (les vidéos « quiz » sont alors bloquées
net, et `/quiz/valider` refuse) :

```bash
# bloquer net les vidéos quiz sur un appareil
curl -s localhost:8090/politiques -H 'content-type: application/json' \
  -d '{"appareil":"tel-enfant","mode":"block"}'

# retour au comportement normal (quiz)
curl -s localhost:8090/politiques -H 'content-type: application/json' \
  -d '{"appareil":"tel-enfant","mode":"quiz"}'

# état courant
curl -s localhost:8090/politiques
```

Le champ `appareil` accepte un identifiant (`tel-enfant`), une clé complète
(`id:tel-enfant`) ou une IP (`192.168.1.16` pour un PC utilisant l'extension).

## L'application Android (`app_android/`)

Une app Kotlin minimaliste (aucune dépendance hors coroutines) qui affiche
`m.youtube.com` dans une WebView et applique les décisions du backend **avant chaque
navigation** — y compris les changements de vidéo sans rechargement (SPA), détectés par
un script injecté qui surveille `location.href`.

Points clés :

- **Fail-closed** : si le serveur est injoignable, tout est bloqué (écran « Serveur
  injoignable » avec bouton réessayer). Hors de la maison, l'app ne laisse rien passer.
- **Sans compte Google** : lecture, recherche et suggestions fonctionnent sans connexion ;
  les liens `accounts.google.com` sont neutralisés. Bonus : pas de recommandations
  personnalisées qui poussent toujours plus du même contenu.
- **Identifiant d'appareil** persistant (SharedPreferences), configuré au premier
  lancement avec l'URL du serveur.
- HTTP en clair autorisé **uniquement** vers l'IP du serveur
  (`res/xml/network_security_config.xml` — à adapter à votre réseau).

Compilation (Android Studio installé, ou juste son SDK + JDK) :

```bash
cd app_android
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Adaptez avant de compiler : l'IP du serveur dans `network_security_config.xml` et le
défaut `BACKEND_DEFAUT` dans `DeviceId.kt`. Logs de debug : `adb logcat -s ControleParental`.

> **Note Family Link** : sur un téléphone supervisé, le débogage USB est bloqué. Soit
> autoriser temporairement les « sources inconnues » depuis l'appli parent et installer
> l'APK par téléchargement, soit lever temporairement la supervision. Une fois l'app en
> place, bloquer l'appli YouTube officielle et YouTube dans Chrome via Family Link pour
> que l'app filtrée soit la seule porte d'entrée.

## L'extension Firefox (`extension/`)

Extension MV3 (compatible Chrome/Firefox : clés `service_worker` **et** `scripts` dans le
manifeste). Le content script applique la décision à chaque page et surveille les
navigations SPA. Pour une installation permanente sous Firefox, l'extension doit être
signée (auto-distribution *unlisted* sur addons.mozilla.org) ; le verrouillage
non-désinstallable passe par `deploiement/policies.json` (`force_installed`).

## Personnalisation

- **Messages et écrans** : `pages/*.html` et `MESSAGE_BLOCAGE` dans `src/main.rs`.
- **Niveaux / durées** : `config.json` (relu à chaque appel, pas de redémarrage).
- **Catégories YouTube déclenchant le quiz** : constante `CATEGORIES_QUIZ` dans
  `src/main.rs` (20 = jeux vidéo, 24 = divertissement, 23 = comédie).
- **Questions** : éditer `questions.json` ou régénérer via
  `python3 tools/generer_questions.py` (niveaux calibrés ~9-11 ans, à ajuster).
- **Règles de domaines** : `POST /regles` (`block` pour interdire, `quiz` pour
  conditionner).

## Limites connues (et assumées)

- **Pas d'authentification sur l'API** : n'exposez pas le port 8090 hors du LAN. Toute
  personne sur le réseau peut modifier règles et politiques.
- Le serveur doit tourner en permanence (script `deploiement/lancer_serveur.sh` ou unité
  systemd `deploiement/controle-parental.service`).
- Le contrôle ne vaut que si c'est la seule porte : sur les appareils de l'enfant,
  bloquer les autres accès (YouTube officiel, autres navigateurs) via Family Link ou
  équivalent.
- Hors du LAN, l'app Android bloque tout (fail-closed). Pour un accès filtré à
  l'extérieur : un VPN vers la maison (ex. Tailscale) et l'IP du serveur VPN comme URL
  de backend — c'est précisément pour ça que le scoping par identifiant d'appareil
  existe (l'IP vue par le serveur n'est alors plus significative).

## Licence / réutilisation

Projet personnel partagé tel quel, sans garantie. Réutilisez, adaptez, améliorez —
un retour d'expérience fait toujours plaisir.
