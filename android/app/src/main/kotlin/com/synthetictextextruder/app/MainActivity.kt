package com.synthetictextextruder.app

import android.annotation.SuppressLint
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.DocumentsContract
import android.provider.MediaStore
import android.util.Base64
import android.view.Gravity
import android.view.ViewGroup
import android.webkit.JavascriptInterface
import android.webkit.MimeTypeMap
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.ProgressBar
import android.widget.TextView
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.browser.customtabs.CustomTabsIntent
import androidx.core.content.FileProvider
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import androidx.window.layout.FoldingFeature
import androidx.window.layout.WindowInfoTracker
import androidx.window.layout.WindowLayoutInfo
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File

class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private var filePathCallback: ValueCallback<Array<Uri>>? = null
    private var pendingCameraUri: Uri? = null
    private var pendingFolderPick: PendingFolderPick? = null
    private var serverOrigin: String? = null
    private var lastPostureJson: String? = null

    private data class PendingFolderPick(
        val requestId: String,
        val already: Int,
        val recursive: Boolean
    )

    private data class TreeChildEntry(
        val docId: String,
        val displayName: String,
        val mimeType: String,
        val flags: Int
    )

    private val openFolderTreeLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        val req = pendingFolderPick
        pendingFolderPick = null
        if (req == null) return@registerForActivityResult

        val treeUri = if (result.resultCode == RESULT_OK) result.data?.data else null
        if (treeUri == null) {
            resolveNativeRequest(
                req.requestId,
                JSONObject().put("ok", false).put("cancelled", true).toString()
            )
            return@registerForActivityResult
        }

        lifecycleScope.launch(Dispatchers.IO) {
            val stagedDir = File(cacheDir, "picked_folder_${System.nanoTime()}").apply { mkdirs() }
            try {
                val folderName = resolveTreeFolderName(treeUri)
                stageDocumentTree(treeUri, stagedDir, req.recursive)
                val py = Python.getInstance()
                val serverMod = py.getModule("synthetic_text_extruder.android_server")
                val jsonResult = serverMod.callAttr(
                    "import_picked_folder_json",
                    stagedDir.absolutePath,
                    folderName,
                    req.already,
                    req.recursive
                ).toString()
                resolveNativeRequest(req.requestId, jsonResult)
            } catch (exc: Throwable) {
                resolveNativeRequest(
                    req.requestId,
                    JSONObject()
                        .put("ok", false)
                        .put("error", exc.message ?: "Folder import failed")
                        .toString()
                )
            } finally {
                try {
                    stagedDir.deleteRecursively()
                } catch (_: Throwable) {
                }
            }
        }
    }

    private val openDocumentsLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        val cb = filePathCallback
        filePathCallback = null
        if (cb == null) return@registerForActivityResult

        val uris = mutableListOf<Uri>()
        if (result.resultCode == RESULT_OK) {
            val data = result.data
            if (data != null) {
                val clip = data.clipData
                if (clip != null && clip.itemCount > 0) {
                    for (i in 0 until clip.itemCount) {
                        clip.getItemAt(i)?.uri?.let { uris.add(it) }
                    }
                } else {
                    data.data?.let { uris.add(it) }
                }
            } else {
                pendingCameraUri?.let { uris.add(it) }
            }
        }
        pendingCameraUri = null
        cb.onReceiveValue(if (uris.isEmpty()) null else uris.toTypedArray())
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        AndroidMediaBridge.init(applicationContext)

        val root = FrameLayout(this)
        val loadingBox = FrameLayout(this)
        val spinner = ProgressBar(this)
        val spinnerParams = FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.WRAP_CONTENT,
            ViewGroup.LayoutParams.WRAP_CONTENT,
            Gravity.CENTER
        )
        loadingBox.addView(spinner, spinnerParams)

        val label = TextView(this).apply {
            text = "Starting Synthetic Text Extruder…"
            textSize = 15f
        }
        val labelParams = FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.WRAP_CONTENT,
            ViewGroup.LayoutParams.WRAP_CONTENT,
            Gravity.CENTER
        ).apply {
            topMargin = (96 * resources.displayMetrics.density).toInt()
        }
        loadingBox.addView(label, labelParams)

        webView = WebView(this).apply {
            visibility = WebView.INVISIBLE
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.allowFileAccess = true
            settings.mediaPlaybackRequiresUserGesture = false
            settings.mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            addJavascriptInterface(AndroidHostBridge(), "AndroidHost")
            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(
                    view: WebView?,
                    request: WebResourceRequest?
                ): Boolean {
                    val uri = request?.url ?: return false
                    val origin = serverOrigin
                    if (origin != null && uri.toString().startsWith(origin)) {
                        return false
                    }
                    openInCustomTab(uri.toString())
                    return true
                }

                override fun onPageFinished(view: WebView?, url: String?) {
                    super.onPageFinished(view, url)
                    webView.visibility = WebView.VISIBLE
                    loadingBox.visibility = FrameLayout.GONE
                    lastPostureJson?.let { pushPostureToWebView(it) }
                }
            }
            webChromeClient = object : WebChromeClient() {
                override fun onShowFileChooser(
                    webView: WebView?,
                    filePathCallback: ValueCallback<Array<Uri>>?,
                    fileChooserParams: FileChooserParams?
                ): Boolean {
                    this@MainActivity.filePathCallback?.onReceiveValue(null)
                    this@MainActivity.filePathCallback = filePathCallback
                    launchFileChooser(fileChooserParams)
                    return true
                }
            }
        }

        root.addView(
            webView,
            FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            )
        )
        root.addView(
            loadingBox,
            FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            )
        )
        setContentView(root)

        onBackPressedDispatcher.addCallback(
            this,
            object : OnBackPressedCallback(true) {
                override fun handleOnBackPressed() {
                    if (webView.canGoBack()) {
                        webView.goBack()
                    } else {
                        isEnabled = false
                        onBackPressedDispatcher.onBackPressed()
                    }
                }
            }
        )

        observeFoldablePosture()

        lifecycleScope.launch {
            try {
                val url = withContext(Dispatchers.IO) { startEmbeddedPythonServer() }
                webView.loadUrl(url)
            } catch (exc: Throwable) {
                label.text = "Failed to start embedded engine:\n${exc.message}"
                spinner.visibility = ProgressBar.GONE
            }
        }
    }

    private fun startEmbeddedPythonServer(): String {
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(this))
        }
        val py = Python.getInstance()
        val serverMod = py.getModule("synthetic_text_extruder.android_server")
        val opener = BrowserOpenerCallback { url ->
            runOnUiThread {
                // Keep outbound DNS/network alive while Chrome Custom Tabs is in foreground (Android 15+)
                if (url.contains("accounts.google.com") || url.contains("oauth")) {
                    GenerationForegroundService.start(this, "Signing in to Google Workspace…")
                }
                openInCustomTab(url)
            }
        }
        val info: PyObject = serverMod.callAttr(
            "start_android_server",
            filesDir.absolutePath,
            opener
        )
        val origin = info.callAttr("get", "origin")?.toString()
        val url = info.callAttr("get", "url")?.toString()
            ?: throw IllegalStateException("Android server returned no URL")
        serverOrigin = origin
        return url
    }

    private fun launchFileChooser(params: WebChromeClient.FileChooserParams?) {
        val acceptTypes = params?.acceptTypes?.filter { it.isNotBlank() } ?: emptyList()
        val captureEnabled = params?.isCaptureEnabled == true
        val allowMultiple = params?.mode == WebChromeClient.FileChooserParams.MODE_OPEN_MULTIPLE

        if (captureEnabled && acceptTypes.any { it.startsWith("image/") }) {
            val camDir = File(cacheDir, "camera").apply { mkdirs() }
            val photoFile = File(camDir, "capture_${System.currentTimeMillis()}.jpg")
            val photoUri = FileProvider.getUriForFile(
                this,
                "${packageName}.fileprovider",
                photoFile
            )
            pendingCameraUri = photoUri
            val camIntent = Intent(MediaStore.ACTION_IMAGE_CAPTURE).apply {
                putExtra(MediaStore.EXTRA_OUTPUT, photoUri)
                addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION or Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            openDocumentsLauncher.launch(camIntent)
            return
        }

        val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = if (acceptTypes.size == 1 && acceptTypes[0].contains("/")) {
                acceptTypes[0]
            } else {
                "*/*"
            }
            if (acceptTypes.size > 1) {
                val mimes = acceptTypes.filter { it.contains("/") }.toTypedArray()
                if (mimes.isNotEmpty()) {
                    putExtra(Intent.EXTRA_MIME_TYPES, mimes)
                }
            }
            putExtra(Intent.EXTRA_ALLOW_MULTIPLE, allowMultiple)
        }
        openDocumentsLauncher.launch(intent)
    }

    private fun observeFoldablePosture() {
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                WindowInfoTracker.getOrCreate(this@MainActivity)
                    .windowLayoutInfo(this@MainActivity)
                    .collect { layoutInfo ->
                        updatePosture(layoutInfo)
                    }
            }
        }
    }

    private fun updatePosture(layoutInfo: WindowLayoutInfo) {
        val dm = resources.displayMetrics
        val widthDp = dm.widthPixels / dm.density
        val folding = layoutInfo.displayFeatures
            .filterIsInstance<FoldingFeature>()
            .firstOrNull()

        var foldOrientation = "none"
        var hingeLeftDp = 0f
        var hingeWidthDp = 0f
        var hingeTopDp = 0f
        var hingeHeightDp = 0f
        var posture = if (widthDp >= 680f) "expanded" else "compact"

        if (folding != null) {
            val bounds = folding.bounds
            hingeLeftDp = bounds.left / dm.density
            hingeWidthDp = bounds.width() / dm.density
            hingeTopDp = bounds.top / dm.density
            hingeHeightDp = bounds.height() / dm.density
            foldOrientation = when (folding.orientation) {
                FoldingFeature.Orientation.VERTICAL -> "vertical"
                FoldingFeature.Orientation.HORIZONTAL -> "horizontal"
                else -> "none"
            }
            posture = when {
                folding.state == FoldingFeature.State.HALF_OPENED &&
                    folding.orientation == FoldingFeature.Orientation.HORIZONTAL -> "tabletop"
                folding.orientation == FoldingFeature.Orientation.VERTICAL && widthDp >= 600f -> "expanded"
                widthDp >= 680f -> "expanded"
                else -> "compact"
            }
        }

        val payload = JSONObject().apply {
            put("posture", posture)
            put("foldOrientation", foldOrientation)
            put("hingeLeftDp", hingeLeftDp)
            put("hingeWidthDp", hingeWidthDp)
            put("hingeTopDp", hingeTopDp)
            put("hingeHeightDp", hingeHeightDp)
        }.toString()

        lastPostureJson = payload
        pushPostureToWebView(payload)
    }

    private fun pushPostureToWebView(payloadJson: String) {
        if (!::webView.isInitialized) return
        webView.post {
            webView.evaluateJavascript(
                "window.__STE_NATIVE_POSTURE_LOCK__=true; if (window.__STE_SET_POSTURE__) window.__STE_SET_POSTURE__($payloadJson);",
                null
            )
        }
    }

    private fun openInCustomTab(url: String) {
        try {
            CustomTabsIntent.Builder().build().launchUrl(this, Uri.parse(url))
        } catch (_: Throwable) {
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
        }
    }

    private fun resolveNativeRequest(requestId: String, resultJson: String) {
        if (!::webView.isInitialized) return
        val safeId = JSONObject.quote(requestId)
        val safeJson = JSONObject.quote(resultJson)
        webView.post {
            webView.evaluateJavascript(
                "if (window.__STE_RESOLVE_NATIVE_REQUEST__) window.__STE_RESOLVE_NATIVE_REQUEST__($safeId, $safeJson);",
                null
            )
        }
    }

    private fun resolveTreeFolderName(treeUri: Uri): String {
        val treeDocId = try {
            DocumentsContract.getTreeDocumentId(treeUri)
        } catch (_: Throwable) {
            ""
        }
        if (treeDocId.isNotEmpty()) {
            val docUri = DocumentsContract.buildDocumentUriUsingTree(treeUri, treeDocId)
            try {
                contentResolver.query(
                    docUri,
                    arrayOf(DocumentsContract.Document.COLUMN_DISPLAY_NAME),
                    null,
                    null,
                    null
                )?.use { cursor ->
                    if (cursor.moveToFirst()) {
                        val name = cursor.getString(0)?.trim().orEmpty()
                        if (name.isNotEmpty()) return name
                    }
                }
            } catch (_: Throwable) {
            }
            val fallback = treeDocId
                .substringAfterLast(':')
                .trim('/')
                .substringAfterLast('/')
                .trim()
            if (fallback.isNotEmpty()) return fallback
        }
        return "Folder"
    }

    private fun stageDocumentTree(treeUri: Uri, rootDest: File, recursive: Boolean) {
        val rootDocId = DocumentsContract.getTreeDocumentId(treeUri)
        val visitedDirs = mutableSetOf<String>()
        var stagedCount = 0
        val maxStagedFiles = 105
        val rejectedSuffixes = setOf(
            ".exe", ".dll", ".so", ".dylib", ".bin", ".msi", ".sys", ".com",
            ".pif", ".scr", ".cpl", ".iso", ".img", ".dmg",
            ".tar", ".gz", ".zip", ".rar", ".7z", ".cab", ".xz", ".bz2",
            ".apk", ".aab", ".dex"
        )

        fun sanitizeSegment(raw: String, fallback: String): String {
            val cleaned = raw.replace('/', '_').replace('\\', '_').trim()
            if (cleaned.isEmpty() || cleaned == "." || cleaned == "..") return fallback
            return cleaned
        }

        fun uniqueDestFile(dir: File, name: String): File {
            val initial = File(dir, name)
            if (!initial.exists()) return initial
            val dot = name.lastIndexOf('.')
            val stem = if (dot > 0) name.substring(0, dot) else name
            val suffix = if (dot > 0) name.substring(dot) else ""
            for (n in 1..1000) {
                val cand = File(dir, "${stem}_$n$suffix")
                if (!cand.exists()) return cand
            }
            return File(dir, "${System.nanoTime()}_$name")
        }

        fun walk(dirDocId: String, destDir: File, depth: Int) {
            if (stagedCount >= maxStagedFiles || depth > 16) return
            if (!visitedDirs.add(dirDocId)) return
            destDir.mkdirs()

            val childrenUri = DocumentsContract.buildChildDocumentsUriUsingTree(treeUri, dirDocId)
            val entries = mutableListOf<TreeChildEntry>()
            try {
                contentResolver.query(
                    childrenUri,
                    arrayOf(
                        DocumentsContract.Document.COLUMN_DOCUMENT_ID,
                        DocumentsContract.Document.COLUMN_DISPLAY_NAME,
                        DocumentsContract.Document.COLUMN_MIME_TYPE,
                        DocumentsContract.Document.COLUMN_FLAGS
                    ),
                    null,
                    null,
                    null
                )?.use { cursor ->
                    while (cursor.moveToNext()) {
                        val cid = cursor.getString(0) ?: continue
                        val cname = cursor.getString(1)?.trim().orEmpty()
                        val cmime = cursor.getString(2)?.trim().orEmpty()
                        val cflags = if (!cursor.isNull(3)) cursor.getInt(3) else 0
                        entries.add(TreeChildEntry(cid, cname, cmime, cflags))
                    }
                }
            } catch (_: Throwable) {
                return
            }

            entries.sortBy { it.displayName.lowercase() }

            for (entry in entries) {
                if (stagedCount >= maxStagedFiles) break
                val rawName = entry.displayName
                if (rawName.isEmpty() || rawName.startsWith(".")) continue

                if (entry.mimeType == DocumentsContract.Document.MIME_TYPE_DIR) {
                    if (recursive) {
                        val subDir = File(destDir, sanitizeSegment(rawName, "subfolder"))
                        walk(entry.docId, subDir, depth + 1)
                    }
                    continue
                }

                if ((entry.flags and DocumentsContract.Document.FLAG_VIRTUAL_DOCUMENT) != 0) {
                    continue
                }

                var safeName = sanitizeSegment(rawName, "file")
                if (!safeName.contains('.') && entry.mimeType.isNotEmpty()) {
                    val ext = MimeTypeMap.getSingleton().getExtensionFromMimeType(entry.mimeType)
                    if (!ext.isNullOrBlank()) {
                        safeName = "$safeName.$ext"
                    }
                }
                val dotIdx = safeName.lastIndexOf('.')
                val lowerExt = if (dotIdx >= 0) safeName.substring(dotIdx).lowercase() else ""
                if (lowerExt in rejectedSuffixes) continue

                val childUri = DocumentsContract.buildDocumentUriUsingTree(treeUri, entry.docId)
                val destFile = uniqueDestFile(destDir, safeName)
                try {
                    val copied = contentResolver.openInputStream(childUri)?.use { input ->
                        destFile.outputStream().use { output ->
                            input.copyTo(output)
                        }
                        true
                    } ?: false
                    if (copied) {
                        stagedCount += 1
                    } else {
                        destFile.delete()
                    }
                } catch (_: Throwable) {
                    destFile.delete()
                }
            }
        }

        walk(rootDocId, rootDest, 0)
    }

    private fun shareFileToSheet(file: File, mimeType: String) {
        val uri = FileProvider.getUriForFile(this, "${packageName}.fileprovider", file)
        val share = Intent(Intent.ACTION_SEND).apply {
            type = mimeType.ifBlank { "application/octet-stream" }
            putExtra(Intent.EXTRA_STREAM, uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        startActivity(Intent.createChooser(share, "Share or Save ${file.name}"))
    }

    inner class BrowserOpenerCallback(private val handler: (String) -> Unit) {
        @Suppress("unused")
        fun openUrl(url: String) {
            handler(url)
        }
    }

    inner class AndroidHostBridge {
        @JavascriptInterface
        fun shareTextFile(filename: String, mimeType: String, content: String): Boolean {
            return try {
                val safe = File(filename.ifBlank { "export.txt" }).name
                val outDir = File(cacheDir, "exports").apply { mkdirs() }
                val dest = File(outDir, safe)
                dest.writeText(content, Charsets.UTF_8)
                runOnUiThread { shareFileToSheet(dest, mimeType) }
                true
            } catch (_: Throwable) {
                false
            }
        }

        @JavascriptInterface
        fun shareBinaryFile(filename: String, mimeType: String, base64Data: String): Boolean {
            return try {
                val safe = File(filename.ifBlank { "export.bin" }).name
                val outDir = File(cacheDir, "exports").apply { mkdirs() }
                val dest = File(outDir, safe)
                dest.writeBytes(Base64.decode(base64Data, Base64.DEFAULT))
                runOnUiThread { shareFileToSheet(dest, mimeType) }
                true
            } catch (_: Throwable) {
                false
            }
        }

        @JavascriptInterface
        fun pickStudioFolder(requestId: String, already: Int, recursive: Boolean): Boolean {
            if (requestId.isBlank()) return false
            runOnUiThread {
                pendingFolderPick?.let { prev ->
                    resolveNativeRequest(
                        prev.requestId,
                        JSONObject().put("ok", false).put("cancelled", true).toString()
                    )
                }
                pendingFolderPick = PendingFolderPick(requestId, already, recursive)
                try {
                    val intent = Intent(Intent.ACTION_OPEN_DOCUMENT_TREE).apply {
                        addFlags(
                            Intent.FLAG_GRANT_READ_URI_PERMISSION or
                                Intent.FLAG_GRANT_PREFIX_URI_PERMISSION
                        )
                    }
                    openFolderTreeLauncher.launch(intent)
                } catch (exc: Throwable) {
                    pendingFolderPick = null
                    resolveNativeRequest(
                        requestId,
                        JSONObject()
                            .put("ok", false)
                            .put("error", exc.message ?: "Folder picker unavailable")
                            .toString()
                    )
                }
            }
            return true
        }

        @JavascriptInterface
        fun startForegroundJob(message: String) {
            runOnUiThread {
                GenerationForegroundService.start(this@MainActivity, message)
            }
        }

        @JavascriptInterface
        fun stopForegroundJob() {
            runOnUiThread {
                GenerationForegroundService.stop(this@MainActivity)
            }
        }
    }
}
