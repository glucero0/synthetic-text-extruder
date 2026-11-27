package com.synthetictextextruder.app

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import android.media.MediaMetadataRetriever
import android.media.MediaMuxer
import android.net.Uri
import android.os.Handler
import android.os.Looper
import androidx.annotation.OptIn
import androidx.media3.common.Effect
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.common.util.UnstableApi
import androidx.media3.decoder.ffmpeg.FfmpegLibrary
import androidx.media3.effect.Brightness
import androidx.media3.effect.Contrast
import androidx.media3.effect.Crop
import androidx.media3.effect.GaussianBlur
import androidx.media3.effect.HslAdjustment
import androidx.media3.effect.Presentation
import androidx.media3.effect.RgbAdjustment
import androidx.media3.effect.RgbFilter
import androidx.media3.effect.RgbMatrix
import androidx.media3.effect.ScaleAndRotateTransformation
import androidx.media3.transformer.Composition
import androidx.media3.transformer.EditedMediaItem
import androidx.media3.transformer.EditedMediaItemSequence
import androidx.media3.transformer.Effects
import androidx.media3.transformer.ExportException
import androidx.media3.transformer.ExportResult
import androidx.media3.transformer.Transformer
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.nio.ByteBuffer
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.roundToInt
import kotlin.math.roundToLong

/**
 * Hardware-accelerated Android video/audio bridge powered by AndroidX Media3 Transformer,
 * Media3 Effect, Media3 FFmpeg decoder extension, and Android SDK MediaMetadataRetriever.
 *
 * Invoked from Python (`synthetic_text_extruder.video_edit`) via Chaquopy on background worker threads.
 */
@OptIn(UnstableApi::class)
object AndroidMediaBridge {

    @Volatile
    private var appContext: Context? = null

    @JvmStatic
    fun init(context: Context) {
        appContext = context.applicationContext
    }

    private fun requireContext(): Context {
        return appContext
            ?: throw IllegalStateException("AndroidMediaBridge has not been initialized")
    }

    @JvmStatic
    fun statusJson(): String {
        val ctx = appContext
        if (ctx == null) {
            return JSONObject()
                .put("ok", false)
                .put("error", "Android media engine is not initialized.")
                .toString()
        }
        val ffmpegLoaded = try {
            FfmpegLibrary.isAvailable()
        } catch (_: Throwable) {
            false
        }
        val ffmpegVer = try {
            if (ffmpegLoaded) FfmpegLibrary.getVersion() ?: "" else ""
        } catch (_: Throwable) {
            ""
        }
        val label = if (ffmpegVer.isNotBlank()) {
            "AndroidX Media3 1.8.0 (FFmpeg $ffmpegVer)"
        } else {
            "AndroidX Media3 1.8.0"
        }
        return JSONObject()
            .put("ok", true)
            .put("backend", "media3")
            .put("ffmpeg", "androidx.media3.transformer")
            .put("ffprobe", "android.media.MediaMetadataRetriever")
            .put("ffmpegDecoder", ffmpegLoaded)
            .put("version", label)
            .toString()
    }

    @JvmStatic
    fun probeVideoInfoJson(path: String): String {
        val file = File(path)
        if (!file.isFile) {
            throw IllegalArgumentException("Video not found: $path")
        }

        var durationSec = 0.0
        var width = 0
        var height = 0
        var rotation = 0
        var hasAudio = false
        var videoCodec = ""

        val retriever = MediaMetadataRetriever()
        try {
            retriever.setDataSource(file.absolutePath)
            durationSec = (retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)
                ?.toLongOrNull() ?: 0L) / 1000.0
            width = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH)
                ?.toIntOrNull() ?: 0
            height = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT)
                ?.toIntOrNull() ?: 0
            rotation = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_ROTATION)
                ?.toIntOrNull() ?: 0
            val audioMeta = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_HAS_AUDIO)
            if (!audioMeta.isNullOrBlank() && audioMeta.lowercase() != "no") {
                hasAudio = true
            }
        } finally {
            try {
                retriever.release()
            } catch (_: Throwable) {
            }
        }

        val extractor = MediaExtractor()
        try {
            extractor.setDataSource(file.absolutePath)
            for (i in 0 until extractor.trackCount) {
                val fmt = extractor.getTrackFormat(i)
                val mime = fmt.getString(MediaFormat.KEY_MIME).orEmpty()
                if (mime.startsWith("video/") && videoCodec.isEmpty()) {
                    videoCodec = shortCodecName(mime)
                    if (width <= 0 && fmt.containsKey(MediaFormat.KEY_WIDTH)) {
                        width = fmt.getInteger(MediaFormat.KEY_WIDTH)
                    }
                    if (height <= 0 && fmt.containsKey(MediaFormat.KEY_HEIGHT)) {
                        height = fmt.getInteger(MediaFormat.KEY_HEIGHT)
                    }
                    if (durationSec <= 0.0 && fmt.containsKey(MediaFormat.KEY_DURATION)) {
                        durationSec = fmt.getLong(MediaFormat.KEY_DURATION) / 1_000_000.0
                    }
                } else if (mime.startsWith("audio/")) {
                    hasAudio = true
                }
            }
        } catch (_: Throwable) {
        } finally {
            try {
                extractor.release()
            } catch (_: Throwable) {
            }
        }

        val normRot = ((rotation % 360) + 360) % 360
        if (normRot == 90 || normRot == 270) {
            val tmp = width
            width = height
            height = tmp
        }

        return JSONObject()
            .put("duration", durationSec)
            .put("width", width)
            .put("height", height)
            .put("codec", videoCodec.ifEmpty { "h264" })
            .put("size", file.length())
            .put("hasAudio", hasAudio)
            .toString()
    }

    @JvmStatic
    fun hasAudioStream(path: String): Boolean {
        val file = File(path)
        if (!file.isFile) {
            throw IllegalArgumentException("Video not found: $path")
        }
        val extractor = MediaExtractor()
        try {
            extractor.setDataSource(file.absolutePath)
            for (i in 0 until extractor.trackCount) {
                val mime = extractor.getTrackFormat(i).getString(MediaFormat.KEY_MIME).orEmpty()
                if (mime.startsWith("audio/")) return true
            }
            return false
        } catch (_: Throwable) {
            val retriever = MediaMetadataRetriever()
            return try {
                retriever.setDataSource(file.absolutePath)
                val meta = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_HAS_AUDIO)
                !meta.isNullOrBlank() && meta.lowercase() != "no"
            } finally {
                try {
                    retriever.release()
                } catch (_: Throwable) {
                }
            }
        } finally {
            try {
                extractor.release()
            } catch (_: Throwable) {
            }
        }
    }

    @JvmStatic
    fun extractFramePng(path: String, atSeconds: Double): ByteArray {
        val file = File(path)
        if (!file.isFile) {
            throw IllegalArgumentException("Video not found: $path")
        }
        val timeUs = (max(0.0, atSeconds) * 1_000_000.0).roundToLong()
        val retriever = MediaMetadataRetriever()
        try {
            retriever.setDataSource(file.absolutePath)
            val bitmap: Bitmap = retriever.getFrameAtTime(
                timeUs,
                MediaMetadataRetriever.OPTION_CLOSEST
            )
                ?: retriever.getFrameAtTime(timeUs, MediaMetadataRetriever.OPTION_CLOSEST_SYNC)
                ?: retriever.getFrameAtTime(0L)
                ?: throw RuntimeException("Could not decode a video frame from ${file.name}")
            try {
                val out = ByteArrayOutputStream()
                if (!bitmap.compress(Bitmap.CompressFormat.PNG, 100, out)) {
                    throw RuntimeException("Failed to encode video frame as PNG")
                }
                return out.toByteArray()
            } finally {
                bitmap.recycle()
            }
        } finally {
            try {
                retriever.release()
            } catch (_: Throwable) {
            }
        }
    }

    @JvmStatic
    fun extractAudioM4a(path: String, maxSeconds: Double): ByteArray {
        val ctx = requireContext()
        val src = File(path)
        if (!src.isFile) {
            throw IllegalArgumentException("Video not found: $path")
        }
        val outFile = File(ctx.cacheDir, "ste_audio_${System.nanoTime()}.m4a")
        try {
            // Fast lossless AAC remux first if the track is already MP4-muxable AAC
            if (remuxAudioTrackToM4a(src, outFile, maxSeconds) && outFile.isFile && outFile.length() >= 32L) {
                return outFile.readBytes()
            }
            outFile.delete()

            // Otherwise transcode audio track to AAC via Media3 Transformer
            val mediaBuilder = MediaItem.Builder().setUri(Uri.fromFile(src))
            if (maxSeconds > 0.0) {
                val clip = MediaItem.ClippingConfiguration.Builder()
                    .setStartPositionMs(0L)
                    .setEndPositionMs((maxSeconds * 1000.0).roundToLong())
                    .build()
                mediaBuilder.setClippingConfiguration(clip)
            }
            val edited = EditedMediaItem.Builder(mediaBuilder.build())
                .setRemoveVideo(true)
                .build()
            val composition = Composition.Builder(EditedMediaItemSequence(listOf(edited))).build()
            runTransformerBlocking(
                ctx = ctx,
                composition = composition,
                outputPath = outFile.absolutePath,
                videoMimeType = null,
                audioMimeType = MimeTypes.AUDIO_AAC,
                timeoutSeconds = 300L
            )
            if (!outFile.isFile || outFile.length() < 32L) {
                throw RuntimeException("Could not extract audio from video.")
            }
            return outFile.readBytes()
        } finally {
            outFile.delete()
        }
    }

    @JvmStatic
    fun extractClipMp4(path: String, maxSeconds: Double): ByteArray {
        val ctx = requireContext()
        val src = File(path)
        if (!src.isFile) {
            throw IllegalArgumentException("Video not found: $path")
        }
        val durMs = (max(1.0, maxSeconds) * 1000.0).roundToLong()
        val outFile = File(ctx.cacheDir, "ste_clip_${System.nanoTime()}.mp4")
        try {
            val clip = MediaItem.ClippingConfiguration.Builder()
                .setStartPositionMs(0L)
                .setEndPositionMs(durMs)
                .build()
            val item = MediaItem.Builder()
                .setUri(Uri.fromFile(src))
                .setClippingConfiguration(clip)
                .build()
            val edited = EditedMediaItem.Builder(item)
                .setRemoveAudio(true)
                .build()
            val composition = Composition.Builder(EditedMediaItemSequence(listOf(edited))).build()
            runTransformerBlocking(
                ctx = ctx,
                composition = composition,
                outputPath = outFile.absolutePath,
                videoMimeType = MimeTypes.VIDEO_H264,
                audioMimeType = null,
                timeoutSeconds = 300L
            )
            if (!outFile.isFile || outFile.length() == 0L) {
                throw RuntimeException("Could not prepare a short video clip.")
            }
            return outFile.readBytes()
        } finally {
            outFile.delete()
        }
    }

    @JvmStatic
    fun applyEdits(srcPath: String, destPath: String, optionsJson: String): String {
        val ctx = requireContext()
        val src = File(srcPath)
        if (!src.isFile) {
            throw IllegalArgumentException("Video not found: $srcPath")
        }
        val dest = File(destPath)
        dest.parentFile?.mkdirs()
        if (dest.exists()) dest.delete()

        val opts = if (optionsJson.isNotBlank()) JSONObject(optionsJson) else JSONObject()
        val probe = JSONObject(probeVideoInfoJson(src.absolutePath))
        val srcW = probe.optInt("width", 0)
        val srcH = probe.optInt("height", 0)
        val hasAudio = probe.optBoolean("hasAudio", false)

        val effects = buildVideoEffects(
            filters = opts.optJSONObject("filters"),
            crop = opts.optJSONObject("crop"),
            rotation = opts.optDouble("rotation", 0.0).toFloat(),
            sourceWidth = srcW,
            sourceHeight = srcH
        )

        val rangesMs = mutableListOf<Pair<Long, Long?>>()
        val segmentsArr = opts.optJSONArray("segments")
        if (segmentsArr != null && segmentsArr.length() > 0) {
            for (i in 0 until segmentsArr.length()) {
                val seg = segmentsArr.optJSONObject(i) ?: continue
                val sMs = (max(0.0, seg.optDouble("start", 0.0)) * 1000.0).roundToLong()
                val eSec = seg.optDouble("end", -1.0)
                val eMs = if (eSec > 0.0) (eSec * 1000.0).roundToLong() else null
                if (eMs != null && eMs - sMs < 40L) continue
                rangesMs.add(sMs to eMs)
            }
        } else {
            val trim = opts.optJSONObject("trim")
            if (trim != null) {
                val sMs = (max(0.0, trim.optDouble("start", 0.0)) * 1000.0).roundToLong()
                val eSec = if (trim.has("end") && !trim.isNull("end")) trim.optDouble("end", -1.0) else -1.0
                val eMs = if (eSec > 0.0 && eSec * 1000.0 > sMs) (eSec * 1000.0).roundToLong() else null
                rangesMs.add(sMs to eMs)
            } else {
                rangesMs.add(0L to null)
            }
        }

        if (rangesMs.isEmpty()) {
            throw IllegalArgumentException("At least one valid segment is required")
        }

        fun buildComposition(removeAudio: Boolean): Composition {
            val items = rangesMs.map { (startMs, endMs) ->
                val itemBuilder = MediaItem.Builder().setUri(Uri.fromFile(src))
                if (startMs > 0L || endMs != null) {
                    val clipBuilder = MediaItem.ClippingConfiguration.Builder()
                        .setStartPositionMs(startMs)
                    if (endMs != null) {
                        clipBuilder.setEndPositionMs(endMs)
                    }
                    itemBuilder.setClippingConfiguration(clipBuilder.build())
                }
                EditedMediaItem.Builder(itemBuilder.build())
                    .setRemoveAudio(removeAudio)
                    .setEffects(Effects(emptyList(), effects))
                    .build()
            }
            return Composition.Builder(EditedMediaItemSequence(items)).build()
        }

        try {
            runTransformerBlocking(
                ctx = ctx,
                composition = buildComposition(removeAudio = !hasAudio),
                outputPath = dest.absolutePath,
                videoMimeType = MimeTypes.VIDEO_H264,
                audioMimeType = if (hasAudio) MimeTypes.AUDIO_AAC else null,
                timeoutSeconds = 900L
            )
        } catch (firstErr: Throwable) {
            if (!hasAudio) throw firstErr
            dest.delete()
            runTransformerBlocking(
                ctx = ctx,
                composition = buildComposition(removeAudio = true),
                outputPath = dest.absolutePath,
                videoMimeType = MimeTypes.VIDEO_H264,
                audioMimeType = null,
                timeoutSeconds = 900L
            )
        }

        if (!dest.isFile || dest.length() == 0L) {
            throw RuntimeException("Media3 video edit produced an empty file")
        }
        return dest.absolutePath
    }

    @JvmStatic
    fun concatVideos(pathsJson: String, destPath: String): String {
        val ctx = requireContext()
        val arr = JSONArray(pathsJson)
        if (arr.length() < 2) {
            throw IllegalArgumentException("Need at least two videos to splice")
        }
        val files = mutableListOf<File>()
        for (i in 0 until arr.length()) {
            val f = File(arr.getString(i))
            if (!f.isFile) throw IllegalArgumentException("Video not found: ${f.path}")
            files.add(f)
        }
        val dest = File(destPath)
        dest.parentFile?.mkdirs()
        if (dest.exists()) dest.delete()

        val firstInfo = JSONObject(probeVideoInfoJson(files[0].absolutePath))
        var tw = max(2, firstInfo.optInt("width", 1280))
        var th = max(2, firstInfo.optInt("height", 720))
        tw -= tw % 2
        th -= th % 2

        val anyAudio = files.any { runCatching { hasAudioStream(it.absolutePath) }.getOrDefault(false) }
        val presentation = Presentation.createForWidthAndHeight(
            tw,
            th,
            Presentation.LAYOUT_SCALE_TO_FIT
        )

        fun buildConcatComp(removeAudio: Boolean): Composition {
            val items = files.map { f ->
                EditedMediaItem.Builder(MediaItem.fromUri(Uri.fromFile(f)))
                    .setRemoveAudio(removeAudio)
                    .setEffects(Effects(emptyList(), listOf(presentation)))
                    .build()
            }
            val builder = Composition.Builder(EditedMediaItemSequence(items))
            if (!removeAudio) {
                builder.experimentalSetForceAudioTrack(true)
            }
            return builder.build()
        }

        try {
            runTransformerBlocking(
                ctx = ctx,
                composition = buildConcatComp(removeAudio = !anyAudio),
                outputPath = dest.absolutePath,
                videoMimeType = MimeTypes.VIDEO_H264,
                audioMimeType = if (anyAudio) MimeTypes.AUDIO_AAC else null,
                timeoutSeconds = 1200L
            )
        } catch (firstErr: Throwable) {
            if (!anyAudio) throw firstErr
            dest.delete()
            runTransformerBlocking(
                ctx = ctx,
                composition = buildConcatComp(removeAudio = true),
                outputPath = dest.absolutePath,
                videoMimeType = MimeTypes.VIDEO_H264,
                audioMimeType = null,
                timeoutSeconds = 1200L
            )
        }

        if (!dest.isFile || dest.length() == 0L) {
            throw RuntimeException("Media3 video concat produced an empty file")
        }
        return dest.absolutePath
    }

    @JvmStatic
    fun buildSlideshow(pathsJson: String, destPath: String, secondsPerImage: Double): String {
        val ctx = requireContext()
        val arr = JSONArray(pathsJson)
        val files = mutableListOf<File>()
        for (i in 0 until arr.length()) {
            val f = File(arr.getString(i))
            if (f.isFile) files.add(f)
        }
        if (files.size < 2) {
            throw IllegalArgumentException("Slideshow needs at least two images")
        }
        val dest = File(destPath)
        dest.parentFile?.mkdirs()
        if (dest.exists()) dest.delete()

        val durMs = (secondsPerImage.coerceIn(0.2, 8.0) * 1000.0).roundToLong()
        val (tw, th) = probeTargetImageDimensions(files[0])
        val presentation = Presentation.createForWidthAndHeight(
            tw,
            th,
            Presentation.LAYOUT_SCALE_TO_FIT
        )

        val items = files.map { img ->
            val mediaItem = MediaItem.Builder()
                .setUri(Uri.fromFile(img))
                .setImageDurationMs(durMs)
                .build()
            EditedMediaItem.Builder(mediaItem)
                .setFrameRate(30)
                .setEffects(Effects(emptyList(), listOf(presentation)))
                .build()
        }
        val composition = Composition.Builder(EditedMediaItemSequence(items)).build()
        runTransformerBlocking(
            ctx = ctx,
            composition = composition,
            outputPath = dest.absolutePath,
            videoMimeType = MimeTypes.VIDEO_H264,
            audioMimeType = null,
            timeoutSeconds = 1200L
        )
        if (!dest.isFile || dest.length() == 0L) {
            throw RuntimeException("Media3 slideshow export produced an empty file")
        }
        return dest.absolutePath
    }

    private fun buildVideoEffects(
        filters: JSONObject?,
        crop: JSONObject?,
        rotation: Float,
        sourceWidth: Int,
        sourceHeight: Int
    ): List<Effect> {
        val out = mutableListOf<Effect>()

        if (crop != null) {
            val cwRaw = crop.optDouble("w", 0.0).toFloat()
            val chRaw = crop.optDouble("h", 0.0).toFloat()
            if (cwRaw > 0f && chRaw > 0f) {
                val cxRaw = crop.optDouble("x", 0.0).toFloat()
                val cyRaw = crop.optDouble("y", 0.0).toFloat()
                val isNorm = crop.optBoolean("normalized", false) ||
                    (cwRaw <= 1f && chRaw <= 1f && sourceWidth > 0 && sourceHeight > 0)
                val nx: Float
                val ny: Float
                val nw: Float
                val nh: Float
                if (isNorm) {
                    nx = cxRaw.coerceIn(0f, 0.99f)
                    ny = cyRaw.coerceIn(0f, 0.99f)
                    nw = cwRaw.coerceIn(0.01f, 1f - nx)
                    nh = chRaw.coerceIn(0.01f, 1f - ny)
                } else if (sourceWidth > 0 && sourceHeight > 0) {
                    nx = (cxRaw / sourceWidth).coerceIn(0f, 0.99f)
                    ny = (cyRaw / sourceHeight).coerceIn(0f, 0.99f)
                    nw = (cwRaw / sourceWidth).coerceIn(0.01f, 1f - nx)
                    nh = (chRaw / sourceHeight).coerceIn(0.01f, 1f - ny)
                } else {
                    nx = 0f
                    ny = 0f
                    nw = 1f
                    nh = 1f
                }
                val left = (-1f + 2f * nx).coerceIn(-1f, 0.98f)
                val right = (-1f + 2f * (nx + nw)).coerceIn(left + 0.02f, 1f)
                val top = (1f - 2f * ny).coerceIn(-0.98f, 1f)
                val bottom = (1f - 2f * (ny + nh)).coerceIn(-1f, top - 0.02f)
                out.add(Crop(left, right, bottom, top))
            }
        }

        val cwRot = ((rotation % 360f) + 360f) % 360f
        if (cwRot > 0.01f) {
            val ccwDegrees = ((360f - cwRot) % 360f + 360f) % 360f
            out.add(
                ScaleAndRotateTransformation.Builder()
                    .setRotationDegrees(ccwDegrees)
                    .build()
            )
        }

        if (filters == null) return out

        val brightnessVal = filters.optDouble("brightness", 0.0).toFloat() / 100f +
            (filters.optDouble("exposure", 0.0).toFloat() / 100f) * 0.5f +
            (filters.optDouble("gamma", 1.0).toFloat() - 1f) * 0.2f
        if (abs(brightnessVal) > 1e-4f) {
            out.add(Brightness(brightnessVal.coerceIn(-1f, 1f)))
        }

        val contrastVal = (filters.optDouble("contrast", 0.0).toFloat() / 100f).coerceIn(-1f, 1f)
        if (abs(contrastVal) > 1e-4f) {
            out.add(Contrast(contrastVal))
        }

        val grayscale = filters.optBoolean("grayscale", false)
        val saturation = filters.optDouble("saturation", 100.0).toFloat()
        val hueRotate = filters.optDouble("hueRotate", 0.0).toFloat()
        if (grayscale) {
            out.add(RgbFilter.createGrayscaleFilter())
        } else if (abs(saturation - 100f) > 1e-3f || abs(hueRotate) > 1e-3f) {
            out.add(
                HslAdjustment.Builder()
                    .adjustHue(hueRotate.coerceIn(-180f, 180f))
                    .adjustSaturation((saturation - 100f).coerceIn(-100f, 100f))
                    .build()
            )
        }

        if (filters.optDouble("invert", 0.0) >= 50.0) {
            out.add(RgbFilter.createInvertedFilter())
        }

        if (filters.optDouble("sepia", 0.0) > 0.0) {
            val sepiaMatrix = floatArrayOf(
                0.393f, 0.349f, 0.272f, 0f,
                0.769f, 0.686f, 0.534f, 0f,
                0.189f, 0.168f, 0.131f, 0f,
                0f, 0f, 0f, 1f
            )
            out.add(RgbMatrix { _, _ -> sepiaMatrix })
        }

        val tintR = filters.optDouble("tintRed", 0.0).toFloat() / 100f
        val tintG = filters.optDouble("tintGreen", 0.0).toFloat() / 100f
        val tintB = filters.optDouble("tintBlue", 0.0).toFloat() / 100f
        if (abs(tintR) > 1e-4f || abs(tintG) > 1e-4f || abs(tintB) > 1e-4f) {
            out.add(
                RgbAdjustment.Builder()
                    .setRedScale((1f + tintR).coerceIn(0f, 3f))
                    .setGreenScale((1f + tintG).coerceIn(0f, 3f))
                    .setBlueScale((1f + tintB).coerceIn(0f, 3f))
                    .build()
            )
        }

        val blurSigma = filters.optDouble("blur", 0.0).toFloat()
        if (blurSigma > 0.05f) {
            out.add(GaussianBlur(blurSigma.coerceIn(0.1f, 20f)))
        }

        return out
    }

    private fun runTransformerBlocking(
        ctx: Context,
        composition: Composition,
        outputPath: String,
        videoMimeType: String?,
        audioMimeType: String?,
        timeoutSeconds: Long
    ) {
        if (Looper.myLooper() == Looper.getMainLooper()) {
            throw IllegalStateException("Media3 export must be awaited from a background thread")
        }
        val mainHandler = Handler(Looper.getMainLooper())
        val latch = CountDownLatch(1)
        val errorRef = AtomicReference<Throwable?>(null)
        val transformerRef = AtomicReference<Transformer?>(null)

        mainHandler.post {
            try {
                val builder = Transformer.Builder(ctx)
                    .setLooper(Looper.getMainLooper())
                if (!videoMimeType.isNullOrBlank()) {
                    builder.setVideoMimeType(videoMimeType)
                }
                if (!audioMimeType.isNullOrBlank()) {
                    builder.setAudioMimeType(audioMimeType)
                }
                builder.addListener(object : Transformer.Listener {
                    override fun onCompleted(composition: Composition, exportResult: ExportResult) {
                        latch.countDown()
                    }

                    override fun onError(
                        composition: Composition,
                        exportResult: ExportResult,
                        exportException: ExportException
                    ) {
                        errorRef.set(exportException)
                        latch.countDown()
                    }
                })
                val transformer = builder.build()
                transformerRef.set(transformer)
                transformer.start(composition, outputPath)
            } catch (t: Throwable) {
                errorRef.set(t)
                latch.countDown()
            }
        }

        val finished = latch.await(timeoutSeconds, TimeUnit.SECONDS)
        if (!finished) {
            mainHandler.post {
                try {
                    transformerRef.get()?.cancel()
                } catch (_: Throwable) {
                }
            }
            throw RuntimeException("Media3 video export timed out after ${timeoutSeconds}s")
        }
        errorRef.get()?.let { err ->
            throw RuntimeException(err.message ?: "Media3 video export failed", err)
        }
    }

    private fun remuxAudioTrackToM4a(src: File, dest: File, maxSeconds: Double): Boolean {
        val extractor = MediaExtractor()
        var muxer: MediaMuxer? = null
        var muxerStarted = false
        try {
            extractor.setDataSource(src.absolutePath)
            var audioTrackIndex = -1
            var audioFormat: MediaFormat? = null
            for (i in 0 until extractor.trackCount) {
                val fmt = extractor.getTrackFormat(i)
                val mime = fmt.getString(MediaFormat.KEY_MIME).orEmpty()
                if (mime == MimeTypes.AUDIO_AAC || mime == "audio/mp4a-latm") {
                    audioTrackIndex = i
                    audioFormat = fmt
                    break
                }
            }
            if (audioTrackIndex < 0 || audioFormat == null) return false

            extractor.selectTrack(audioTrackIndex)
            muxer = MediaMuxer(dest.absolutePath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
            val dstTrack = muxer.addTrack(audioFormat)
            muxer.start()
            muxerStarted = true

            val maxUs = if (maxSeconds > 0.0) (maxSeconds * 1_000_000.0).roundToLong() else Long.MAX_VALUE
            val maxInput = if (audioFormat.containsKey(MediaFormat.KEY_MAX_INPUT_SIZE)) {
                max(65536, audioFormat.getInteger(MediaFormat.KEY_MAX_INPUT_SIZE))
            } else {
                262144
            }
            val buffer = ByteBuffer.allocate(maxInput)
            val info = MediaCodec.BufferInfo()
            while (true) {
                val sampleSize = extractor.readSampleData(buffer, 0)
                if (sampleSize < 0) break
                val sampleTimeUs = extractor.sampleTime
                if (sampleTimeUs > maxUs) break
                info.offset = 0
                info.size = sampleSize
                info.presentationTimeUs = max(0L, sampleTimeUs)
                info.flags = extractor.sampleFlags
                muxer.writeSampleData(dstTrack, buffer, info)
                extractor.advance()
            }
            return true
        } catch (_: Throwable) {
            return false
        } finally {
            if (muxer != null) {
                try {
                    if (muxerStarted) muxer.stop()
                } catch (_: Throwable) {
                }
                try {
                    muxer.release()
                } catch (_: Throwable) {
                }
            }
            try {
                extractor.release()
            } catch (_: Throwable) {
            }
        }
    }

    private fun probeTargetImageDimensions(firstImage: File): Pair<Int, Int> {
        val opts = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(firstImage.absolutePath, opts)
        var w = if (opts.outWidth > 0) opts.outWidth else 1280
        var h = if (opts.outHeight > 0) opts.outHeight else 720
        val maxDim = max(w, h)
        if (maxDim > 1920) {
            val scale = 1920.0 / maxDim.toDouble()
            w = max(2, (w * scale).roundToInt())
            h = max(2, (h * scale).roundToInt())
        }
        w = max(2, w - (w % 2))
        h = max(2, h - (h % 2))
        return w to h
    }

    private fun shortCodecName(mime: String): String {
        return when (mime.lowercase()) {
            MimeTypes.VIDEO_H264, "video/avc" -> "h264"
            MimeTypes.VIDEO_H265, "video/hevc" -> "hevc"
            MimeTypes.VIDEO_VP9, "video/x-vnd.on2.vp9" -> "vp9"
            MimeTypes.VIDEO_VP8, "video/x-vnd.on2.vp8" -> "vp8"
            MimeTypes.VIDEO_AV1, "video/av01" -> "av1"
            MimeTypes.VIDEO_MP4V, "video/mp4v-es" -> "mpeg4"
            else -> mime.substringAfter('/')
        }
    }
}
