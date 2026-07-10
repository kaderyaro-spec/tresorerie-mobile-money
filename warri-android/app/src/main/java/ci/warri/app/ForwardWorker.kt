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
        val endpoint = inputData.getString("endpoint") ?: return Result.failure()
        val sender = inputData.getString("sender") ?: ""
        val body = inputData.getString("body") ?: ""

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
