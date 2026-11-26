package com.synthetictextextruder.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import com.chaquo.python.Python

class GenerationForegroundService : Service() {

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_CANCEL) {
            try {
                if (Python.isStarted()) {
                    Python.getInstance()
                        .getModule("synthetic_text_extruder.android_server")
                        .callAttr("cancel_active_jobs")
                }
            } catch (_: Throwable) {
                // Best-effort cancellation
            }
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
            return START_NOT_STICKY
        }

        ensureChannel()
        val message = intent?.getStringExtra(EXTRA_MESSAGE) ?: "Generating with Gemini…"
        startForeground(NOTIFICATION_ID, buildNotification(message))
        return START_NOT_STICKY
    }

    private fun ensureChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val nm = getSystemService(NotificationManager::class.java)
            val channel = NotificationChannel(
                CHANNEL_ID,
                "AI Generation Progress",
                NotificationManager.IMPORTANCE_LOW
            )
            nm.createNotificationChannel(channel)
        }
    }

    private fun buildNotification(message: String): Notification {
        val openIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val cancelIntent = PendingIntent.getService(
            this,
            1,
            Intent(this, GenerationForegroundService::class.java).apply {
                action = ACTION_CANCEL
            },
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle("Synthetic Text Extruder")
            .setContentText(message)
            .setOngoing(true)
            .setContentIntent(openIntent)
            .addAction(0, "Cancel", cancelIntent)
            .build()
    }

    companion object {
        private const val CHANNEL_ID = "ste_generation_jobs"
        private const val NOTIFICATION_ID = 1042
        private const val ACTION_CANCEL = "com.synthetictextextruder.app.CANCEL_JOBS"
        private const val EXTRA_MESSAGE = "message"

        fun start(context: Context, message: String) {
            val intent = Intent(context, GenerationForegroundService::class.java).apply {
                putExtra(EXTRA_MESSAGE, message)
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, GenerationForegroundService::class.java))
        }
    }
}
