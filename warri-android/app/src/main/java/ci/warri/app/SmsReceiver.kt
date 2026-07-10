package ci.warri.app

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.Data
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit

/**
 * Reçoit chaque SMS entrant, en extrait l'expéditeur et le texte, puis confie
 * l'envoi vers Warri à un Worker (fiable : file d'attente + réessais si hors-ligne).
 */
class SmsReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return

        val endpoint = Prefs.getEndpoint(context)
        if (endpoint.isNullOrBlank()) return   // lecture SMS pas encore activée

        val messages = Telephony.Sms.Intents.getMessagesFromIntent(intent) ?: return
        if (messages.isEmpty()) return

        val sender = messages[0].originatingAddress ?: ""
        // Un SMS long est découpé en plusieurs morceaux : on les recolle.
        val body = messages.joinToString("") { it.messageBody ?: "" }
        if (body.isBlank()) return

        val data = Data.Builder()
            .putString("endpoint", endpoint)
            .putString("sender", sender)
            .putString("body", body)
            .build()

        val request = OneTimeWorkRequestBuilder<ForwardWorker>()
            .setInputData(data)
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build()
            )
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 10, TimeUnit.SECONDS)
            .build()

        WorkManager.getInstance(context).enqueue(request)
    }
}
