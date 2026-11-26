# Keep AndroidHost JS interface and Chaquopy entrypoints intact
-keepclassmembers class com.synthetictextextruder.app.MainActivity$AndroidHostBridge {
    @android.webkit.JavascriptInterface <methods>;
}
