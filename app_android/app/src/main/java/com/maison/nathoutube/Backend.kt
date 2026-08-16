package com.maison.nathoutube

import android.util.Log
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** Résultat de POST /decision. `Erreur` couvre tout imprévu → fail-closed côté app. */
sealed class Decision {
    data class Allow(val restantSec: Long?) : Decision()
    data object Quiz : Decision()
    data object Block : Decision()
    data object Erreur : Decision()
}

object Backend {
    private const val TAG = "ControleParental"

    /**
     * Appelle POST /decision {domaine, url, appareil}. Appel bloquant : à exécuter
     * hors du fil principal (Dispatchers.IO). Le readTimeout est large car le serveur
     * peut interroger l'API YouTube pour classer une vidéo jamais vue.
     */
    fun decision(backendUrl: String, domaine: String, url: String, appareil: String): Decision {
        return try {
            val co = (URL("$backendUrl/decision").openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 4000
                readTimeout = 8000
                doOutput = true
                setRequestProperty("Content-Type", "application/json")
            }
            val corps = JSONObject()
                .put("domaine", domaine)
                .put("url", url)
                .put("appareil", appareil)
            co.outputStream.use { it.write(corps.toString().toByteArray(Charsets.UTF_8)) }
            val texte = co.inputStream.bufferedReader().use { it.readText() }
            co.disconnect()

            val json = JSONObject(texte)
            when (json.optString("action")) {
                "allow" -> Decision.Allow(
                    if (json.has("restant_sec")) json.getLong("restant_sec") else null
                )
                "quiz" -> Decision.Quiz
                "block" -> Decision.Block
                else -> {
                    Log.d(TAG, "Réponse /decision inconnue : $texte")
                    Decision.Erreur
                }
            }
        } catch (e: Exception) {
            Log.d(TAG, "Échec /decision pour $url : $e")
            Decision.Erreur
        }
    }
}
