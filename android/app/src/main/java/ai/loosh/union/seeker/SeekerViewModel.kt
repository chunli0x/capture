package ai.loosh.union.seeker

import ai.loosh.union.Base58
import ai.loosh.union.BuildConfig
import android.app.Application
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.util.Base64
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.solana.mobilewalletadapter.clientlib.*
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
    submission.optJSONObject("bounty")?.optString("kind", "object") ?: "object"

/** Serializes a [BountyDraft] to the create-bounty request body the server expects. */
private fun BountyDraft.toJson(): JSONObject {
    val cats = JSONArray()
    categories.forEach { c ->
        cats.put(JSONObject().put("id", c.id).put("name", c.name).put("kind", c.kind))
    }
    return JSONObject()
        .put("kind", kind)
        .put("title", title)
        .put("categories", cats)
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

data class PilotState(
    val server: String = "",
    val wallet: String = "",
    val worker: Boolean = false,
    val reviewer: Boolean = false,
    val busy: Boolean = false,
    val message: String = "",
    val error: String? = null,
    val bounties: List<JSONObject> = emptyList(),
    val submissions: List<JSONObject> = emptyList(),
    val reviews: List<JSONObject> = emptyList(),
    val transactions: List<JSONObject> = emptyList(),
    val selected: JSONObject? = null,
    val image: Bitmap? = null,
    val videoDurationMs: Int? = null,
    val reviewing: Boolean = false,
    val bond: Long = 0,
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
    private var draftInput: List<String>? = null
    private var draftBody: JSONObject? = null
    private var draftKey: String? = null
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
                        identityUri = Uri.parse("https://union.loosh.ai"),
                        iconUri = Uri.parse("favicon.ico"),
                        identityName = "Seeker test pilot",
                    )
            )
            .apply { blockchain = Solana.Devnet }

    private fun run(label: String, block: suspend () -> Unit) {
        if (mutable.value.busy) return
        mutable.update { it.copy(busy = true, error = null, message = label) }
        viewModelScope.launch {
            try {
                block()
                mutable.update { it.copy(message = "Ready") }
            } catch (e: Exception) {
                if (e is kotlinx.coroutines.CancellationException) throw e
                if (e is ApiFailure && e.status == 401) clearSession()
                mutable.update { it.copy(error = e.message ?: "Request failed") }
            } finally {
                mutable.update { it.copy(busy = false) }
            }
        }
    }

    private fun clearSession() {
        token = null
        adapter.authToken = null
        draftInput = null
        draftBody = null
        draftKey = null
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

    fun connect(sender: ActivityResultSender) =
        run("Sign in with your devnet wallet") {
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
            val session =
                post(
                    "/auth/verify",
                    JSONObject()
                        .put("challenge_id", challenge.getString("challenge_id"))
                        .put("signature", Base58.encode(signature)),
                )
            token = session.getString("token")
            mutable.update { it.copy(wallet = wallet) }
            refreshData()
        }

    fun logout() =
        run("Signing out") {
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
        mutable.update {
            it.copy(
                worker = me.getBoolean("worker"),
                reviewer = me.getBoolean("reviewer"),
                bond = me.getLong("bond_test_skr_units"),
                bounties = b,
                submissions = s,
                reviews = r,
                transactions = tx,
            )
        }
    }

    fun refresh() = run("Refreshing") { refreshData() }

    fun close() {
        if (!mutable.value.busy)
            mutable.update { it.copy(selected = null, image = null, videoDurationMs = null) }
    }

    fun create(
        title: String,
        categories: String,
        reward: String,
        slots: String,
        hours: String,
        kind: String = KIND_OBJECT,
    ) = run("Creating bounty draft") {
            val amount = reward.toBigDecimal().movePointRight(6).longValueExact()
            val duration = hours.toLong()
            require(duration in 1..720) { "Choose 1–720 hours." }
            val draft =
                buildBountyDraft(
                    kind = kind,
                    title = title,
                    categories = categories,
                    rewardUsdcUnits = amount,
                    slots = slots.toInt(),
                    deadline = System.currentTimeMillis() / 1000 + duration * 3600,
                )
            val input = listOf(title, categories, reward, slots, hours, kind)
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
        run("Reserving a capture slot") {
            val s = post("/bounties/$bid/claim")
            mutable.update {
                it.copy(selected = s, image = null, videoDurationMs = null, reviewing = false)
            }
            if (!s.isNull("media_hash") && bountyKindOf(s) != "action") loadImage(s.getString("id"))
            refreshData()
        }

    fun open(s: JSONObject, review: Boolean) =
        run("Opening approved image") {
            mutable.update {
                it.copy(selected = s, image = null, videoDurationMs = null, reviewing = review)
            }
            if (!s.isNull("media_hash") && bountyKindOf(s) != "action") loadImage(s.getString("id"))
        }

    private suspend fun loadImage(id: String) {
        val data = bytes("/submissions/$id/media")
        val image =
            withContext(Dispatchers.Default) {
                BitmapFactory.decodeByteArray(data, 0, data.size)
                    ?: error("Image cannot be decoded")
            }
        mutable.update { it.copy(image = image) }
    }

    fun capture(claimId: String, data: ByteArray, videoDurationMs: Int? = null) =
        run("Checking your capture before upload approval") {
            val s = mutable.value.selected ?: error("Select a claim first")
            val id = s.getString("id")
            require(id == claimId) { "Capture belongs to another claim; open it again." }
            val result = JSONObject(String(bytes("/submissions/$id/media", raw = data)))
            s.put("media_hash", result.getString("media_hash"))
            if (videoDurationMs == null) {
                loadImage(id)
            } else {
                mutable.update { it.copy(image = null, videoDurationMs = videoDurationMs) }
            }
            refreshData()
        }

    private fun mediaHash(): String =
        mutable.value.selected?.getString("media_hash")
            ?: error("No approved media to label")

    private fun submitLabels(payload: JSONObject) =
        run("Submitting manual labels") {
            val s = mutable.value.selected ?: error("No selected capture")
            val action = if (mutable.value.reviewing) "reviews" else "labels"
            post("/submissions/${s.getString("id")}/$action", payload)
            mutable.update { it.copy(selected = null, image = null, videoDurationMs = null) }
            refreshData()
        }

    fun submit(boxes: List<LabelBox>) =
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
        )

    fun submitPlace(categoryId: Int) =
        submitLabels(
            JSONObject()
                .put("media_hash", mediaHash())
                .put("scene", JSONObject().put("category_id", categoryId))
        )

    fun submitAction(categoryId: Int, trim: TrimRange) =
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
        )

    fun transact(path: String, sender: ActivityResultSender) =
        run("Review this test-token transaction in your wallet") {
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
        run("Checking finalized chain history") {
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
