package ai.loosh.union.seeker

import ai.loosh.union.Base58
import ai.loosh.union.BuildConfig
import android.app.Application
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.media.MediaMetadataRetriever
import android.net.Uri
import android.util.Base64
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.solana.mobilewalletadapter.clientlib.*
import java.io.File
import java.util.UUID
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject

private fun JSONArray.objects() = (0 until length()).map { getJSONObject(it) }

/** The bounty kind governing a submission's media + label shape (`object|place|action`). */
private fun bountyKindOf(submission: JSONObject): String =
    if (submission.has("kind")) submission.getString("kind")
    else submission.optJSONObject("bounty")?.optString("kind", "object") ?: "object"

/** Serializes a [BountyDraft] to the create-bounty request body the server expects. */
private fun BountyDraft.toJson(): JSONObject {
    val ids = JSONArray()
    categoryIds.forEach { ids.put(it) }
    return JSONObject()
        .put("kind", kind)
        .put("title", title)
        .put("category_ids", ids)
        .put("reward_usdc_units", rewardUsdcUnits)
        .put("slots", slots)
        .put("deadline", deadline)
}

private class ApiFailure(val status: Int, message: String) : java.io.IOException(message)

/**
 * What [SeekerViewModel.recover] should do for a prepared transaction id.
 *
 * Kept as a pure, decision-only type (no Android, no network) so the branch
 * between replaying an exact confirm and falling back to a chain scan is unit
 * testable without a device or the wallet adapter.
 */
sealed class RecoveryAction {
    data class Confirm(val id: String, val signature: String) : RecoveryAction()
    data class Reconcile(val id: String) : RecoveryAction()

    companion object {
        /**
         * A persisted wallet signature lets recovery replay the exact confirm,
         * which works even when the bounty wallet has more than 100 transactions
         * and a chain-history scan would miss it. Without one, fall back to
         * [Reconcile], which scans recent chain history.
         */
        fun forTransaction(id: String, storedSignature: String?): RecoveryAction =
            if (storedSignature == null) Reconcile(id) else Confirm(id, storedSignature)
    }
}

/**
 * The phase of the most recent async call. Distinct from [PilotState.busy] so a
 * completed call can be told apart from idle: [Success] carries a transient
 * confirmation line for the snackbar, [Failure] pairs with [PilotState.error].
 */
sealed class AsyncStatus {
    object Idle : AsyncStatus()
    object Working : AsyncStatus()
    object Success : AsyncStatus()
    object Failure : AsyncStatus()
}

data class PilotState(
    val server: String = "",
    val wallet: String = "",
    val worker: Boolean = false,
    val reviewer: Boolean = false,
    val busy: Boolean = false,
    val message: String = "",
    val error: String? = null,
    val status: AsyncStatus = AsyncStatus.Idle,
    val transient: String? = null,
    val bounties: List<JSONObject> = emptyList(),
    val submissions: List<JSONObject> = emptyList(),
    val reviews: List<JSONObject> = emptyList(),
    val transactions: List<JSONObject> = emptyList(),
    val selected: JSONObject? = null,
    val image: Bitmap? = null,
    val videoDurationMs: Int? = null,
    val videoUri: Uri? = null,
    val taxonomy: List<TaxonomyCategory> = emptyList(),
    val reviewing: Boolean = false,
    val bond: Long = 0,
    val pendingUsdc: Long = 0,
    // --- Capture v2: leveling ---
    val level: Int = 0,
    val levelName: String = "Scout",
    val acceptedCount: Int = 0,
    val acceptanceRate: Double = 0.0,
    val rateMultiplier: Double = 1.0,
    val bondMultiplier: Double = 2.0,
    // --- Capture v2: liveness gate ---
    val livenessChallenge: String? = null,
    val livenessVerified: Boolean = false,
    // --- Capture v2: judge verdict + payout ---
    val lastResult: SubmissionResult? = null,
    // --- Capture v2: bond gate + free quality-check path ---
    val bonded: Boolean = false,
    val qualityChecks: Int = 0,
    val qualityChecksRequired: Int = 0,
    val unlocked: Boolean = true,
    val bondFunded: Boolean = false,
    val reviewQueue: List<JSONObject> = emptyList(),
    // --- Judgment product (RLHF preference judging) ---
    val judgeCalibrated: Boolean = false,
    val judgeAgreementRate: Double = 0.0,
    val judgeJudgedCount: Int = 0,
    val judgeLevel: Int = 0,
    val judgeLevelName: String = "Scout",
    val judgeRateMultiplier: Double = 1.0,
    val judgeStakedSkr: Long = 0,
    val judgeWarnings: Int = 0,
    val calibrationCompleted: Int = 0,
    val calibrationRequired: Int = 10,
    val calibrationCorrect: Int = 0,
    val judgePair: JSONObject? = null,
)

class SeekerViewModel(application: Application) : AndroidViewModel(application) {
    private val prefs = application.getSharedPreferences("seeker.api", 0)

    // A wallet-returned transaction signature, persisted by prepared transaction
    // id so a process kill between sign and confirm can still be recovered.
    private fun signatureKey(id: String) = "sig.$id"

    private fun storeSignature(id: String, signature: String) {
        prefs.edit().putString(signatureKey(id), signature).apply()
    }

    private fun storedSignature(id: String): String? = prefs.getString(signatureKey(id), null)

    private fun clearSignature(id: String) {
        prefs.edit().remove(signatureKey(id)).apply()
    }
    private val mutable =
        MutableStateFlow(
            PilotState(server = prefs.getString("server", null) ?: BuildConfig.SEEKER_API_BASE)
        )
    val state = mutable.asStateFlow()
    private var token: String? = null
    private var draftInput: List<Any>? = null
    private var draftBody: JSONObject? = null
    private var draftKey: String? = null
    private var livenessSessionId: String? = null
    private val http =
        OkHttpClient.Builder()
            .followRedirects(false)
            .followSslRedirects(false)
            .callTimeout(75, TimeUnit.SECONDS)
            .build()
    private val adapter =
        MobileWalletAdapter(
                connectionIdentity =
                    ConnectionIdentity(
                        identityUri = Uri.parse("https://capture.magnumopus.ai"),
                        iconUri = Uri.parse("favicon.ico"),
                        identityName = "Capture",
                    )
            )
            .apply { blockchain = Solana.Devnet }

    private fun run(label: String, success: String? = null, block: suspend () -> Unit) {
        if (mutable.value.busy) return
        mutable.update {
            it.copy(busy = true, error = null, message = label, status = AsyncStatus.Working, transient = null)
        }
        viewModelScope.launch {
            try {
                block()
                mutable.update {
                    it.copy(message = "", status = AsyncStatus.Success, transient = success)
                }
            } catch (e: Exception) {
                if (e is kotlinx.coroutines.CancellationException) throw e
                if (e is ApiFailure && e.status == 401) clearSession()
                mutable.update {
                    it.copy(error = e.message ?: "Request failed", status = AsyncStatus.Failure)
                }
            } finally {
                mutable.update { it.copy(busy = false) }
            }
        }
    }

    /** Clears the success phase + transient message once the snackbar times out. */
    fun dismissTransient() {
        if (!mutable.value.busy)
            mutable.update { it.copy(status = AsyncStatus.Idle, transient = null) }
    }

    /** Dismisses the error card; also resets the Failure phase back to Idle. */
    fun dismissError() {
        if (!mutable.value.busy)
            mutable.update {
                it.copy(
                    error = null,
                    status = if (it.status == AsyncStatus.Failure) AsyncStatus.Idle else it.status,
                )
            }
    }

    /** Whether the first-run onboarding pager has been completed (persisted). */
    fun onboarded(): Boolean = prefs.getBoolean("onboarded", false)

    fun setOnboarded() {
        prefs.edit().putBoolean("onboarded", true).apply()
    }

    /** Whether the first-run ground-level capture tutorial has been completed (persisted). */
    fun tutorialDone(): Boolean = prefs.getBoolean("tutorial_done", false)

    fun setTutorialDone() {
        prefs.edit().putBoolean("tutorial_done", true).apply()
    }

    private fun clearSession() {
        token = null
        adapter.authToken = null
        draftInput = null
        draftBody = null
        draftKey = null
        livenessSessionId = null
        mutable.value = PilotState(server = mutable.value.server, busy = mutable.value.busy)
    }

    fun server(value: String) {
        if (mutable.value.busy) return
        val url = value.trim().trimEnd('/')
        val uri = Uri.parse(url)
        if (
            uri.host.isNullOrBlank() ||
                !(uri.scheme == "https" || BuildConfig.DEBUG && uri.scheme == "http") ||
                uri.userInfo != null
        ) {
            mutable.update {
                it.copy(error = "Enter an HTTPS server address (HTTP is allowed only in debug).")
            }
            return
        }
        token = null
        adapter.authToken = null
        draftInput = null
        draftBody = null
        draftKey = null
        prefs.edit().putString("server", url).apply()
        mutable.value = PilotState(server = url)
    }

    private suspend fun bytes(
        path: String,
        json: JSONObject? = null,
        raw: ByteArray? = null,
        requestKey: String? = null,
    ): ByteArray =
        withContext(Dispatchers.IO) {
            val url = mutable.value.server
            require(BuildConfig.DEBUG || url.startsWith("https://")) {
                "Release builds require HTTPS."
            }
            val builder = Request.Builder().url(url + path)
            token?.let { builder.header("Authorization", "Bearer $it") }
            requestKey?.let { builder.header("Idempotency-Key", it) }
            if (json != null)
                builder.post(json.toString().toRequestBody("application/json".toMediaType()))
            if (raw != null)
                builder.post(raw.toRequestBody("application/octet-stream".toMediaType()))
            http.newCall(builder.build()).execute().use { response ->
                val data = response.body?.bytes() ?: error("Empty server response")
                if (!response.isSuccessful) {
                    val detail = runCatching {
                        JSONObject(String(data)).optString("detail")
                    }
                        .getOrDefault("Request failed")
                    throw ApiFailure(response.code, "${response.code}: $detail")
                }
                data
            }
        }

    private suspend fun get(path: String) = JSONObject(String(bytes(path)))

    private suspend fun post(
        path: String,
        data: JSONObject = JSONObject(),
        requestKey: String? = null,
    ) = JSONObject(String(bytes(path, data, requestKey = requestKey)))

    private suspend fun list(path: String) = JSONArray(String(bytes(path))).objects()

    fun connect(sender: ActivityResultSender, over18: Boolean) =
        run("Connecting to your wallet…", "Wallet connected") {
            val connection = adapter.connect(sender)
            check(connection is TransactionResult.Success) { "Wallet connection was not approved." }
            val wallet = Base58.encode(connection.authResult.accounts.first().publicKey)
            val challenge = post("/auth/challenge", JSONObject().put("wallet", wallet))
            val signed =
                adapter.transact(sender) { auth ->
                    check(Base58.encode(auth.accounts.first().publicKey) == wallet) {
                        "Wallet changed; sign in again."
                    }
                    signMessagesDetached(
                        arrayOf(challenge.getString("message").toByteArray(Charsets.UTF_8)),
                        arrayOf(auth.accounts.first().publicKey),
                    )
                }
            check(signed is TransactionResult.Success) { "Sign-in was not approved." }
            val signature =
                signed.successPayload?.messages?.first()?.signatures?.first()
                    ?: error("Wallet returned no signature")
            val verify =
                buildVerifyRequest(
                    challengeId = challenge.getString("challenge_id"),
                    signature = Base58.encode(signature),
                    over18 = over18,
                )
            val session =
                post(
                    "/auth/verify",
                    JSONObject()
                        .put("challenge_id", verify.challengeId)
                        .put("signature", verify.signature)
                        .put("over_18", verify.over18),
                )
            token = session.getString("token")
            mutable.update { it.copy(wallet = wallet) }
            refreshData()
        }

    fun logout() =
        run("Signing out", "Signed out") {
            try {
                post("/auth/logout")
            } finally {
                clearSession()
            }
        }

    private suspend fun refreshData() {
        val me = get("/me")
        val b = list("/bounties")
        val s = list("/submissions")
        val r = if (me.getBoolean("reviewer")) list("/review-queue") else emptyList()
        val tx = list("/transactions")
        val taxonomy = parseTaxonomy(get("/taxonomy"))
        val parsedLevel = me.optInt("level", 0).coerceIn(0, MAX_LEVEL)
        val bonded = me.optBoolean("bonded", false)
        val qualityChecks = me.optInt("quality_checks", 0)
        val qualityChecksRequired = me.optInt("quality_checks_required", 0)
        // The backend owns `unlocked`; when it is absent (legacy server) derive it
        // so a bond-capable backend never leaves a user gated by surprise.
        val unlocked =
            if (me.has("unlocked")) me.getBoolean("unlocked")
            else (bonded || qualityChecksRequired <= 0 || qualityChecks >= qualityChecksRequired)
        mutable.update {
            it.copy(
                worker = me.getBoolean("worker"),
                reviewer = me.getBoolean("reviewer"),
                bond = me.getLong("bond_test_skr_units"),
                pendingUsdc = me.optLong("pending_usdc", 0),
                bounties = b,
                submissions = s,
                reviews = r,
                transactions = tx,
                taxonomy = taxonomy,
                level = parsedLevel,
                levelName = me.optString("level_name", levelName(parsedLevel)),
                acceptedCount = me.optInt("accepted_count", 0),
                acceptanceRate = me.optDouble("acceptance_rate", 0.0),
                rateMultiplier = me.optDouble("rate_multiplier", levelTier(parsedLevel).rateMultiplier),
                bondMultiplier = me.optDouble("bond_multiplier", levelTier(parsedLevel).bondMultiplier),
                bonded = bonded,
                qualityChecks = qualityChecks,
                qualityChecksRequired = qualityChecksRequired,
                unlocked = unlocked,
            )
        }
    }

    /** Parses the `GET /taxonomy` registry into per-kind categories for the creation picker. */
    private fun parseTaxonomy(data: JSONObject): List<TaxonomyCategory> {
        val categories = data.optJSONArray("categories") ?: return emptyList()
        return (0 until categories.length()).map { i ->
            val c = categories.getJSONObject(i)
            val rawId: Any = if (c.has("id")) c.get("id") else 0
            val (id, slug) =
                when (rawId) {
                    is Int -> rawId to null
                    is String -> (rawId.toIntOrNull() ?: 0) to rawId
                    else -> 0 to null
                }
            TaxonomyCategory(
                id = id,
                name = c.getString("name"),
                kind = c.optString("kind", KIND_OBJECT),
                group = c.optString("group").takeIf { it.isNotBlank() },
                slug = slug,
            )
        }
    }

    fun refresh() = run("Refreshing", "Bounties refreshed") { refreshData() }

    // --- Capture v2: bond gate + free quality-check path ---

    /** Devnet test-SKR faucet — "Get test SKR". Idempotent; records funding server-side. */
    fun faucet() =
        run("Requesting test SKR", "Test SKR funded") {
            post("/bond/faucet")
            mutable.update { it.copy(bondFunded = true) }
        }

    /**
     * Devnet bond deposit. POST /bond/deposit returns the prepared on-chain
     * escrow transaction (self-serve enrollment — no prior worker flag needed),
     * which the wallet signs + sends, then /transactions/{id}/confirm marks the
     * account bonded. Mirrors [transact] but hits /bond/deposit directly.
     */
    fun depositBond(sender: ActivityResultSender) =
        run("Depositing bond", "Bond deposited") {
            val prepared = post("/bond/deposit")
            val tx = Base64.decode(prepared.getString("transaction_base64"), Base64.DEFAULT)
            val result =
                adapter.transact(sender) { auth ->
                    check(Base58.encode(auth.accounts.first().publicKey) == mutable.value.wallet) {
                        "Wallet changed; sign in again."
                    }
                    signAndSendTransactions(arrayOf(tx))
                }
            check(result is TransactionResult.Success) {
                "Wallet did not send the transaction. Refresh to recover if it was sent."
            }
            val sig =
                result.successPayload?.signatures?.first()
                    ?: error("Wallet returned no signature; use Recover.")
            val id = prepared.getString("id")
            val signature = Base58.encode(sig)
            storeSignature(id, signature)
            try {
                confirm(id, signature)
                clearSignature(id)
            } catch (e: Exception) {
                // Leave the signature persisted so recover() can replay the confirm.
                throw e
            }
            refreshData()
        }

    /** Settles accrued earnings: POST /bond/settle drains pending_usdc to the wallet. */
    fun settle() =
        run("Settling earnings", "Earnings settled") {
            post("/bond/settle")
            refreshData()
        }

    /** Lists open uploads awaiting peer review (the token-saving path). */
    fun loadReviewQueue() =
        run("Loading review queue", "Review queue loaded") {
            mutable.update { it.copy(reviewQueue = list("/review-queue")) }
        }

    /** Records an accept/reject review for an open submission, then refreshes state + queue. */
    fun submitReview(sid: String, accept: Boolean) =
        run("Submitting review", "Review recorded") {
            post("/submissions/$sid/reviews", JSONObject().put("accepted", accept))
            refreshData()
            mutable.update { it.copy(reviewQueue = list("/review-queue")) }
        }

    // --- Judgment product (RLHF preference judging) ---

    /** Fetches the next calibration/judgment pair plus the judge's stats. */
    fun judgeNext() = run("Loading next pair", "Pair loaded") { refreshJudgment() }

    /** Submits a preference choice (a/b/tie/cant_tell) or a 1-5 rating. */
    fun submitJudgment(choice: String? = null, rating: Int? = null) =
        run("Submitting judgment", "Judgment recorded") {
            val pair = mutable.value.judgePair ?: error("No pair to judge")
            val id = pair.getString("pair_id")
            val body = JSONObject()
            if (choice != null) body.put("choice", choice)
            else body.put("rating", rating ?: error("A rating is required"))
            post("/judge/$id", body)
            refreshJudgment()
        }

    private suspend fun refreshJudgment() {
        val next = get("/judge/next")
        val stats = get("/judge/stats")
        val level = stats.optInt("level", 0).coerceIn(0, MAX_JUDGE_LEVEL)
        val progress = stats.optJSONObject("calibration_progress")
        val pair = if (next.optString("kind", "none") == "none") null else next
        mutable.update {
            it.copy(
                judgePair = pair,
                judgeCalibrated = stats.optBoolean("calibrated", false),
                judgeAgreementRate = stats.optDouble("agreement_rate", 0.0),
                judgeJudgedCount = stats.optInt("judged_count", 0),
                judgeLevel = level,
                judgeLevelName = stats.optString("level_name", judgeLevelName(level)),
                judgeRateMultiplier = stats.optDouble("rate_multiplier", judgeRateMultiplier(level)),
                judgeStakedSkr = stats.optLong("staked_skr", 0),
                judgeWarnings = stats.optInt("warnings", 0),
                calibrationCompleted = progress?.optInt("completed", 0) ?: 0,
                calibrationRequired = progress?.optInt("required", 10) ?: 10,
                calibrationCorrect = progress?.optInt("correct", 0) ?: 0,
            )
        }
    }

    // --- Capture v2: liveness gate (once per session, before first upload) ---

    fun startLiveness() =
        run("Starting liveness check") {
            require(mutable.value.wallet.isNotEmpty()) { "Sign in first." }
            val session =
                post(
                    "/liveness/session",
                    JSONObject().put("contributor", mutable.value.wallet).put("task_id", "capture-session"),
                )
            livenessSessionId = session.getString("session_id")
            mutable.update {
                it.copy(livenessChallenge = session.getString("challenge"), livenessVerified = false)
            }
        }

    fun completeLiveness(resultDigestHex: String) =
        run("Verifying") {
            val sid = livenessSessionId ?: error("No liveness session in progress.")
            post(
                "/liveness/complete",
                JSONObject()
                    .put("contributor", mutable.value.wallet)
                    .put("session_id", sid)
                    .put("result_digest", resultDigestHex),
            )
            livenessSessionId = null
            mutable.update { it.copy(livenessVerified = true, livenessChallenge = null) }
        }

    fun cancelLiveness() {
        if (!mutable.value.busy) {
            livenessSessionId = null
            mutable.update { it.copy(livenessChallenge = null) }
        }
    }

    // --- Capture v2: instant open upload (no bounty wait) ---

    fun startOpenCapture(kind: String) =
        run("Opening a capture", "Ready to capture") {
            val created = post("/submissions", JSONObject().put("kind", kind))
            val id = created.getString("id")
            val categories =
                categoriesForKind(mutable.value.taxonomy, kind).map { c ->
                    JSONObject()
                        .put("id", c.id)
                        .put("name", c.name)
                        .put("kind", c.kind)
                        .also { obj -> c.slug?.let { obj.put("slug", it) } }
                }
            val selected =
                JSONObject()
                    .put("id", id)
                    .put("worker", mutable.value.wallet)
                    .put("status", "claimed")
                    .put(
                        "bounty",
                        JSONObject()
                            .put("kind", kind)
                            .put("title", openCaptureTitle(kind))
                            .put("categories", JSONArray(categories)),
                    )
            mutable.update {
                it.copy(
                    selected = selected,
                    image = null,
                    videoDurationMs = null,
                    videoUri = null,
                    reviewing = false,
                    lastResult = null,
                )
            }
        }

    fun dismissVerdict() {
        if (!mutable.value.busy)
            mutable.update { it.copy(lastResult = null) }
    }

    private fun openCaptureTitle(kind: String): String =
        when (kind) {
            KIND_PLACE -> "Place capture"
            KIND_ACTION -> "Action capture"
            else -> "Object capture"
        }

    fun close() {
        if (!mutable.value.busy)
            mutable.update {
                it.copy(selected = null, image = null, videoDurationMs = null, videoUri = null)
            }
    }

    fun create(
        title: String,
        categoryIds: List<Int>,
        reward: String,
        slots: String,
        hours: String,
        kind: String = KIND_OBJECT,
    ) = run("Creating bounty draft", "Bounty draft saved") {
            val amount = reward.toBigDecimal().movePointRight(6).longValueExact()
            val duration = hours.toLong()
            require(duration in 1..720) { "Choose 1–720 hours." }
            require(categoryIds.isNotEmpty()) { "Choose at least one category." }
            val draft =
                buildBountyDraft(
                    kind = kind,
                    title = title,
                    categoryIds = categoryIds,
                    rewardUsdcUnits = amount,
                    slots = slots.toInt(),
                    deadline = System.currentTimeMillis() / 1000 + duration * 3600,
                )
            val input = listOf(title, categoryIds, reward, slots, hours, kind)
            val fresh = draft.toJson()
            if (draftInput != input) {
                draftInput = input
                draftBody = fresh
                draftKey = UUID.randomUUID().toString()
            }
            val data = draftBody ?: error("Missing draft")
            val hash = draftKey ?: error("Missing draft key")
            post("/bounties", data, hash)
            refreshData()
        }

    fun claim(bid: String) =
        run("Reserving a capture slot", "Slot claimed") {
            val s = post("/bounties/$bid/claim")
            mutable.update {
                it.copy(selected = s, image = null, videoDurationMs = null, videoUri = null, reviewing = false)
            }
            loadApprovedMedia(s)
            refreshData()
        }

    fun open(s: JSONObject, review: Boolean) =
        run("Opening approved media", "Opened") {
            mutable.update {
                it.copy(selected = s, image = null, videoDurationMs = null, videoUri = null, reviewing = review)
            }
            loadApprovedMedia(s)
        }

    /** Loads the approved image or video backing a submission, keyed by bounty kind. */
    private suspend fun loadApprovedMedia(s: JSONObject) {
        if (s.isNull("media_hash")) return
        if (bountyKindOf(s) == "action") loadVideo(s.getString("id")) else loadImage(s.getString("id"))
    }

    private suspend fun loadImage(id: String) {
        val data = bytes("/submissions/$id/media")
        val image =
            withContext(Dispatchers.Default) {
                BitmapFactory.decodeByteArray(data, 0, data.size)
                    ?: error("Image cannot be decoded")
            }
        mutable.update { it.copy(image = image, videoUri = null) }
    }

    private suspend fun loadVideo(id: String) {
        val data = bytes("/submissions/$id/media")
        val file = File(getApplication<Application>().cacheDir, "seeker-video-$id.mp4")
        withContext(Dispatchers.IO) { file.writeBytes(data) }
        val durationMs =
            withContext(Dispatchers.IO) {
                runCatching { probeDurationMs(file) }.getOrDefault(0)
            }
        mutable.update {
            it.copy(
                videoUri = Uri.fromFile(file),
                image = null,
                videoDurationMs = if (durationMs > 0) durationMs else it.videoDurationMs,
            )
        }
    }

    /** Authoritative clip duration in integer ms, read from the media container itself. */
    private fun probeDurationMs(file: File): Int {
        val retriever = MediaMetadataRetriever()
        return try {
            retriever.setDataSource(file.absolutePath)
            retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)?.toIntOrNull() ?: 0
        } finally {
            retriever.release()
        }
    }

    fun capture(claimId: String, data: ByteArray, videoDurationMs: Int? = null) =
        run("Uploading capture…", "Capture uploaded") {
            val s = mutable.value.selected ?: error("Select a claim first")
            val id = s.getString("id")
            require(id == claimId) { "Capture belongs to another claim; open it again." }
            val result = JSONObject(String(bytes("/submissions/$id/media", raw = data)))
            s.put("media_hash", result.getString("media_hash"))
            if (videoDurationMs == null) {
                loadImage(id)
            } else {
                mutable.update { it.copy(image = null, videoDurationMs = videoDurationMs) }
                loadVideo(id)
            }
            refreshData()
        }

    private fun mediaHash(): String =
        mutable.value.selected?.getString("media_hash")
            ?: error("No approved media to label")

    /** Appends the three optional secondary arrays, omitting any that are empty, plus the v2 metadata fields. */
    private fun JSONObject.withSecondary(secondary: SecondarySelection): JSONObject =
        apply {
            secondaryLabelFields(
                    secondary.expressions,
                    secondary.postures,
                    secondary.environment,
                )
                .forEach { (key, ids) ->
                    put(key, JSONArray().apply { ids.forEach { put(it) } })
                }
            captureMetadataFields(secondary).forEach { (key, value) -> put(key, value) }
        }

    private fun submitLabels(payload: JSONObject) =
        run("Submitting labels…", "Labels submitted") {
            val s = mutable.value.selected ?: error("No selected capture")
            val action = if (mutable.value.reviewing) "reviews" else "labels"
            val result = post("/submissions/${s.getString("id")}/$action", payload)
            val outcome = parseSubmissionResult(result)
            mutable.update {
                it.copy(
                    selected = null,
                    image = null,
                    videoDurationMs = null,
                    videoUri = null,
                    lastResult = outcome,
                    level = outcome.levelAfter ?: it.level,
                    levelName = outcome.levelAfter?.let(::levelName) ?: it.levelName,
                )
            }
            refreshData()
        }

    /**
     * Maps a submit response to [SubmissionResult]. Absent or malformed verdict
     * fields fall back safely: no `accepted` key means "no verdict yet", never
     * a fabricated rejection.
     */
    private fun parseSubmissionResult(result: JSONObject): SubmissionResult {
        val verdict = result.optJSONObject("verdict")
        val accepted =
            if (verdict != null && verdict.has("accepted")) verdict.optBoolean("accepted") else null
        val reason = verdict?.optString("reason").orEmpty()
        val payoutUsdc = result.optInt("payout_usdc", 0)
        val levelAfter =
            if (result.has("level_after")) result.optInt("level_after", -1).takeIf { it >= 0 } else null
        val status = result.optString("status", "")
        return buildSubmissionResult(accepted, reason, payoutUsdc, levelAfter, status)
    }

    /** Posture is the one required secondary dimension in v2; refuse to mint a label without it. */
    private fun requirePosture(secondary: SecondarySelection) {
        require(secondary.postures.isNotEmpty()) { "Choose a posture (required)." }
    }

    fun submit(boxes: List<LabelBox>, secondary: SecondarySelection): Unit =
        requirePosture(secondary).let {
            submitLabels(
                JSONObject()
                    .put("media_hash", mediaHash())
                    .put(
                        "boxes",
                        JSONArray().apply {
                            boxes.forEach {
                                put(
                                    JSONObject()
                                        .put("category_id", it.categoryId)
                                        .put("x", it.x.toDouble())
                                        .put("y", it.y.toDouble())
                                        .put("w", it.w.toDouble())
                                        .put("h", it.h.toDouble())
                                )
                            }
                        },
                    )
                    .withSecondary(secondary)
            )
        }

    fun submitPlace(categoryId: Int, secondary: SecondarySelection): Unit =
        requirePosture(secondary).let {
            submitLabels(
                JSONObject()
                    .put("media_hash", mediaHash())
                    .put("scene", JSONObject().put("category_id", categoryId))
                    .withSecondary(secondary)
            )
        }

    fun submitAction(categoryId: Int, trim: TrimRange, secondary: SecondarySelection): Unit =
        requirePosture(secondary).let {
            submitLabels(
                JSONObject()
                    .put("media_hash", mediaHash())
                    .put(
                        "action",
                        JSONObject()
                            .put("category_id", categoryId)
                            .put("start_ms", trim.startMs)
                            .put("end_ms", trim.endMs),
                    )
                    .withSecondary(secondary)
            )
        }

    fun transact(path: String, sender: ActivityResultSender) =
        run("Review this transaction in your wallet", "Transaction confirmed") {
            val prepared = post("$path/prepare")
            val tx = Base64.decode(prepared.getString("transaction_base64"), Base64.DEFAULT)
            val result =
                adapter.transact(sender) { auth ->
                    check(Base58.encode(auth.accounts.first().publicKey) == mutable.value.wallet) {
                        "Wallet changed; sign in again."
                    }
                    signAndSendTransactions(arrayOf(tx))
                }
            check(result is TransactionResult.Success) {
                "Wallet did not send the transaction. Refresh to recover if it was sent."
            }
            val sig =
                result.successPayload?.signatures?.first()
                    ?: error("Wallet returned no signature; use Recover.")
            val id = prepared.getString("id")
            val signature = Base58.encode(sig)
            // Persist before confirming so a kill between sign and confirm does
            // not lose the signature for good.
            storeSignature(id, signature)
            try {
                confirm(id, signature)
                clearSignature(id)
            } catch (e: Exception) {
                // Leave the signature persisted so recover() can replay the confirm.
                throw e
            }
            refreshData()
        }

    private suspend fun confirm(id: String, signature: String) {
        var confirmed = false
        repeat(10) {
            if (!confirmed) {
                try {
                    post(
                        "/transactions/$id/confirm",
                        JSONObject().put("signature", signature),
                    )
                    confirmed = true
                } catch (e: Exception) {
                    if (e !is ApiFailure || e.status != 503 || it == 9) throw e
                    delay(1500)
                }
            }
        }
    }

    fun recover(id: String) =
        run("Checking finalized chain history", "Transaction recovered") {
            when (val action = RecoveryAction.forTransaction(id, storedSignature(id))) {
                is RecoveryAction.Confirm -> {
                    confirm(action.id, action.signature)
                    clearSignature(action.id)
                }
                is RecoveryAction.Reconcile -> post("/transactions/${action.id}/reconcile")
            }
            refreshData()
        }
}
