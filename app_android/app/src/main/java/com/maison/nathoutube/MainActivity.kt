package com.maison.nathoutube

import android.annotation.SuppressLint
import android.app.Activity
import android.app.AlertDialog
import android.net.Uri
import android.os.Bundle
import android.util.Log
import android.view.View
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : Activity() {

    companion object {
        private const val TAG = "ControleParental"
        private const val ACCUEIL = "https://m.youtube.com/"
    }

    private lateinit var webView: WebView
    private lateinit var overlayChargement: View
    private lateinit var overlayErreur: View

    private val scope = MainScope()
    private var travailEnCours: Job? = null

    /** Dernière URL déjà passée en décision — évite les doublons du poll SPA. */
    private var derniereUrlDecidee: String? = null

    /** URL à retenter depuis l'écran « Serveur injoignable ». */
    private var urlEnEchec: String = ACCUEIL

    private val backend get() = DeviceId.backend(this)
    private val appareil get() = DeviceId.appareil(this)

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        webView = findViewById(R.id.webview)
        overlayChargement = findViewById(R.id.overlay_chargement)
        overlayErreur = findViewById(R.id.overlay_erreur)
        findViewById<Button>(R.id.bouton_reessayer).setOnClickListener {
            overlayErreur.visibility = View.GONE
            deciderEtCharger(urlEnEchec)
        }

        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            mediaPlaybackRequiresUserGesture = false
        }

        webView.addJavascriptInterface(
            UrlWatcher { url -> runOnUiThread { surChangementSpa(url) } },
            UrlWatcher.NOM_INTERFACE
        )

        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                if (!request.isForMainFrame) return false
                val url = request.url.toString()
                return when {
                    estBackend(url) -> false          // écrans quiz/blocage : laisser charger
                    estConnexionGoogle(url) -> {
                        Log.d(TAG, "Connexion Google neutralisée : $url")
                        true                          // bouton « Se connecter » inerte
                    }
                    else -> {
                        deciderEtCharger(url)         // décision serveur AVANT de naviguer
                        true
                    }
                }
            }

            override fun onPageFinished(view: WebView, url: String) {
                if (!estBackend(url)) view.evaluateJavascript(UrlWatcher.SCRIPT, null)
            }

            override fun doUpdateVisitedHistory(view: WebView, url: String, isReload: Boolean) {
                // Capte les pushState de la SPA ; le poll JS reste le filet de sécurité.
                if (!estBackend(url)) surChangementSpa(url)
            }
        }

        if (DeviceId.configFaite(this)) {
            deciderEtCharger(ACCUEIL)
        } else {
            dialogueConfiguration()
        }
    }

    // -----------------------------------------------------------------------
    // Décision
    // -----------------------------------------------------------------------

    /** Navigation SPA détectée (poll JS ou historique) : re-décision sans recharger. */
    private fun surChangementSpa(url: String) {
        if (url == derniereUrlDecidee || estBackend(url)) return
        Log.d(TAG, "Changement SPA : $url")
        deciderEtCharger(url, spa = true)
    }

    /**
     * Demande au backend quoi faire de `url`, puis navigue selon la réponse.
     * En mode `spa`, la page est déjà affichée : « allow » ne recharge rien.
     * Échec réseau → fail-closed : écran « Serveur injoignable ».
     */
    private fun deciderEtCharger(url: String, spa: Boolean = false) {
        val domaine = Uri.parse(url).host
        if (domaine.isNullOrEmpty()) {
            Log.d(TAG, "URL sans hôte ignorée : $url")
            return
        }
        derniereUrlDecidee = url
        travailEnCours?.cancel()
        travailEnCours = scope.launch {
            if (!spa) overlayChargement.visibility = View.VISIBLE
            val decision = withContext(Dispatchers.IO) {
                Backend.decision(backend, domaine, url, appareil)
            }
            overlayChargement.visibility = View.GONE
            Log.d(TAG, "Décision $decision pour $url")
            when (decision) {
                is Decision.Allow -> if (!spa) webView.loadUrl(url)
                Decision.Quiz -> webView.loadUrl(urlEcranQuiz(url, domaine))
                Decision.Block -> webView.loadUrl("$backend/ecran/blocage")
                Decision.Erreur -> {
                    urlEnEchec = url
                    derniereUrlDecidee = null   // pour re-décider après « Réessayer »
                    overlayErreur.visibility = View.VISIBLE
                }
            }
        }
    }

    private fun urlEcranQuiz(retour: String, domaine: String): String =
        "$backend/ecran/quiz?retour=${Uri.encode(retour)}" +
            "&domaine=${Uri.encode(domaine)}&appareil=${Uri.encode(appareil)}"

    private fun estBackend(url: String) = url.startsWith(backend)

    private fun estConnexionGoogle(url: String): Boolean {
        val hote = Uri.parse(url).host ?: return false
        return hote == "accounts.google.com" || hote.endsWith(".accounts.google.com")
    }

    // -----------------------------------------------------------------------
    // Configuration (premier lancement)
    // -----------------------------------------------------------------------

    /** Dialog parent : nom de l'appareil + URL du backend, avec défauts préremplis. */
    private fun dialogueConfiguration() {
        val marge = (16 * resources.displayMetrics.density).toInt()
        val conteneur = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(marge, marge, marge, 0)
        }
        val libelleNom = TextView(this).apply { text = "Nom de l'appareil (a-z, 0-9, - _) :" }
        val champNom = EditText(this).apply { setText(DeviceId.appareil(this@MainActivity)) }
        val libelleUrl = TextView(this).apply { text = "URL du serveur :" }
        val champUrl = EditText(this).apply { setText(DeviceId.backend(this@MainActivity)) }
        conteneur.addView(libelleNom)
        conteneur.addView(champNom)
        conteneur.addView(libelleUrl)
        conteneur.addView(champUrl)

        AlertDialog.Builder(this)
            .setTitle("Configuration")
            .setView(conteneur)
            .setCancelable(false)
            .setPositiveButton("Valider") { _, _ ->
                val nomOk = DeviceId.definirAppareil(this, champNom.text.toString())
                val urlOk = DeviceId.definirBackend(this, champUrl.text.toString())
                if (!nomOk) Log.d(TAG, "Nom d'appareil invalide, identifiant généré conservé")
                if (!urlOk) Log.d(TAG, "URL backend invalide, défaut conservé")
                DeviceId.marquerConfigFaite(this)
                Log.d(TAG, "Config : appareil=$appareil backend=$backend")
                deciderEtCharger(ACCUEIL)
            }
            .show()
    }

    // -----------------------------------------------------------------------
    // Cycle de vie
    // -----------------------------------------------------------------------

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (webView.canGoBack()) webView.goBack() else super.onBackPressed()
    }

    override fun onPause() {
        super.onPause()
        webView.onPause()
    }

    override fun onResume() {
        super.onResume()
        webView.onResume()
    }

    override fun onDestroy() {
        scope.cancel()
        webView.destroy()
        super.onDestroy()
    }
}
