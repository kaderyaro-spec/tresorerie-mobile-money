package ci.warri.app

import android.webkit.JavascriptInterface

/**
 * Pont exposé à l'app web sous « window.WarriAndroid ».
 * L'écran Réglages détecte sa présence et propose « Activer la lecture SMS
 * sur ce téléphone », qui appelle setSmsEndpoint(lien de l'appareil).
 */
class WarriBridge(private val activity: MainActivity) {

    /** Vrai quand la page tourne dans l'app native (et non un simple navigateur). */
    @JavascriptInterface
    fun isWarriApp(): Boolean = true

    /** Enregistre le lien …/api/sms?token=… et demande la permission SMS. */
    @JavascriptInterface
    fun setSmsEndpoint(url: String) {
        Prefs.setEndpoint(activity, url.trim())
        activity.runOnUiThread { activity.askSmsPermissionIfNeeded() }
    }

    /** État de la lecture SMS : "ready" / "no_permission" / "no_endpoint". */
    @JavascriptInterface
    fun smsStatus(): String = when {
        Prefs.getEndpoint(activity).isNullOrBlank() -> "no_endpoint"
        !activity.hasSmsPermission() -> "no_permission"
        else -> "ready"
    }

    /** Lien actuellement enregistré sur CE téléphone ("" si aucun). Permet à la
     *  page Réglages de vérifier qu'il correspond toujours à un appareil actif
     *  (et non à un appareil révoqué). */
    @JavascriptInterface
    fun getEndpoint(): String = Prefs.getEndpoint(activity) ?: ""
}
