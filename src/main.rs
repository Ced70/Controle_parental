use std::net::SocketAddr;
use std::sync::{Arc, Mutex};
use std::time::{SystemTime, UNIX_EPOCH};

use axum::{
    Json, Router,
    extract::{ConnectInfo, Query, State},
    http::StatusCode,
    response::Html,
    routing::{get, post},
};
use rusqlite::{Connection, OptionalExtension, params};
use serde::{Deserialize, Serialize};
use tower_http::cors::CorsLayer;

type Db = Arc<Mutex<Connection>>;

// État partagé entre toutes les requêtes.
#[derive(Clone)]
struct AppState {
    db: Db,
    yt_cle: Option<Arc<String>>, // clé YouTube Data API (None = palier 3 inactif)
    http: reqwest::Client,
}

// Message de blocage personnalisé — modifiable ici.
const MESSAGE_BLOCAGE: &str = "Site bloqué par papa 😂";

/// Catégories YouTube « non intelligentes » qui déclenchent le quiz.
/// 20 = Jeux vidéo, 24 = Divertissement, 23 = Comédie. (Modifiable.)
const CATEGORIES_QUIZ: &[&str] = &["20", "24", "23"];

/// Configuration d'un niveau de défi (libellé, durée de déblocage, couleur).
#[derive(Debug, Clone, Serialize, Deserialize)]
struct Niveau {
    cle: String,
    label: String,
    minutes: i64,
    couleur: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct Config {
    niveaux: Vec<Niveau>,
}

fn config_par_defaut() -> Config {
    Config {
        niveaux: vec![
            Niveau { cle: "simple".into(), label: "Facile".into(), minutes: 2, couleur: "#22c55e".into() },
            Niveau { cle: "moyen".into(), label: "Moyen".into(), minutes: 5, couleur: "#eab308".into() },
            Niveau { cle: "difficile".into(), label: "Difficile".into(), minutes: 10, couleur: "#ef4444".into() },
        ],
    }
}

/// Lit `config.json` à CHAQUE appel (modifiable à chaud) ; défaut si absent/invalide.
fn charger_config() -> Config {
    std::fs::read_to_string("config.json")
        .ok()
        .and_then(|s| serde_json::from_str::<Config>(&s).ok())
        .unwrap_or_else(config_par_defaut)
}

/// Durée de déblocage (minutes) du niveau, depuis la config (0 si niveau inconnu).
fn duree_minutes(niveau: &str) -> i64 {
    charger_config()
        .niveaux
        .iter()
        .find(|n| n.cle == niveau)
        .map(|n| n.minutes)
        .unwrap_or(0)
}

/// Clé identifiant l'appareil : identifiant explicite si fourni et valide, sinon IP source.
/// Le préfixe `id:`/`ip:` évite toute collision entre un identifiant et une vraie IP.
fn cle_appareil(appareil: &Option<String>, addr: &SocketAddr) -> String {
    match appareil.as_deref().map(str::trim) {
        Some(a)
            if !a.is_empty()
                && a.len() <= 64
                && a.chars().all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-') =>
        {
            format!("id:{a}")
        }
        _ => format!("ip:{}", addr.ip()),
    }
}

fn maintenant() -> i64 {
    SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs() as i64
}

/// Charge la clé YouTube : variable d'env `CONTROLE_YT_API_KEY`, sinon fichier `youtube_api.key`.
fn charger_cle_youtube() -> Option<String> {
    if let Ok(k) = std::env::var("CONTROLE_YT_API_KEY") {
        let k = k.trim().to_string();
        if !k.is_empty() {
            return Some(k);
        }
    }
    std::fs::read_to_string("youtube_api.key")
        .ok()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
}

// ---------------------------------------------------------------------------
// Types JSON
// ---------------------------------------------------------------------------

#[derive(Debug, Deserialize)]
struct DecisionRequest {
    domaine: String,
    url: String,
    #[serde(default)]
    appareil: Option<String>, // identifiant d'appareil, optionnel (app Android)
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "lowercase")]
enum Action {
    Allow,
    Block,
    Quiz,
}

#[derive(Debug, Serialize)]
struct DecisionResponse {
    action: Action,
    message: String,
    // Secondes restantes avant la fin du déblocage (présent seulement si allow par déblocage).
    #[serde(skip_serializing_if = "Option::is_none")]
    restant_sec: Option<i64>,
}

#[derive(Debug, Serialize, Deserialize)]
struct Regle {
    domaine: String,
    action: String,
}

#[derive(Debug, Serialize)]
struct QuestionPublique {
    id: i64,
    niveau: String,
    enonce: String,
    choix: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct QuestionQuery {
    niveau: String,
}

#[derive(Debug, Deserialize)]
struct ValiderRequest {
    question_id: i64,
    choix: i64,
    domaine: String,
    #[serde(default)]
    appareil: Option<String>, // identifiant d'appareil, optionnel (app Android)
}

#[derive(Debug, Serialize)]
struct ValiderResponse {
    ok: bool,
    duree_min: i64,
    message: String,
    bonne: i64, // index de la bonne réponse (pour révélation après échec) ; -1 si inconnu
}

// Raccourcis pour construire les réponses fréquentes.
fn rep_quiz() -> DecisionResponse {
    DecisionResponse {
        action: Action::Quiz,
        message: "Réponds à une question pour débloquer la page 😉".to_string(),
        restant_sec: None,
    }
}
fn rep_allow() -> DecisionResponse {
    DecisionResponse { action: Action::Allow, message: String::new(), restant_sec: None }
}
fn rep_block() -> DecisionResponse {
    DecisionResponse { action: Action::Block, message: MESSAGE_BLOCAGE.to_string(), restant_sec: None }
}

// ---------------------------------------------------------------------------
// Politiques par appareil (mode « blocage net » : quiz désactivé)
// ---------------------------------------------------------------------------

#[derive(Debug, Serialize, Deserialize)]
struct Politique {
    appareil: String,
    mode: String, // "block" = vidéos quiz bloquées net ; "quiz" = comportement normal
}

/// Normalise une clé de politique : accepte `tel-nathou`, `id:tel-nathou` ou `192.168.1.16`.
fn normaliser_cle_politique(s: &str) -> String {
    let s = s.trim();
    if s.starts_with("id:") || s.starts_with("ip:") {
        s.to_string()
    } else if s.parse::<std::net::IpAddr>().is_ok() {
        format!("ip:{s}")
    } else {
        format!("id:{s}")
    }
}

/// L'appareil est-il en mode « blocage net » (quiz désactivé) ?
fn quiz_bloque_pour(conn: &Connection, appareil: &str) -> bool {
    conn.query_row(
        "SELECT mode FROM politiques_appareils WHERE appareil = ?1",
        params![appareil],
        |r| r.get::<_, String>(0),
    )
    .optional()
    .unwrap()
    .as_deref()
        == Some("block")
}

/// Convertit un éventuel « quiz » en blocage net si la politique de l'appareil l'exige.
fn appliquer_politique(rep: DecisionResponse, bloquer: bool) -> DecisionResponse {
    if bloquer && matches!(rep.action, Action::Quiz) { rep_block() } else { rep }
}

// ---------------------------------------------------------------------------
// Logique YouTube (palier 3)
// ---------------------------------------------------------------------------

fn est_youtube(domaine: &str) -> bool {
    domaine.contains("youtube.com") || domaine.contains("youtu.be")
}

/// Extrait l'identifiant de vidéo d'une URL YouTube (watch?v=, /shorts/, /embed/, youtu.be/).
fn extraire_video_id(url: &str) -> Option<String> {
    let u = reqwest::Url::parse(url).ok()?;
    if let Some((_, v)) = u.query_pairs().find(|(k, _)| k.as_ref() == "v") {
        let v = v.into_owned();
        if !v.is_empty() {
            return Some(v);
        }
    }
    let segs: Vec<String> = u
        .path_segments()
        .map(|it| it.map(|s| s.to_string()).collect())
        .unwrap_or_default();
    match segs.first().map(String::as_str) {
        Some("shorts") | Some("embed") => segs.get(1).filter(|s| !s.is_empty()).cloned(),
        _ if u.host_str() == Some("youtu.be") => segs.first().filter(|s| !s.is_empty()).cloned(),
        _ => None,
    }
}

/// Décision selon la catégorie de la vidéo.
fn decision_youtube(categorie: &str) -> DecisionResponse {
    if CATEGORIES_QUIZ.contains(&categorie) {
        DecisionResponse {
            action: Action::Quiz,
            message: "Vidéo de divertissement 🎮 — réponds à une question pour la débloquer 😉".to_string(),
            restant_sec: None,
        }
    } else {
        rep_allow()
    }
}

/// Interroge l'API YouTube pour la catégorie d'une vidéo.
async fn recuperer_categorie(client: &reqwest::Client, cle: &str, video_id: &str) -> Option<String> {
    let url = format!("https://www.googleapis.com/youtube/v3/videos?part=snippet&id={video_id}&key={cle}");
    let json: serde_json::Value = client.get(url).send().await.ok()?.json().await.ok()?;
    json.get("items")?
        .get(0)?
        .get("snippet")?
        .get("categoryId")?
        .as_str()
        .map(|s| s.to_string())
}

// ---------------------------------------------------------------------------
// Base de données
// ---------------------------------------------------------------------------

fn init_db() -> Connection {
    let conn = Connection::open("controle_parental.db").expect("ouverture de la base");

    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS regles (
            id      INTEGER PRIMARY KEY,
            domaine TEXT NOT NULL UNIQUE,
            action  TEXT NOT NULL CHECK(action IN ('block','quiz'))
        );
        CREATE TABLE IF NOT EXISTS questions (
            id            INTEGER PRIMARY KEY,
            niveau        TEXT NOT NULL CHECK(niveau IN ('simple','moyen','difficile')),
            enonce        TEXT NOT NULL,
            choix         TEXT NOT NULL,
            bonne_reponse INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS categories_videos (
            video_id    TEXT PRIMARY KEY,
            category_id TEXT NOT NULL,
            vu_at       INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS politiques_appareils (
            appareil TEXT PRIMARY KEY,
            mode     TEXT NOT NULL CHECK(mode IN ('quiz','block'))
        );",
    )
    .expect("création des tables");

    // Table des déblocages : indexée par appareil (identifiant explicite préfixé `id:`
    // ou IP préfixée `ip:`) + domaine, pour qu'un déblocage sur un appareil ne débloque
    // pas les autres. Migration : si une vieille table sans colonne `appareil` existe,
    // on la recrée (données transitoires, ≤ 10 min).
    let colonnes: Vec<String> = {
        let mut stmt = conn.prepare("PRAGMA table_info(deblocages)").unwrap();
        let cols = stmt
            .query_map([], |r| r.get::<_, String>(1))
            .unwrap()
            .filter_map(Result::ok)
            .collect();
        cols
    };
    if !colonnes.is_empty() && !colonnes.iter().any(|c| c == "appareil") {
        conn.execute("DROP TABLE deblocages", []).unwrap();
    }
    conn.execute(
        "CREATE TABLE IF NOT EXISTS deblocages (
            appareil  TEXT NOT NULL,
            domaine   TEXT NOT NULL,
            expire_at INTEGER NOT NULL,
            PRIMARY KEY (appareil, domaine)
        )",
        [],
    )
    .expect("création de la table deblocages");

    let nb_regles: i64 = conn
        .query_row("SELECT COUNT(*) FROM regles", [], |r| r.get(0))
        .unwrap();
    if nb_regles == 0 {
        for (domaine, action) in [
            ("exemple-interdit.com", "block"),
            ("youtube.com", "quiz"),
            ("twitch.tv", "quiz"),
        ] {
            conn.execute(
                "INSERT INTO regles (domaine, action) VALUES (?1, ?2)",
                params![domaine, action],
            )
            .unwrap();
        }
    }

    // Questions : si questions.json existe, on (re)charge depuis ce fichier (source éditable).
    // Sinon, amorçage par défaut si la table est vide.
    if std::path::Path::new("questions.json").exists() {
        charger_questions_fichier(&conn);
    } else {
        let nb_q: i64 = conn
            .query_row("SELECT COUNT(*) FROM questions", [], |r| r.get(0))
            .unwrap();
        if nb_q == 0 {
            amorcer_questions(&conn);
            println!("Banque de questions amorcée (défaut).");
        }
    }

    conn
}

#[derive(Debug, Deserialize)]
struct QuestionFichier {
    niveau: String,
    enonce: String,
    choix: Vec<String>,
    bonne: i64,
}

#[derive(Debug, Deserialize)]
struct BanqueQuestions {
    questions: Vec<QuestionFichier>,
}

/// (Re)charge la table `questions` depuis questions.json (remplace l'existant).
fn charger_questions_fichier(conn: &Connection) {
    let contenu = match std::fs::read_to_string("questions.json") {
        Ok(c) => c,
        Err(_) => return,
    };
    let banque: BanqueQuestions = match serde_json::from_str(&contenu) {
        Ok(b) => b,
        Err(e) => {
            eprintln!("questions.json invalide : {e}");
            return;
        }
    };
    // Une seule transaction pour tout le rechargement : sans elle, chaque INSERT
    // paie un fsync — plusieurs minutes de démarrage sur carte SD (Raspberry Pi).
    conn.execute_batch("BEGIN IMMEDIATE").unwrap();
    conn.execute("DELETE FROM questions", []).unwrap();
    let mut n = 0;
    for q in &banque.questions {
        let choix_json = serde_json::to_string(&q.choix).unwrap();
        if conn
            .execute(
                "INSERT INTO questions (niveau, enonce, choix, bonne_reponse) VALUES (?1, ?2, ?3, ?4)",
                params![q.niveau, q.enonce, choix_json, q.bonne],
            )
            .is_ok()
        {
            n += 1;
        }
    }
    conn.execute_batch("COMMIT").unwrap();
    println!("{n} questions chargées depuis questions.json.");
}

fn amorcer_questions(conn: &Connection) {
    let questions: &[(&str, &str, &[&str], i64)] = &[
        // SIMPLE (≈ 9 ans) → débloque 2 min — tables et calculs à 2-3 chiffres
        ("simple", "Combien font 7 × 9 ?", &["56", "63", "72"], 1),
        ("simple", "Combien font 84 ÷ 7 ?", &["12", "13", "11"], 0),
        ("simple", "Combien font 156 + 247 ?", &["403", "393", "413"], 0),
        ("simple", "Combien font 100 − 64 ?", &["46", "36", "44"], 1),
        ("simple", "Combien de côtés a un octogone ?", &["6", "8", "10"], 1),
        ("simple", "Quel est le double de 47 ?", &["84", "94", "98"], 1),
        // MOYEN → débloque 5 min — multiplications, fractions, pourcentages, géo
        ("moyen", "Combien font 13 × 14 ?", &["172", "182", "192"], 1),
        ("moyen", "Combien font 144 ÷ 12 + 5 ?", &["17", "16", "15"], 0),
        ("moyen", "Quelle fraction est la plus grande : 3/5 ou 5/8 ?", &["3/5", "5/8", "égales"], 1),
        ("moyen", "Combien de minutes dans 2 h 45 ?", &["165", "145", "175"], 0),
        ("moyen", "Quelle est la capitale de l'Allemagne ?", &["Munich", "Berlin", "Hambourg"], 1),
        ("moyen", "Combien font 25 % de 80 ?", &["15", "20", "25"], 1),
        // DIFFICILE (≈ 11 ans+) → débloque 10 min — calculs à étapes, puissances, sciences
        ("difficile", "Combien font 17 × 18 ?", &["306", "296", "316"], 0),
        ("difficile", "Quelle est la racine carrée de 169 ?", &["12", "13", "14"], 1),
        ("difficile", "Combien font 35 % de 240 ?", &["72", "84", "96"], 1),
        ("difficile", "Combien font (8 + 4) × 3 − 10 ?", &["26", "36", "16"], 0),
        ("difficile", "Combien de secondes dans 1 h 30 ?", &["4500", "5400", "3600"], 1),
        ("difficile", "Combien font 2³ + 3² ?", &["17", "18", "16"], 0),
        ("difficile", "Quelle est la plus grande planète du système solaire ?", &["Saturne", "Jupiter", "Neptune"], 1),
    ];
    for (niveau, enonce, choix, bonne) in questions {
        let choix_json = serde_json::to_string(choix).unwrap();
        conn.execute(
            "INSERT INTO questions (niveau, enonce, choix, bonne_reponse) VALUES (?1, ?2, ?3, ?4)",
            params![niveau, enonce, choix_json, bonne],
        )
        .unwrap();
    }
}

// ---------------------------------------------------------------------------
// Handlers
// ---------------------------------------------------------------------------

async fn health() -> &'static str {
    "ok"
}

/// Sert la page de quiz (lue sur le disque à CHAQUE requête → éditable sans recompiler).
async fn ecran_quiz() -> Html<String> {
    Html(
        std::fs::read_to_string("pages/quiz.html")
            .unwrap_or_else(|_| "<h1>pages/quiz.html introuvable</h1>".to_string()),
    )
}

/// Sert la page de blocage (idem, éditable à chaud).
async fn ecran_blocage() -> Html<String> {
    Html(
        std::fs::read_to_string("pages/blocage.html")
            .unwrap_or_else(|_| "<h1>Site bloqué par papa 😂</h1>".to_string()),
    )
}

/// Renvoie la config (niveaux + durées) pour que la page de quiz affiche les bons libellés.
async fn config() -> Json<Config> {
    Json(charger_config())
}

/// Décide quoi faire d'une page. Pour YouTube avec clé API, classe la vidéo par catégorie.
async fn decision(
    State(st): State<AppState>,
    ConnectInfo(addr): ConnectInfo<SocketAddr>,
    Json(req): Json<DecisionRequest>,
) -> Json<DecisionResponse> {
    let now = maintenant();
    let appareil = cle_appareil(&req.appareil, &addr); // appareil qui fait la requête

    // --- Phase synchrone (sous verrou) : politique, déblocage, règle, cache catégorie ---
    // Le bloc renvoie l'ID de la vidéo à classer ; tous les autres cas font `return`.
    let (video_id, bloquer): (String, bool) = {
        let conn = st.db.lock().unwrap();

        // 0) Politique de l'appareil : « block » = quiz désactivé, vidéos bloquées net.
        let bloquer = quiz_bloque_pour(&conn, &appareil);

        // 1) Déblocage encore actif POUR CET APPAREIL ? (sans objet en mode blocage net)
        if !bloquer {
            let expire_at: Option<i64> = conn
                .query_row(
                    "SELECT expire_at FROM deblocages
                     WHERE appareil = ?1 AND ?2 LIKE '%' || domaine || '%' AND expire_at > ?3
                     ORDER BY expire_at DESC LIMIT 1",
                    params![appareil, req.domaine, now],
                    |r| r.get(0),
                )
                .optional()
                .unwrap();
            if let Some(expire_at) = expire_at {
                return Json(DecisionResponse {
                    action: Action::Allow,
                    message: "Débloqué ✅".to_string(),
                    restant_sec: Some(expire_at - now), // temps restant pour le minuteur côté extension
                });
            }
        }

        // 2) Règle applicable ?
        let action: Option<String> = conn
            .query_row(
                "SELECT action FROM regles
                 WHERE ?1 LIKE '%' || domaine || '%'
                 ORDER BY CASE action WHEN 'block' THEN 0 ELSE 1 END LIMIT 1",
                params![req.domaine],
                |r| r.get(0),
            )
            .optional()
            .unwrap();

        match action.as_deref() {
            Some("block") => return Json(rep_block()),
            Some("quiz") => {
                // Intelligence YouTube uniquement si une clé API est configurée.
                if est_youtube(&req.domaine) && st.yt_cle.is_some() {
                    match extraire_video_id(&req.url) {
                        Some(vid) => {
                            // Catégorie déjà en cache ?
                            let cat: Option<String> = conn
                                .query_row(
                                    "SELECT category_id FROM categories_videos WHERE video_id = ?1",
                                    params![vid],
                                    |r| r.get(0),
                                )
                                .optional()
                                .unwrap();
                            match cat {
                                Some(c) => return Json(appliquer_politique(decision_youtube(&c), bloquer)),
                                None => (vid, bloquer), // valeur du bloc -> classée via l'API hors verrou
                            }
                        }
                        // Page YouTube hors vidéo (accueil, recherche) : on laisse naviguer.
                        None => return Json(rep_allow()),
                    }
                } else {
                    // Pas YouTube, ou pas de clé : comportement classique = quiz.
                    return Json(appliquer_politique(rep_quiz(), bloquer));
                }
            }
            _ => return Json(rep_allow()),
        }
    }; // verrou relâché ici

    // --- Phase asynchrone : classification via l'API YouTube ---
    let cle = st.yt_cle.as_ref().unwrap();

    match recuperer_categorie(&st.http, cle.as_str(), &video_id).await {
        Some(cat) => {
            // Mise en cache pour ne pas réinterroger l'API à chaque visite.
            let conn = st.db.lock().unwrap();
            let _ = conn.execute(
                "INSERT OR REPLACE INTO categories_videos (video_id, category_id, vu_at) VALUES (?1, ?2, ?3)",
                params![video_id, cat, now],
            );
            Json(appliquer_politique(decision_youtube(&cat), bloquer))
        }
        // Échec API : on retombe prudemment sur le quiz.
        None => Json(appliquer_politique(rep_quiz(), bloquer)),
    }
}

async fn quiz_question(
    State(st): State<AppState>,
    Query(q): Query<QuestionQuery>,
) -> Result<Json<QuestionPublique>, (StatusCode, String)> {
    if duree_minutes(&q.niveau) == 0 {
        return Err((StatusCode::BAD_REQUEST, "niveau invalide".to_string()));
    }
    let conn = st.db.lock().unwrap();
    let res: Option<(i64, String, String, String)> = conn
        .query_row(
            "SELECT id, niveau, enonce, choix FROM questions
             WHERE niveau = ?1 ORDER BY RANDOM() LIMIT 1",
            params![q.niveau],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
        )
        .optional()
        .unwrap();

    match res {
        Some((id, niveau, enonce, choix_json)) => {
            let choix: Vec<String> = serde_json::from_str(&choix_json).unwrap_or_default();
            Ok(Json(QuestionPublique { id, niveau, enonce, choix }))
        }
        None => Err((StatusCode::NOT_FOUND, "aucune question pour ce niveau".to_string())),
    }
}

async fn quiz_valider(
    State(st): State<AppState>,
    ConnectInfo(addr): ConnectInfo<SocketAddr>,
    Json(req): Json<ValiderRequest>,
) -> Json<ValiderResponse> {
    let appareil = cle_appareil(&req.appareil, &addr);
    let conn = st.db.lock().unwrap();

    // Mode « blocage net » : pas de déblocage possible par le quiz.
    if quiz_bloque_pour(&conn, &appareil) {
        return Json(ValiderResponse {
            ok: false,
            duree_min: 0,
            message: "Le quiz est désactivé pour cet appareil.".to_string(),
            bonne: -1,
        });
    }

    let info: Option<(i64, String)> = conn
        .query_row(
            "SELECT bonne_reponse, niveau FROM questions WHERE id = ?1",
            params![req.question_id],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()
        .unwrap();

    let (bonne, niveau) = match info {
        Some(x) => x,
        None => {
            return Json(ValiderResponse {
                ok: false,
                duree_min: 0,
                message: "Question introuvable.".to_string(),
                bonne: -1,
            });
        }
    };

    if req.choix != bonne {
        return Json(ValiderResponse {
            ok: false,
            duree_min: 0,
            message: "Mauvaise réponse".to_string(),
            bonne, // l'extension révèle la bonne réponse après le 2e échec
        });
    }

    let duree = duree_minutes(&niveau);
    let cle = conn
        .query_row(
            "SELECT domaine FROM regles
             WHERE ?1 LIKE '%' || domaine || '%' AND action = 'quiz' LIMIT 1",
            params![req.domaine],
            |r| r.get::<_, String>(0),
        )
        .optional()
        .unwrap()
        .unwrap_or_else(|| req.domaine.clone());

    let expire = maintenant() + duree * 60;
    conn.execute(
        "INSERT INTO deblocages (appareil, domaine, expire_at) VALUES (?1, ?2, ?3)
         ON CONFLICT(appareil, domaine) DO UPDATE SET expire_at = excluded.expire_at",
        params![appareil, cle, expire],
    )
    .unwrap();

    Json(ValiderResponse {
        ok: true,
        duree_min: duree,
        message: format!("Bravo ! 🎉 Débloqué pour {duree} minutes."),
        bonne,
    })
}

async fn lister_regles(State(st): State<AppState>) -> Json<Vec<Regle>> {
    let conn = st.db.lock().unwrap();
    let mut stmt = conn
        .prepare("SELECT domaine, action FROM regles ORDER BY domaine")
        .unwrap();
    let regles = stmt
        .query_map([], |row| Ok(Regle { domaine: row.get(0)?, action: row.get(1)? }))
        .unwrap()
        .filter_map(Result::ok)
        .collect();
    Json(regles)
}

async fn ajouter_regle(
    State(st): State<AppState>,
    Json(regle): Json<Regle>,
) -> Result<Json<Regle>, (StatusCode, String)> {
    if regle.action != "block" && regle.action != "quiz" {
        return Err((
            StatusCode::BAD_REQUEST,
            "le champ 'action' doit valoir 'block' ou 'quiz'".to_string(),
        ));
    }
    let conn = st.db.lock().unwrap();
    conn.execute(
        "INSERT INTO regles (domaine, action) VALUES (?1, ?2)
         ON CONFLICT(domaine) DO UPDATE SET action = excluded.action",
        params![regle.domaine, regle.action],
    )
    .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
    Ok(Json(regle))
}

/// Liste les appareils en mode particulier (absent de la liste = quiz normal).
async fn lister_politiques(State(st): State<AppState>) -> Json<Vec<Politique>> {
    let conn = st.db.lock().unwrap();
    let mut stmt = conn
        .prepare("SELECT appareil, mode FROM politiques_appareils ORDER BY appareil")
        .unwrap();
    let politiques = stmt
        .query_map([], |row| Ok(Politique { appareil: row.get(0)?, mode: row.get(1)? }))
        .unwrap()
        .filter_map(Result::ok)
        .collect();
    Json(politiques)
}

/// Bascule un appareil : mode "block" = vidéos quiz bloquées net ; "quiz" = retour au
/// comportement normal (la ligne est supprimée). La clé est normalisée (`id:`/`ip:`).
async fn definir_politique(
    State(st): State<AppState>,
    Json(p): Json<Politique>,
) -> Result<Json<Politique>, (StatusCode, String)> {
    if p.mode != "quiz" && p.mode != "block" {
        return Err((
            StatusCode::BAD_REQUEST,
            "le champ 'mode' doit valoir 'quiz' ou 'block'".to_string(),
        ));
    }
    let cle = normaliser_cle_politique(&p.appareil);
    let conn = st.db.lock().unwrap();
    if p.mode == "quiz" {
        conn.execute("DELETE FROM politiques_appareils WHERE appareil = ?1", params![cle])
            .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
    } else {
        conn.execute(
            "INSERT INTO politiques_appareils (appareil, mode) VALUES (?1, 'block')
             ON CONFLICT(appareil) DO UPDATE SET mode = 'block'",
            params![cle],
        )
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
    }
    Ok(Json(Politique { appareil: cle, mode: p.mode }))
}

// ---------------------------------------------------------------------------

#[tokio::main]
async fn main() {
    let cle = charger_cle_youtube();
    match &cle {
        Some(_) => println!("Clé YouTube chargée → intelligence par catégorie ACTIVE."),
        None => println!("Pas de clé YouTube → YouTube déclenche le quiz systématiquement."),
    }

    let state = AppState {
        db: Arc::new(Mutex::new(init_db())),
        yt_cle: cle.map(Arc::new),
        http: reqwest::Client::new(),
    };

    let app = Router::new()
        .route("/health", get(health))
        .route("/decision", post(decision))
        .route("/regles", get(lister_regles).post(ajouter_regle))
        .route("/politiques", get(lister_politiques).post(definir_politique))
        .route("/quiz/question", get(quiz_question))
        .route("/quiz/valider", post(quiz_valider))
        .route("/ecran/quiz", get(ecran_quiz))
        .route("/ecran/blocage", get(ecran_blocage))
        .route("/config", get(config))
        .layer(CorsLayer::permissive())
        .with_state(state);

    let adresse = "0.0.0.0:8090";
    let listener = tokio::net::TcpListener::bind(adresse).await.unwrap();
    println!("Serveur contrôle parental en écoute sur http://{adresse}");

    axum::serve(
        listener,
        app.into_make_service_with_connect_info::<SocketAddr>(),
    )
    .await
    .unwrap();
}
