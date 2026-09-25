package ai.loosh.union

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
    val uiClipBalance: Double,
    val clipQualified: Boolean,
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

/** An object the ghost overlay can be drawn for. */
data class PoseObject(
    val objectId: String,
    val label: String,
    val rollFeature: String,
    val spriteUrl: String,
    /** Sprite edge length in image pixels at scale 1.0. */
    val spritePxAtScale1: Float,
    val canvas: Int,
)

/**
 * A served pose task.
 *
 * [truth] is non-null in practice only, where the client needs it for the snap
 * glow and the error delta. [allowSnap] is the server's word on whether any
 * proximity-dependent UI may render at all - during qualification it is false
 * and must stay false, or the blind gate is not blind.
 */
data class PoseTask(
    val taskId: String,
    val objectId: String,
    val imageUrl: String,
    val canvas: Int,
    val mode: String,
    val allowSnap: Boolean,
    val reward: Int,
    val truth: GhostPose?,
    val index: Int?,
    val of: Int?,
)

/** Image-plane pose: translation, in-plane rotation, and auxiliary scale. */
data class GhostPose(
    val x: Float,
    val y: Float,
    val roll: Float,
    val scale: Float = 1f,
)

data class PoseFeedback(
    val errorPx: Double,
    val errorDeg: Double,
    val withinTolerance: Boolean,
)

data class Qualification(
    val attempted: Int,
    val required: Int,
    val passedItems: Int,
    val qualified: Boolean,
    val meanErrorPx: Double,
    val meanErrorDeg: Double,
    val summary: String,
)

data class PoseResult(
    val mode: String,
    val reward: Int,
    val uiBalance: Double,
    val qualified: Boolean,
    val feedback: PoseFeedback?,
    val qualification: Qualification?,
)

data class PreparedClaim(
    val transactionBase64: String,
    val uiAmount: Double,
    val cluster: String,
)

/** Raised for a 4xx the UI is expected to handle rather than show as a crash. */
class ApiException(val status: Int, message: String) : IOException(message)

/** A served clip-judgment task. The answer is never part of this. */
data class ClipTask(
    val taskId: String,
    val mode: String,
    val clipUrl: String,
    val question: String,
    val choices: List<String>,
    /** False during qualification: blind means no escape hatch. */
    val canFlag: Boolean,
    val reward: Int,
    /** A stand-in clip. The UI refuses to present these as real footage. */
    val placeholder: Boolean,
)

data class ClipQualification(
    val graded: Int,
    val correct: Int,
    val required: Int,
    val accuracy: Double,
    val passed: Boolean,
    /** What a uniform guesser would have scored on this gate. */
    val chancePass: Double,
    val retryAvailable: Boolean,
    val retryReadyAt: Double?,
)

data class ClipResult(
    val mode: String,
    val reward: Int,
    val uiBalance: Double,
    val qualified: Boolean,
    val flagged: Boolean,
    /** Practice only. Null during a blind run and in paid work. */
    val correct: Boolean?,
    val expected: String?,
    val qualification: ClipQualification?,
)

/** A server-issued liveness challenge. Single use, short lived. */
data class LivenessSession(
    val sessionId: String,
    val challenge: String,
    val nonce: String,
    val ttlSeconds: Double,
)

data class LivenessProof(
    val proofHashHex: String,
    val taskId: String,
    val challenge: String,
    /** The server's own words for what this establishes. Shown, not paraphrased. */
    val attests: String,
)

/** The portable credential, as a buyer checks it. */
data class Attestation(
    val found: Boolean,
    val human: String?,
    val taskId: String?,
    val status: String?,
    val uiBondAmount: Double,
    val attestedAt: Long,
    val verifier: String?,
    val bondAccount: String?,
    val attestationAccount: String?,
    val cluster: String,
    val verifiedHuman: Boolean,
    val taskComplete: Boolean,
    val staked: Boolean,
    /** The server's own sentence. Rendered, never paraphrased. */
    val summary: String,
)

data class NetworkStats(
    /** A heartbeat, not a verified population. Named so it cannot be mistaken. */
    val onlineNowEstimate: Int,
    val actedToday: Int,
    val workProven: Int,
    val source: String,
)

data class LeaderRow(
    val rank: Int,
    val humanShort: String,
    val qualityScore: Double,
    val accuracy: Double,
    val workCount: Int,
    val uiBond: Double,
)

/**
 * Backend client.
 *
 * OkHttp plus org.json (part of the Android framework, no dependency) instead of
 * Retrofit + a serialization plugin - the API is small and this keeps the build
 * simple.
 */
class UnionApi(private val baseUrlProvider: () -> String = { BuildConfig.API_BASE }) {

    /** Read per request, so editing the address does not need a restart. */
    private val baseUrl: String get() = baseUrlProvider()

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
            uiClipBalance = o.optDouble("ui_clip_balance", 0.0),
            clipQualified = o.optBoolean("clip_qualified", false),
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

    suspend fun poseObjects(): List<PoseObject> = withContext(Dispatchers.IO) {
        val array = JSONArray(getRaw("/pose/objects"))
        (0 until array.length()).map { i ->
            val o = array.getJSONObject(i)
            PoseObject(
                objectId = o.getString("object_id"),
                label = o.getString("label"),
                rollFeature = o.getString("roll_feature"),
                spriteUrl = absoluteUrl(o.getString("sprite")),
                spritePxAtScale1 = o.getDouble("sprite_px_at_scale_1").toFloat(),
                canvas = o.getInt("canvas"),
            )
        }
    }

    suspend fun nextPoseTask(contributor: String, mode: String): PoseTask =
        withContext(Dispatchers.IO) {
            val o = get("/pose/task/next?contributor=$contributor&mode=$mode")
            PoseTask(
                taskId = o.getString("task_id"),
                objectId = o.getString("object_id"),
                imageUrl = absoluteUrl(o.getString("image_url")),
                canvas = o.getInt("canvas"),
                mode = o.getString("mode"),
                allowSnap = o.getBoolean("allow_snap"),
                reward = o.getInt("reward"),
                truth = if (o.isNull("truth")) null else o.getJSONObject("truth").let { t ->
                    GhostPose(
                        x = t.getDouble("x").toFloat(),
                        y = t.getDouble("y").toFloat(),
                        roll = t.getDouble("roll").toFloat(),
                        scale = t.optDouble("scale", 1.0).toFloat(),
                    )
                },
                index = if (o.isNull("index")) null else o.getInt("index"),
                of = if (o.isNull("of")) null else o.getInt("of"),
            )
        }

    suspend fun submitPose(
        contributor: String,
        taskId: String,
        pose: GhostPose,
    ): PoseResult = withContext(Dispatchers.IO) {
        val payload = JSONObject()
            .put("contributor", contributor)
            .put("task_id", taskId)
            .put(
                "pose",
                JSONObject()
                    .put("x", pose.x.toDouble())
                    .put("y", pose.y.toDouble())
                    .put("roll", pose.roll.toDouble())
                    .put("scale", pose.scale.toDouble()),
            )
        val o = post("/pose/submit", payload)
        PoseResult(
            mode = o.getString("mode"),
            reward = o.getInt("reward"),
            uiBalance = o.getDouble("ui_balance"),
            qualified = o.getBoolean("qualified"),
            feedback = if (o.isNull("feedback")) null else o.getJSONObject("feedback").let { f ->
                PoseFeedback(
                    errorPx = f.getDouble("error_px"),
                    errorDeg = f.getDouble("error_deg"),
                    withinTolerance = f.getBoolean("within_tolerance"),
                )
            },
            qualification = if (o.isNull("qualification")) null else
                o.getJSONObject("qualification").let { q ->
                    Qualification(
                        attempted = q.getInt("attempted"),
                        required = q.getInt("required"),
                        passedItems = q.getInt("passed_items"),
                        qualified = q.getBoolean("qualified"),
                        meanErrorPx = q.getDouble("mean_error_px"),
                        meanErrorDeg = q.getDouble("mean_error_deg"),
                        summary = q.getString("summary"),
                    )
                },
        )
    }

    suspend fun flagPoseTask(
        contributor: String,
        taskId: String,
        reason: String,
    ): Unit = withContext(Dispatchers.IO) {
        post(
            "/pose/flag",
            JSONObject()
                .put("contributor", contributor)
                .put("task_id", taskId)
                .put("reason", reason),
        )
    }

    suspend fun nextClipTask(contributor: String, mode: String): ClipTask =
        withContext(Dispatchers.IO) {
            val o = get("/clip/task/next?contributor=$contributor&mode=$mode")
            val choices = o.getJSONArray("choices")
            ClipTask(
                taskId = o.getString("task_id"),
                mode = o.getString("mode"),
                clipUrl = absoluteUrl(o.getString("clip_url")),
                question = o.getString("question"),
                choices = (0 until choices.length()).map { choices.getString(it) },
                canFlag = o.getBoolean("can_flag"),
                reward = o.getInt("reward"),
                placeholder = o.getBoolean("placeholder"),
            )
        }

    suspend fun submitClip(
        contributor: String,
        taskId: String,
        choice: String,
    ): ClipResult = withContext(Dispatchers.IO) {
        clipResult(
            post(
                "/clip/submit",
                JSONObject()
                    .put("contributor", contributor)
                    .put("task_id", taskId)
                    .put("choice", choice),
            )
        )
    }

    suspend fun flagClip(contributor: String, taskId: String): ClipResult =
        withContext(Dispatchers.IO) {
            clipResult(
                post(
                    "/clip/flag",
                    JSONObject()
                        .put("contributor", contributor)
                        .put("task_id", taskId)
                        .put("choice", ""),
                )
            )
        }

    suspend fun clipQualification(contributor: String): ClipQualification =
        withContext(Dispatchers.IO) {
            clipQualification(get("/clip/qualification/$contributor"))
        }

    suspend fun retryClipQualification(contributor: String): ClipQualification =
        withContext(Dispatchers.IO) {
            clipQualification(
                post(
                    "/clip/qualification/retry",
                    JSONObject().put("contributor", contributor),
                )
            )
        }

    suspend fun livenessSession(contributor: String, taskId: String): LivenessSession =
        withContext(Dispatchers.IO) {
            val o = post(
                "/liveness/session",
                JSONObject().put("contributor", contributor).put("task_id", taskId),
            )
            LivenessSession(
                sessionId = o.getString("session_id"),
                challenge = o.getString("challenge"),
                nonce = o.getString("nonce"),
                ttlSeconds = o.getDouble("ttl_seconds"),
            )
        }

    suspend fun completeLiveness(
        contributor: String,
        sessionId: String,
        resultDigestHex: String,
    ): LivenessProof = withContext(Dispatchers.IO) {
        val o = post(
            "/liveness/complete",
            JSONObject()
                .put("contributor", contributor)
                .put("session_id", sessionId)
                .put("result_digest", resultDigestHex),
        )
        LivenessProof(
            proofHashHex = o.getString("liveness_proof_hash"),
            taskId = o.getString("task_id"),
            challenge = o.getString("challenge"),
            attests = o.getString("attests"),
        )
    }

    suspend fun verify(human: String, taskId: String): Attestation =
        withContext(Dispatchers.IO) {
            val o = get("/verify/$human/$taskId")
            Attestation(
                found = o.getBoolean("found"),
                human = o.optString("human").ifBlank { null },
                taskId = o.optString("task_id").ifBlank { null },
                status = o.optString("status").ifBlank { null },
                uiBondAmount = o.optDouble("ui_bond_amount", 0.0),
                attestedAt = o.optLong("attested_at", 0L),
                verifier = o.optString("verifier").ifBlank { null },
                bondAccount = o.optString("bond_account").ifBlank { null },
                attestationAccount = o.optString("attestation_account").ifBlank { null },
                cluster = o.getString("cluster"),
                verifiedHuman = o.optBoolean("verified_human", false),
                taskComplete = o.optBoolean("task_complete", false),
                staked = o.optBoolean("staked", false),
                summary = o.getString("summary"),
            )
        }

    suspend fun networkStats(): NetworkStats = withContext(Dispatchers.IO) {
        val o = get("/network/stats")
        NetworkStats(
            onlineNowEstimate = o.getInt("online_now_estimate"),
            actedToday = o.getInt("acted_today"),
            workProven = o.getInt("work_proven"),
            source = o.getString("source"),
        )
    }

    suspend fun leaderboard(): List<LeaderRow> = withContext(Dispatchers.IO) {
        val rows = get("/network/leaderboard").getJSONArray("rows")
        (0 until rows.length()).map { i ->
            val o = rows.getJSONObject(i)
            LeaderRow(
                rank = o.getInt("rank"),
                humanShort = o.getString("human_short"),
                qualityScore = o.getDouble("quality_score"),
                accuracy = o.getDouble("accuracy"),
                workCount = o.getInt("work_count"),
                uiBond = o.getDouble("ui_bond"),
            )
        }
    }

    private fun clipResult(o: JSONObject) = ClipResult(
        mode = o.getString("mode"),
        reward = o.getInt("reward"),
        uiBalance = o.getDouble("ui_balance"),
        qualified = o.getBoolean("qualified"),
        flagged = o.getBoolean("flagged"),
        correct = if (o.isNull("correct")) null else o.getBoolean("correct"),
        expected = if (o.isNull("expected")) null else o.getString("expected"),
        qualification =
            if (o.isNull("qualification")) null
            else clipQualification(o.getJSONObject("qualification")),
    )

    private fun clipQualification(o: JSONObject) = ClipQualification(
        graded = o.getInt("graded"),
        correct = o.getInt("correct"),
        required = o.getInt("required"),
        accuracy = o.getDouble("accuracy"),
        passed = o.getBoolean("passed"),
        chancePass = o.getDouble("chance_pass"),
        retryAvailable = o.getBoolean("retry_available"),
        retryReadyAt =
            if (o.isNull("retry_ready_at")) null else o.getDouble("retry_ready_at"),
    )

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
