package starter.appcrash

import android.app.ActivityManager
import android.app.ApplicationExitInfo
import android.content.Context
import android.os.Build
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import java.io.File
import java.io.PrintWriter
import java.io.StringWriter

/**
 * Keeps the last crash on the phone (app-private storage, never sent automatically). On the next
 * launch the app offers the user to send it to the team (when crash upload is configured). Native crashes are caught by
 * the default uncaught-exception handler (then passed on, so Android still closes the app); fatal
 * JavaScript errors are written synchronously by the app before React Native closes it.
 */
class CrashModule : Module() {
  override fun definition() = ModuleDefinition {
    Name("AppCrash")

    OnCreate {
      appContext.reactContext?.applicationContext?.let { install(it) }
    }

    // Synchronous on purpose: a fatal JS error closes the app right after this returns.
    Function("recordJs") { text: String ->
      appContext.reactContext?.applicationContext?.let { write(it, "javascript", text) }
      true
    }

    // The saved report, or else what Android recorded about the last unexpected exit
    // (native crashes and freezes included), plus this app's own crash log lines.
    Function("read") {
      val context = appContext.reactContext?.applicationContext ?: return@Function ""
      val saved = file(context).takeIf { it.exists() }?.readText().orEmpty()
      if (saved.isNotEmpty()) return@Function saved + logTail()
      lastExit(context)
    }

    Function("clear") {
      appContext.reactContext?.applicationContext?.let { context ->
        file(context).delete()
        // Remember which system exit was handled so it is offered only once.
        lastExitTimestamp(context)?.let { prefs(context).edit().putLong("reported_exit", it).apply() }
      }
      true
    }
  }

  companion object {
    private const val MAX = 20_000
    @Volatile private var installed = false

    private fun file(context: Context) = File(context.filesDir, "app-last-crash.txt")
    private fun prefs(context: Context) = context.getSharedPreferences("app-crash", Context.MODE_PRIVATE)

    private fun crashExit(context: Context): ApplicationExitInfo? {
      if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return null
      return try {
        val manager = context.getSystemService(ActivityManager::class.java) ?: return null
        manager.getHistoricalProcessExitReasons(context.packageName, 0, 5).firstOrNull {
          it.reason == ApplicationExitInfo.REASON_CRASH || it.reason == ApplicationExitInfo.REASON_CRASH_NATIVE || it.reason == ApplicationExitInfo.REASON_ANR
        }
      } catch (_: Throwable) {
        null
      }
    }

    private fun lastExitTimestamp(context: Context): Long? =
      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) crashExit(context)?.timestamp else null

    /** Android's record of the last crash or freeze, when it has not been offered yet (Android 11+). */
    private fun lastExit(context: Context): String {
      if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return ""
      val exit = crashExit(context) ?: return ""
      if (exit.timestamp <= prefs(context).getLong("reported_exit", 0L)) return ""
      if (System.currentTimeMillis() - exit.timestamp > 3L * 24 * 60 * 60 * 1000) return ""
      val kind = when (exit.reason) {
        ApplicationExitInfo.REASON_CRASH_NATIVE -> "native-crash"
        ApplicationExitInfo.REASON_ANR -> "freeze"
        else -> "crash"
      }
      val trace = if (exit.reason == ApplicationExitInfo.REASON_ANR) {
        try {
          exit.traceInputStream?.bufferedReader()?.use { it.readText() }?.take(6000).orEmpty()
        } catch (_: Throwable) {
          ""
        }
      } else ""
      val header = "kind=$kind\nandroid=${Build.VERSION.RELEASE} (${Build.VERSION.SDK_INT})\ndevice=${Build.MANUFACTURER} ${Build.MODEL}\ntime=${exit.timestamp}\nstatus=${exit.status} importance=${exit.importance}\ndescription=${exit.description ?: ""}\n"
      return (header + trace + logTail()).take(MAX)
    }

    /** This app's own recent crash and error log lines (apps may read their own logs). */
    private fun logTail(): String = try {
      val process = Runtime.getRuntime().exec(arrayOf("logcat", "-d", "-b", "crash,main", "-v", "brief", "-t", "300", "*:E"))
      val text = process.inputStream.bufferedReader().use { it.readText() }
      process.destroy()
      if (text.isBlank()) "" else "\n--- log ---\n" + text.takeLast(8000)
    } catch (_: Throwable) {
      ""
    }

    fun write(context: Context, kind: String, details: String) {
      try {
        val header = "kind=$kind\nandroid=${Build.VERSION.RELEASE} (${Build.VERSION.SDK_INT})\ndevice=${Build.MANUFACTURER} ${Build.MODEL}\ntime=${System.currentTimeMillis()}\n\n"
        file(context).writeText((header + details).take(MAX))
      } catch (_: Throwable) {
        // Never make a crash worse.
      }
    }

    fun install(context: Context) {
      if (installed) return
      installed = true
      val previous = Thread.getDefaultUncaughtExceptionHandler()
      Thread.setDefaultUncaughtExceptionHandler { thread, error ->
        val trace = StringWriter().also { error.printStackTrace(PrintWriter(it)) }.toString()
        write(context, "native", "thread=${thread.name}\n$trace")
        previous?.uncaughtException(thread, error)
      }
    }
  }
}
