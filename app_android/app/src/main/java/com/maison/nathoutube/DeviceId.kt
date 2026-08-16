package com.maison.nathoutube

import android.content.Context
import java.util.UUID

/**
 * Identifiant d'appareil persistant + URL du backend, stockés en SharedPreferences.
 * L'identifiant est la clé de scoping des déblocages côté serveur (préfixé `id:`).
 * Format imposé, identique au backend : [A-Za-z0-9_-]{1,64}.
 */
object DeviceId {
    private const val PREFS = "cp"
    private const val CLE_ID = "appareil_id"
    private const val CLE_BACKEND = "backend_url"
    private const val CLE_CONFIG_FAITE = "config_faite"

    const val BACKEND_DEFAUT = "http://192.168.1.51:8090"
    val FORMAT = Regex("^[A-Za-z0-9_-]{1,64}$")

    private fun prefs(ctx: Context) = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    /** Identifiant stable de l'appareil ; généré à la première demande. */
    fun appareil(ctx: Context): String {
        prefs(ctx).getString(CLE_ID, null)?.let { return it }
        val id = "tel-" + UUID.randomUUID().toString().substring(0, 8)
        prefs(ctx).edit().putString(CLE_ID, id).apply()
        return id
    }

    /** Renomme l'appareil (config parent). Refuse les formats invalides. */
    fun definirAppareil(ctx: Context, id: String): Boolean {
        val propre = id.trim()
        if (!FORMAT.matches(propre)) return false
        prefs(ctx).edit().putString(CLE_ID, propre).apply()
        return true
    }

    fun backend(ctx: Context): String =
        (prefs(ctx).getString(CLE_BACKEND, null) ?: BACKEND_DEFAUT).trimEnd('/')

    fun definirBackend(ctx: Context, url: String): Boolean {
        val propre = url.trim().trimEnd('/')
        if (!propre.startsWith("http://") && !propre.startsWith("https://")) return false
        prefs(ctx).edit().putString(CLE_BACKEND, propre).apply()
        return true
    }

    fun configFaite(ctx: Context): Boolean = prefs(ctx).getBoolean(CLE_CONFIG_FAITE, false)

    fun marquerConfigFaite(ctx: Context) {
        prefs(ctx).edit().putBoolean(CLE_CONFIG_FAITE, true).apply()
    }
}
