package ci.warri.app

/**
 * Expéditeurs légitimes des opérateurs mobile money (Côte d'Ivoire).
 *
 * Seuls les SMS venant de ces expéditeurs quittent le téléphone : les messages
 * personnels, promotions et codes de vérification ne sont JAMAIS transmis.
 *
 * ⚠ Miroir exact de logic.is_operator_sender() (serveur) : toute modification
 * doit être reportée des DEUX côtés.
 */
object SmsSenders {

    private val NAME_HINTS = listOf(
        "orange", "mtn", "momo", "mobilemoney", "mobile money", "moov", "flooz", "wave"
    )
    private val SHORTCODES = listOf("454", "133", "155")

    /**
     * Tolérant sur la forme du short-code (« +454 », « 454 », « +225454 ») et sur
     * la casse du nom (« MobileMoney »). Un numéro de client complet (10 chiffres)
     * n'est jamais reconnu, même s'il se termine par un short-code.
     */
    fun isOperator(sender: String?): Boolean {
        val s = (sender ?: "").trim().lowercase()
        if (s.isBlank()) return false
        if (NAME_HINTS.any { s.contains(it) }) return true
        val digits = s.filter { it.isDigit() }
        if (digits.isEmpty() || digits.length > 8) return false   // au-delà : vrai numéro
        return SHORTCODES.any { digits == it || digits.endsWith(it) }
    }
}
