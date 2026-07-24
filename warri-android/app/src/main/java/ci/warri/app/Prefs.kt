package ci.warri.app

import android.content.Context
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Stockage local : lien d'envoi des SMS + statistiques de diagnostic. */
object Prefs {
    private const val FILE = "warri_prefs"
    private const val KEY_ENDPOINT = "sms_endpoint"

    // Diagnostic : ce qui s'est réellement passé sur CE téléphone.
    private const val KEY_NB_CAPTES = "nb_captes"       // SMS captés par le récepteur
    private const val KEY_NB_ENVOYES = "nb_envoyes"     // envois serveur réussis
    private const val KEY_LAST_SMS_AT = "last_sms_at"   // heure du dernier SMS capté
    private const val KEY_LAST_SEND_AT = "last_send_at" // heure du dernier essai d'envoi
    private const val KEY_LAST_SEND_RESULT = "last_send_result" // ex. "200", "erreur réseau"

    private fun sp(ctx: Context) = ctx.getSharedPreferences(FILE, Context.MODE_PRIVATE)
    private fun now(): String =
        SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.FRANCE).format(Date())

    fun getEndpoint(ctx: Context): String? = sp(ctx).getString(KEY_ENDPOINT, null)

    fun setEndpoint(ctx: Context, url: String) {
        sp(ctx).edit().putString(KEY_ENDPOINT, url).apply()
    }

    /** Un SMS vient d'être capté par le récepteur (même si pas encore envoyé). */
    fun stampSmsCaptured(ctx: Context) {
        val s = sp(ctx)
        s.edit()
            .putInt(KEY_NB_CAPTES, s.getInt(KEY_NB_CAPTES, 0) + 1)
            .putString(KEY_LAST_SMS_AT, now())
            .apply()
    }

    /** Résultat du dernier essai d'envoi au serveur ("200", "401", "erreur réseau"…). */
    fun stampSendResult(ctx: Context, result: String, success: Boolean) {
        val s = sp(ctx)
        val e = s.edit()
            .putString(KEY_LAST_SEND_AT, now())
            .putString(KEY_LAST_SEND_RESULT, result)
        if (success) e.putInt(KEY_NB_ENVOYES, s.getInt(KEY_NB_ENVOYES, 0) + 1)
        e.apply()
    }

    /** Bilan complet pour l'écran de diagnostic (JSON simple). */
    fun diagJson(ctx: Context): String {
        val s = sp(ctx)
        fun esc(v: String?) = (v ?: "").replace("\\", "").replace("\"", "'")
        return "{" +
            "\"captes\":${s.getInt(KEY_NB_CAPTES, 0)}," +
            "\"envoyes\":${s.getInt(KEY_NB_ENVOYES, 0)}," +
            "\"dernier_sms\":\"${esc(s.getString(KEY_LAST_SMS_AT, null))}\"," +
            "\"dernier_envoi\":\"${esc(s.getString(KEY_LAST_SEND_AT, null))}\"," +
            "\"dernier_resultat\":\"${esc(s.getString(KEY_LAST_SEND_RESULT, null))}\"" +
            "}"
    }
}
