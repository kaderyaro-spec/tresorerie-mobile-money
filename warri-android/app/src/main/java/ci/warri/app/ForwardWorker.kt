package ci.warri.app

import android.content.Context
import androidx.work.Worker
import androidx.work.WorkerParameters
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/**
 * Envoie un SMS (expéditeur + texte) au lien Warri par POST form-urlencoded.
 * - 2xx  -> succès
 * - 5xx / réseau -> réessai (WorkManager relance plus tard)
 * - 4xx  -> échec définitif (ex. token invalide : inutile d'insister)
 */
class ForwardWorker(ctx: Context, params: WorkerParameters) : Worker(ctx, params) {

    override fun doWork(): Result {
        val rawEndpoint = inputData.getString("endpoint") ?: return Result.failure()
        val sender = inputData.getString("sender") ?: ""
        val body = inputData.getString("body") ?: ""

        // Sécurité : le jeton ne voyage plus dans l'URL (les URL finissent dans
        // les journaux des serveurs) mais dans l'en-tête X-Token. Compatible avec
        // les liens déjà enregistrés au format « …/api/sms?token=… ».
        var token: String? = null
        val parts = rawEndpoint.split("?", limit = 2)
        val endpoint = if (parts.size == 2) {
            val kept = parts[1].split("&").filter { p ->
                val isTok = p.startsWith("token=")
                if (isTok) token = p.substringAfter("=")
                !isTok
            }
            parts[0] + if (kept.isEmpty()) "" else "?" + kept.joinToString("&")
        } else rawEndpoint

        return try {
            val payload = "sender=" + URLEncoder.encode(sender, "UTF-8") +
                    "&body=" + URLEncoder.encode(body, "UTF-8")

            val conn = (URL(endpoint).openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                doOutput = true
                connectTimeout = 15000
                readTimeout = 15000
                setRequestProperty("Content-Type", "application/x-www-form-urlencoded")
                setRequestProperty("X-Requested-With", "warri-android")
                token?.let { setRequestProperty("X-Token", it) }
            }
            conn.outputStream.use { it.write(payload.toByteArray(Charsets.UTF_8)) }
            val code = conn.responseCode
            conn.disconnect()

            when {
                code in 200..299 -> Result.success()
                code in 500..599 -> Result.retry()
                else -> Result.failure()
            }
        } catch (e: Exception) {
            Result.retry()
        }
    }
}
