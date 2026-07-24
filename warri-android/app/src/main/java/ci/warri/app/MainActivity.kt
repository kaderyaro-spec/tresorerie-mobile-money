package ci.warri.app

import android.Manifest
import android.annotation.SuppressLint
import android.app.DownloadManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.webkit.CookieManager
import android.webkit.URLUtil
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.addCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat

class MainActivity : AppCompatActivity() {

    private lateinit var web: WebView
    private val startUrl = "https://tresorerie-mobile-money.onrender.com/"
    private val allowedHost = "tresorerie-mobile-money.onrender.com"

    private val permsLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { /* l'agent peut relancer depuis Réglages si refusé */ }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        web = WebView(this)
        setContentView(web)

        with(web.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            mediaPlaybackRequiresUserGesture = false
        }
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, true)

        web.addJavascriptInterface(WarriBridge(this), "WarriAndroid")

        web.webChromeClient = WebChromeClient()
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(
                view: WebView, request: WebResourceRequest
            ): Boolean {
                val uri = request.url
                val isHttp = uri.scheme == "http" || uri.scheme == "https"
                // On garde le site Warri dans la WebView ; le reste (wa.me, tel:,
                // mailto:, autres sites) part vers l'app système appropriée.
                if (isHttp && uri.host == allowedHost) return false
                return try {
                    startActivity(Intent(Intent.ACTION_VIEW, uri))
                    true
                } catch (e: Exception) {
                    false
                }
            }
        }

        // Téléchargements (exports CSV/PDF) : passés au gestionnaire système avec
        // le cookie de session pour rester authentifié.
        web.setDownloadListener { url, _, contentDisposition, mimeType, _ ->
            try {
                val req = DownloadManager.Request(Uri.parse(url)).apply {
                    setMimeType(mimeType)
                    addRequestHeader("Cookie", CookieManager.getInstance().getCookie(url))
                    setNotificationVisibility(
                        DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED
                    )
                    val name = URLUtil.guessFileName(url, contentDisposition, mimeType)
                    setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name)
                }
                (getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager).enqueue(req)
            } catch (e: Exception) {
                startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
            }
        }

        onBackPressedDispatcher.addCallback(this) {
            if (web.canGoBack()) web.goBack() else finish()
        }

        if (savedInstanceState == null) web.loadUrl(startUrl)
    }

    fun hasSmsPermission(): Boolean =
        ContextCompat.checkSelfPermission(this, Manifest.permission.RECEIVE_SMS) ==
                PackageManager.PERMISSION_GRANTED

    fun askSmsPermissionIfNeeded() {
        val needed = mutableListOf(Manifest.permission.RECEIVE_SMS)
        if (Build.VERSION.SDK_INT >= 33) needed.add(Manifest.permission.POST_NOTIFICATIONS)
        val missing = needed.filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }
        if (missing.isNotEmpty()) permsLauncher.launch(missing.toTypedArray())
        // Sans exemption batterie, Xiaomi/Redmi & co finissent par bloquer la
        // lecture en arrière-plan : on la demande dans la foulée.
        requestIgnoreBattery()
    }

    /** Fiche « Infos application » de Warri (autorisations, batterie…). */
    fun openAppSettings() {
        try {
            startActivity(
                Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                       Uri.parse("package:$packageName")))
        } catch (e: Exception) { /* réglages indisponibles : tant pis */ }
    }

    fun isIgnoringBattery(): Boolean {
        val pm = getSystemService(Context.POWER_SERVICE) as android.os.PowerManager
        return pm.isIgnoringBatteryOptimizations(packageName)
    }

    /** Demande au système d'exempter Warri de l'économie de batterie. */
    fun requestIgnoreBattery() {
        try {
            if (!isIgnoringBattery()) {
                startActivity(
                    Intent(android.provider.Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                           Uri.parse("package:$packageName")))
            }
        } catch (e: Exception) { /* certains téléphones n'ont pas cet écran */ }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        web.saveState(outState)
    }

    override fun onRestoreInstanceState(savedInstanceState: Bundle) {
        super.onRestoreInstanceState(savedInstanceState)
        web.restoreState(savedInstanceState)
    }
}
