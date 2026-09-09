package ai.loosh.tapfarm

import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject

data class Campaign(
    val id: String,
    val title: String,
    val taskType: String,
    val rewardPerTask: Int,
    val status: String,
    val description: String,
) {
    val isLive: Boolean get() = status == "live"
}

/** A task as served. The answer is never part of this - the server keeps it. */
data class Task(
    val taskId: String,
    val prompt: String,
    val grid: Int,
    val imageUrl: String,
)

data class Submission(
    val graded: Boolean,
    val correct: Boolean?,
    val reward: Int,
    val balance: Int,
    val uiBalance: Double,
    val accuracy: Double,
    val goldSamples: Int,
    val claimable: Boolean,
    val reason: String,
)

data class Contributor(
    val balance: Int,
    val uiBalance: Double,
    val uiReferralUnclaimed: Double,
    val uiTotalClaimable: Double,
    val solved: Int,
    val accuracy: Double,
    val goldSamples: Int,
    val claimable: Boolean,
    val reason: String,
)

data class Referral(
    val referrer: String?,
    val referees: Int,
    val uiEarned: Double,
    val uiUnclaimed: Double,
    val eligible: Boolean,
    val reason: String,
)

data class PreparedClaim(
    val transactionBase64: String,
    val uiAmount: Double,
    val cluster: String,
)

/** Raised for a 4xx the UI is expected to handle rather than show as a crash. */
class ApiException(val status: Int, message: String) : IOException(message)

/**
 * Backend client.
 *
 * OkHttp plus org.json (part of the Android framework, no dependency) instead of
 * Retrofit + a serialization plugin - the API is small and this keeps the build
 * simple.
 */
class TapFarmApi(private val baseUrl: String = BuildConfig.API_BASE) {

    private val http = OkHttpClient.Builder()
        .callTimeout(20, TimeUnit.SECONDS)
        .build()

    private val json = "application/json".toMediaType()

    /** Task images are served relative to the API root. */
    fun absoluteUrl(path: String): String =
        if (path.startsWith("http")) path else baseUrl + path

    suspend fun campaigns(): List<Campaign> = withContext(Dispatchers.IO) {
        val array = JSONArray(getRaw("/campaigns"))
        (0 until array.length()).map { i ->
            val o = array.getJSONObject(i)
            Campaign(
                id = o.getString("id"),
                title = o.getString("title"),
                taskType = o.getString("task_type"),
                rewardPerTask = o.getInt("reward_per_task"),
                status = o.getString("status"),
                description = o.getString("description"),
            )
        }
    }

    suspend fun nextTask(contributor: String): Task = withContext(Dispatchers.IO) {
        val o = get("/task/next?contributor=$contributor")
        Task(
            taskId = o.getString("task_id"),
            prompt = o.getString("prompt"),
            grid = o.getInt("grid"),
            imageUrl = absoluteUrl(o.getString("image_url")),
        )
    }

    suspend fun submit(
        contributor: String,
        taskId: String,
        cells: Set<Int>,
    ): Submission = withContext(Dispatchers.IO) {
        val payload = JSONObject()
            .put("contributor", contributor)
            .put("task_id", taskId)
            .put("cells", JSONArray(cells.sorted()))
        val o = post("/task/submit", payload)
        Submission(
            graded = o.getBoolean("graded"),
            correct = if (o.isNull("correct")) null else o.getBoolean("correct"),
            reward = o.getInt("reward"),
            balance = o.getInt("balance"),
            uiBalance = o.getDouble("ui_balance"),
            accuracy = o.getDouble("accuracy"),
            goldSamples = o.getInt("gold_samples"),
            claimable = o.getBoolean("claimable"),
            reason = o.getString("reason"),
        )
    }

    suspend fun contributor(contributor: String): Contributor = withContext(Dispatchers.IO) {
        val o = get("/contributor/$contributor")
        Contributor(
            balance = o.getInt("balance"),
            uiBalance = o.getDouble("ui_balance"),
            uiReferralUnclaimed = o.getDouble("ui_referral_unclaimed"),
            uiTotalClaimable = o.getDouble("ui_total_claimable"),
            solved = o.getInt("solved"),
            accuracy = o.getDouble("accuracy"),
            goldSamples = o.getInt("gold_samples"),
            claimable = o.getBoolean("claimable"),
            reason = o.getString("reason"),
        )
    }

    suspend fun referral(contributor: String): Referral = withContext(Dispatchers.IO) {
        val o = get("/referral/$contributor")
        Referral(
            referrer = if (o.isNull("referrer")) null else o.getString("referrer"),
            referees = o.getInt("referees"),
            uiEarned = o.getDouble("ui_earned"),
            uiUnclaimed = o.getDouble("ui_unclaimed"),
            eligible = o.getBoolean("eligible"),
            reason = o.getString("reason"),
        )
    }

    suspend fun prepareClaim(contributor: String): PreparedClaim = withContext(Dispatchers.IO) {
        val o = post("/claim/prepare", JSONObject().put("contributor", contributor))
        PreparedClaim(
            transactionBase64 = o.getString("transaction"),
            uiAmount = o.getDouble("ui_amount"),
            cluster = o.getString("cluster"),
        )
    }

    private fun get(path: String): JSONObject = JSONObject(getRaw(path))

    private fun getRaw(path: String): String =
        execute(Request.Builder().url(baseUrl + path).get().build())

    private fun post(path: String, payload: JSONObject): JSONObject =
        JSONObject(
            execute(
                Request.Builder()
                    .url(baseUrl + path)
                    .post(payload.toString().toRequestBody(json))
                    .build()
            )
        )

    private fun execute(request: Request): String {
        http.newCall(request).execute().use { response ->
            val text = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                // FastAPI puts the reason in "detail"; surface it rather than a
                // bare status code, since "not eligible yet" is a normal state
                // the UI needs to explain.
                val detail = runCatching { JSONObject(text).getString("detail") }
                    .getOrElse { text.ifBlank { "HTTP ${response.code}" } }
                throw ApiException(response.code, detail)
            }
            return text
        }
    }
}
