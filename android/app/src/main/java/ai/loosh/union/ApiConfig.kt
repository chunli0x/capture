package ai.loosh.union

import android.content.Context
import android.content.SharedPreferences

/**
 * Where the backend lives, editable on the device.
 *
 * This used to be fixed at build time, which meant anyone wanting to try the
 * app needed the whole Android toolchain just to bake in their own laptop's
 * address. A backend running on a phone's own network is the normal case for
 * this demo, so the address belongs in the app rather than in the build.
 *
 * The compiled-in value is still the default, so a build made with
 * `-PunionApiBase=...` behaves exactly as before until someone edits it.
 */
class ApiConfig(context: Context) {

    private val prefs: SharedPreferences =
        context.applicationContext.getSharedPreferences("tap.api", Context.MODE_PRIVATE)

    var baseUrl: String
        get() = prefs.getString(KEY_BASE_URL, null)?.takeIf { it.isNotBlank() }
            ?: BuildConfig.API_BASE
        set(value) {
            prefs.edit().putString(KEY_BASE_URL, normalise(value)).apply()
        }

    /** True once someone has set an address by hand. */
    val isCustom: Boolean
        get() = prefs.getString(KEY_BASE_URL, null)?.isNotBlank() == true

    fun reset() {
        prefs.edit().remove(KEY_BASE_URL).apply()
    }

    companion object {
        private const val KEY_BASE_URL = "base_url"

        /**
         * Tidy up what someone typed.
         *
         * People type `192.168.1.20:8000` far more often than a full URL, and a
         * trailing slash doubles up with the paths the client appends - both
         * produce a connection error that looks like the server is down.
         */
        fun normalise(input: String): String {
            val trimmed = input.trim().trimEnd('/')
            if (trimmed.isEmpty()) return trimmed
            return if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) {
                trimmed
            } else {
                "http://$trimmed"
            }
        }
    }
}
