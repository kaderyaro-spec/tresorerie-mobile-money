# Conserver les interfaces JavaScript exposées à la WebView.
-keepclassmembers class ci.warri.app.WarriBridge {
   @android.webkit.JavascriptInterface <methods>;
}
