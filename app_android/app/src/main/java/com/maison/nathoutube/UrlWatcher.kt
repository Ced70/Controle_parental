package com.maison.nathoutube

import android.webkit.JavascriptInterface

/**
 * Détection de la navigation SPA de YouTube (changement de vidéo sans rechargement).
 * Un script injecté à onPageFinished poll location.href toutes les 1,2 s — même
 * stratégie que le content.js de l'extension Firefox — et notifie l'app via
 * l'interface JS `CP`. doUpdateVisitedHistory sert de complément côté natif.
 */
class UrlWatcher(private val onChange: (String) -> Unit) {

    @JavascriptInterface
    fun onUrlChanged(url: String) = onChange(url)

    companion object {
        const val NOM_INTERFACE = "CP"

        val SCRIPT = """
            (function () {
              if (window.__cpWatcher) return;
              window.__cpWatcher = true;
              var derniere = location.href;
              setInterval(function () {
                if (location.href !== derniere) {
                  derniere = location.href;
                  if (window.$NOM_INTERFACE) $NOM_INTERFACE.onUrlChanged(location.href);
                }
              }, 1200);
            })();
        """.trimIndent()
    }
}
