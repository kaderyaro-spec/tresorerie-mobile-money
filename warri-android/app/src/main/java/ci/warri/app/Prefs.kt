package ci.warri.app

import android.content.Context

/** Stockage local du lien d'envoi des SMS (…/api/sms?token=…) fourni par Warri. */
object Prefs {
    private const val FILE = "warri_prefs"
    private const val KEY_ENDPOINT = "sms_endpoint"

    fun getEndpoint(ctx: Context): String? =
        ctx.getSharedPreferences(FILE, Context.MODE_PRIVATE).getString(KEY_ENDPOINT, null)

    fun setEndpoint(ctx: Context, url: String) {
        ctx.getSharedPreferences(FILE, Context.MODE_PRIVATE)
            .edit().putString(KEY_ENDPOINT, url).apply()
    }
}
