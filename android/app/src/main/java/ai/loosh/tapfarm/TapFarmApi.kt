package ai.loosh.tapfarm

import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject

/** A claim the backend has built and treasury-signed, ready for the wallet. */
data class PreparedClaim(
    val transactionBase64: String,
    val uiAmount: Double,
    val cluster: String,
)

data class Balance(val uiEarned: Double, val claimable: Boolean)

/**
 * Backend client.
 *
 * OkHttp plus org.json (part of the Android framework, no dependency) instead of
 * Retrofit + a serialization plugin - the spike has three endpoints and this
 * keeps the build simple.
 */
class TapFarmApi(private val baseUrl: String = BuildConfig.API_BASE) {

    private val http = OkHttpClient.Builder()
        .callTimeout(20, TimeUnit.SECONDS)
        .build()

    private val json = "application/json".toMediaType()

    suspend fun balance(contributor: String): Balance = withContext(Dispatchers.IO) {
        val body = get("/contributor/$contributor")
        Balance(
            uiEarned = body.getDouble("ui_earned"),
            claimable = body.getBoolean("claimable"),
        )
    }

    /** Spike-only: credit tasks without solving them. Replaced by task submit. */
    suspend fun grant(contributor: String, tasks: Int): Unit = withContext(Dispatchers.IO) {
        post(
            "/spike/grant",
            JSONObject().put("contributor", contributor).put("tasks", tasks),
        )
    }

    suspend fun prepareClaim(contributor: String): PreparedClaim = withContext(Dispatchers.IO) {
        val body = post("/claim/prepare", JSONObject().put("contributor", contributor))
        PreparedClaim(
            transactionBase64 = body.getString("transaction"),
            uiAmount = body.getDouble("ui_amount"),
            cluster = body.getString("cluster"),
        )
    }

    private fun get(path: String): JSONObject =
        execute(Request.Builder().url(baseUrl + path).get().build())

    private fun post(path: String, payload: JSONObject): JSONObject =
        execute(
            Request.Builder()
                .url(baseUrl + path)
                .post(payload.toString().toRequestBody(json))
                .build()
        )

    private fun execute(request: Request): JSONObject {
        http.newCall(request).execute().use { response ->
            val text = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                // FastAPI puts the reason in "detail"; surface it rather than a
                // bare status code, since "nothing to claim" is a normal state.
                val detail = runCatching { JSONObject(text).getString("detail") }
                    .getOrElse { text.ifBlank { "HTTP ${response.code}" } }
                throw IOException(detail)
            }
            return JSONObject(text)
        }
    }
}
