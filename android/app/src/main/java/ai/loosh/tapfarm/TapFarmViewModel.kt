package ai.loosh.tapfarm

import android.app.Application
import android.net.Uri
import android.util.Base64
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.solana.mobilewalletadapter.clientlib.ActivityResultSender
import com.solana.mobilewalletadapter.clientlib.ConnectionIdentity
import com.solana.mobilewalletadapter.clientlib.MobileWalletAdapter
import com.solana.mobilewalletadapter.clientlib.Solana
import com.solana.mobilewalletadapter.clientlib.TransactionResult
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

enum class Screen { CONNECT, CAMPAIGNS, SOLVING, POSE_PRIMER, POSE_TASK, CLIP_PRIMER, CLIP_TASK, LIVENESS }

/** Ghost-overlay modes, matching the server's pools. */
/** Modes are the wire values the backend expects; do not localise them. */
object ClipMode {
    const val PRACTICE = "practice"
    const val QUALIFY = "qualify"
    const val EARN = "earn"
}

object PoseMode {
    const val PRACTICE = "practice"
    const val QUALIFY = "qualify"
    const val EARN = "earn"
}

/**
 * Result of the last submission.
 *
 * Showing honestly whether a task was verified looks like it leaks which tasks
 * are gold, and it does - but only *after* the answer is in. Gold is chosen at
 * random per serving, a task is served to a contributor once, and resubmission
 * is refused, so knowing after the fact has no predictive value for the next
 * task. Hiding it would cost real feedback for no security gain.
 */
data class Feedback(
    val verified: Boolean,
    val correct: Boolean?,
    val reward: Int,
) {
    val headline: String
        get() = when {
            !verified -> "Recorded"
            correct == true -> "Verified"
            else -> "Incorrect"
        }
}

data class UiState(
    val screen: Screen = Screen.CONNECT,
    val wallet: String? = null,
    val campaigns: List<Campaign> = emptyList(),
    val task: Task? = null,
    val selected: Set<Int> = emptySet(),
    val feedback: Feedback? = null,
    val solved: Int = 0,
    val uiBalance: Double = 0.0,
    val accuracy: Double = 0.0,
    val goldSamples: Int = 0,
    val claimable: Boolean = false,
    val eligibilityReason: String = "",
    val referral: Referral? = null,
    val uiReferralUnclaimed: Double = 0.0,
    val uiTotalClaimable: Double = 0.0,
    // --- ghost overlay ---
    val poseObjects: Map<String, PoseObject> = emptyMap(),
    val poseTask: PoseTask? = null,
    val pose: GhostPose = GhostPose(0f, 0f, 0f, 1f),
    val poseMode: String = PoseMode.PRACTICE,
    val poseFeedback: PoseFeedback? = null,
    val poseSubmitted: Boolean = false,
    val qualification: Qualification? = null,
    val poseQualified: Boolean = false,
    val practiceDone: Int = 0,
    // --- clip judgment ---
    val clipTask: ClipTask? = null,
    val clipMode: String = ClipMode.PRACTICE,
    val clipResult: ClipResult? = null,
    val clipQualification: ClipQualification? = null,
    val clipQualified: Boolean = false,
    val uiClipBalance: Double = 0.0,
    // --- liveness ---
    val livenessSession: LivenessSession? = null,
    val livenessProof: LivenessProof? = null,
    val busy: String? = null,
    val error: String? = null,
    val lastSignature: String? = null,
    val serverUrl: String = "",
    val serverReachable: Boolean = false,
) {
    val walletShort: String?
        get() = wallet?.let { "${it.take(4)}…${it.takeLast(4)}" }
    val canSubmit: Boolean
        get() = task != null && feedback == null && busy == null

    val poseObject: PoseObject?
        get() = poseTask?.let { poseObjects[it.objectId] }

    val canSubmitPose: Boolean
        get() = poseTask != null && !poseSubmitted && busy == null
}

class TapFarmViewModel(application: Application) : AndroidViewModel(application) {

    private val config = ApiConfig(application)
    private val api = TapFarmApi { config.baseUrl }

    private val adapter = MobileWalletAdapter(
        connectionIdentity = ConnectionIdentity(
            identityUri = Uri.parse("https://tapfarm.loosh.ai"),
            iconUri = Uri.parse("favicon.ico"),
            identityName = "Tap",
        )
    ).apply { blockchain = Solana.Devnet }

    private val _state = MutableStateFlow(UiState(serverUrl = config.baseUrl))
    val state: StateFlow<UiState> = _state.asStateFlow()

    /** Point the app at a different backend. Takes effect on the next request. */
    fun setServerUrl(url: String) {
        config.baseUrl = url
        _state.update { it.copy(serverUrl = config.baseUrl, error = null) }
    }

    /** Check the address before asking someone to trust it with a wallet. */
    fun testServer() = launchGuarded("Checking server") {
        val campaigns = api.campaigns()
        _state.update {
            it.copy(
                campaigns = campaigns,
                error = null,
                busy = null,
            )
        }
        _state.update { it.copy(serverReachable = true) }
    }

    fun connect(sender: ActivityResultSender) = launchGuarded("Connecting wallet") {
        when (val result = adapter.connect(sender)) {
            is TransactionResult.Success -> {
                val pubkey = Base58.encode(result.authResult.accounts.first().publicKey)
                _state.update { it.copy(wallet = pubkey, screen = Screen.CAMPAIGNS) }
                _state.update { it.copy(campaigns = api.campaigns()) }
                refresh()
            }
            is TransactionResult.NoWalletFound ->
                fail("No MWA wallet found. Install a Solana wallet, or run on a Seeker.")
            is TransactionResult.Failure ->
                fail("Wallet connection failed: ${result.message}")
        }
    }

    fun openCampaign(campaign: Campaign) {
        if (!campaign.isLive) {
            fail("${campaign.title} is not open yet.")
            return
        }
        // Task type, not campaign id: a second ghost-overlay campaign should
        // route itself without another branch here.
        if (campaign.taskType == "ghost_pose") {
            openGhostCampaign()
            return
        }
        if (campaign.taskType == "clip_judgment") {
            openClipCampaign()
            return
        }
        _state.update { it.copy(screen = Screen.SOLVING) }
        loadNextTask()
    }

    fun backToCampaigns() {
        _state.update {
            it.copy(screen = Screen.CAMPAIGNS, task = null, selected = emptySet(), feedback = null)
        }
    }

    fun toggleCell(cell: Int) {
        if (_state.value.feedback != null) return  // already submitted
        _state.update {
            val next = it.selected.toMutableSet()
            if (!next.add(cell)) next.remove(cell)
            it.copy(selected = next)
        }
    }

    fun loadNextTask() = launchGuarded("Loading task") {
        val wallet = requireWallet() ?: return@launchGuarded
        _state.update { it.copy(feedback = null, selected = emptySet(), task = null) }
        _state.update { it.copy(task = api.nextTask(wallet)) }
    }

    fun submit() = launchGuarded("Submitting") {
        val wallet = requireWallet() ?: return@launchGuarded
        val task = _state.value.task ?: return@launchGuarded

        val result = api.submit(wallet, task.taskId, _state.value.selected)
        _state.update {
            it.copy(
                feedback = Feedback(
                    verified = result.graded,
                    correct = result.correct,
                    reward = result.reward,
                ),
                solved = it.solved + 1,
                uiBalance = result.uiBalance,
                accuracy = result.accuracy,
                goldSamples = result.goldSamples,
                claimable = result.claimable,
                eligibilityReason = result.reason,
            )
        }
    }

    fun claim(sender: ActivityResultSender) = launchGuarded("Preparing claim") {
        val wallet = requireWallet() ?: return@launchGuarded

        val prepared = api.prepareClaim(wallet)
        val txBytes = Base64.decode(prepared.transactionBase64, Base64.DEFAULT)

        _state.update { it.copy(busy = "Waiting for wallet approval") }

        // signAndSendTransactions, not signTransactions: the wallet adds the
        // contributor's fee-payer signature and broadcasts, so there is no
        // second round trip and nothing for us to submit.
        val result = adapter.transact(sender) {
            signAndSendTransactions(arrayOf(txBytes))
        }

        when (result) {
            is TransactionResult.Success -> {
                val signature = Base58.encode(result.payload.signatures.first())
                _state.update { it.copy(lastSignature = signature) }
                refresh()
            }
            is TransactionResult.NoWalletFound ->
                fail("Wallet disappeared mid-claim. Reconnect and try again.")
            is TransactionResult.Failure ->
                fail("Claim not signed: ${result.message}")
        }
    }

    // ---- ghost overlay -----------------------------------------------------

    fun openGhostCampaign() = launchGuarded("Loading campaign") {
        val objects = api.poseObjects().associateBy { it.objectId }
        _state.update { it.copy(poseObjects = objects, screen = Screen.POSE_PRIMER) }
    }

    fun startPose(mode: String) {
        _state.update { it.copy(poseMode = mode, screen = Screen.POSE_TASK) }
        nextPoseTask()
    }

    fun nextPoseTask() = launchGuarded("Loading task") {
        val wallet = requireWallet() ?: return@launchGuarded
        val mode = _state.value.poseMode
        _state.update {
            it.copy(poseTask = null, poseFeedback = null, poseSubmitted = false)
        }
        val task = api.nextPoseTask(wallet, mode)
        _state.update { it.copy(poseTask = task, pose = startingPose(task)) }
    }

    fun updatePose(pose: GhostPose) {
        if (_state.value.poseSubmitted) return
        val canvas = _state.value.poseTask?.canvas ?: return
        // Clamped on the way in, so the ghost can never be dragged somewhere
        // the labeler cannot reach it again.
        _state.update { it.copy(pose = clampToCanvas(pose, canvas)) }
    }

    /** Bring the ghost back to its starting position. */
    fun recentreGhost() {
        val task = _state.value.poseTask ?: return
        if (_state.value.poseSubmitted) return
        _state.update { it.copy(pose = startingPose(task)) }
    }

    /**
     * Discard a task the labeler cannot honestly answer.
     *
     * A forced guess on an unclear or empty frame is a confident wrong label,
     * which is worse for the dataset than no label. The server refuses this
     * during the blind run, and surfaces why.
     */
    fun flagTask(reason: String) = launchGuarded("Skipping") {
        val wallet = requireWallet() ?: return@launchGuarded
        val task = _state.value.poseTask ?: return@launchGuarded
        api.flagPoseTask(wallet, task.taskId, reason)
        nextPoseTask()
    }

    fun submitPose() = launchGuarded("Submitting") {
        val wallet = requireWallet() ?: return@launchGuarded
        val task = _state.value.poseTask ?: return@launchGuarded

        val result = api.submitPose(wallet, task.taskId, _state.value.pose)
        _state.update {
            it.copy(
                poseSubmitted = true,
                poseFeedback = result.feedback,
                qualification = result.qualification ?: it.qualification,
                poseQualified = result.qualified,
                practiceDone =
                    if (task.mode == PoseMode.PRACTICE) it.practiceDone + 1 else it.practiceDone,
                uiBalance = result.uiBalance,
            )
        }
        if (result.qualification != null) refresh()
    }

    fun leavePose() {
        _state.update {
            it.copy(screen = Screen.CAMPAIGNS, poseTask = null, poseFeedback = null)
        }
    }

    /**
     * Where the ghost starts.
     *
     * Deliberately a fixed corner offset rather than anywhere near the answer.
     * Seeding it close to the true pose would hand over part of the label - and
     * during qualification the client does not know the answer anyway.
     */
    private fun startingPose(task: PoseTask): GhostPose =
        GhostPose(x = task.canvas * 0.26f, y = task.canvas * 0.26f, roll = 0f, scale = 1f)

    // --- clip judgment -----------------------------------------------------

    fun openClipCampaign() {
        _state.update { it.copy(screen = Screen.CLIP_PRIMER, error = null) }
    }

    fun startClip(mode: String) {
        _state.update {
            it.copy(clipMode = mode, clipResult = null, clipTask = null)
        }
        nextClipTask()
    }

    fun nextClipTask() = launchGuarded("Loading clip") {
        val wallet = requireWallet() ?: return@launchGuarded
        val task = api.nextClipTask(wallet, _state.value.clipMode)
        _state.update {
            it.copy(screen = Screen.CLIP_TASK, clipTask = task, clipResult = null)
        }
    }

    fun answerClip(choice: String) = launchGuarded("Submitting") {
        val wallet = requireWallet() ?: return@launchGuarded
        val task = _state.value.clipTask ?: return@launchGuarded
        val result = api.submitClip(wallet, task.taskId, choice)
        _state.update {
            it.copy(
                clipResult = result,
                clipQualified = result.qualified,
                clipQualification = result.qualification ?: it.clipQualification,
                uiClipBalance = result.uiBalance,
            )
        }
        refresh()
    }

    fun flagClip() = launchGuarded("Flagging") {
        val wallet = requireWallet() ?: return@launchGuarded
        val task = _state.value.clipTask ?: return@launchGuarded
        val result = api.flagClip(wallet, task.taskId)
        _state.update { it.copy(clipResult = result) }
    }

    fun retryClipQualification() = launchGuarded("Resetting qualification") {
        val wallet = requireWallet() ?: return@launchGuarded
        val qualification = api.retryClipQualification(wallet)
        _state.update {
            it.copy(clipQualification = qualification, clipResult = null)
        }
    }

    fun leaveClip() {
        _state.update {
            it.copy(screen = Screen.CAMPAIGNS, clipTask = null, clipResult = null)
        }
    }

    // --- liveness ----------------------------------------------------------

    /**
     * Ask the server for a challenge, then show the camera.
     *
     * The session is requested here rather than on the camera screen so a
     * server error surfaces before the permission prompt: being asked for the
     * camera and then told the backend is unreachable is a worse first
     * impression than the reverse.
     */
    fun startLiveness(taskId: String) = launchGuarded("Starting liveness check") {
        val wallet = requireWallet() ?: return@launchGuarded
        val session = api.livenessSession(wallet, taskId)
        _state.update {
            it.copy(
                screen = Screen.LIVENESS,
                livenessSession = session,
                livenessProof = null,
            )
        }
    }

    fun completeLiveness(resultDigestHex: String) = launchGuarded("Checking") {
        val wallet = requireWallet() ?: return@launchGuarded
        val session = _state.value.livenessSession ?: return@launchGuarded
        val proof = api.completeLiveness(wallet, session.sessionId, resultDigestHex)
        _state.update {
            it.copy(
                livenessProof = proof,
                livenessSession = null,
                screen = Screen.CLIP_PRIMER,
            )
        }
    }

    fun cancelLiveness() {
        _state.update {
            it.copy(screen = Screen.CLIP_PRIMER, livenessSession = null)
        }
    }

    fun dismissError() = _state.update { it.copy(error = null) }

    private suspend fun refresh() {
        val wallet = _state.value.wallet ?: return
        val summary = api.contributor(wallet)
        val referral = runCatching { api.referral(wallet) }.getOrNull()
        _state.update {
            it.copy(
                solved = summary.solved,
                uiBalance = summary.uiBalance,
                uiReferralUnclaimed = summary.uiReferralUnclaimed,
                uiTotalClaimable = summary.uiTotalClaimable,
                accuracy = summary.accuracy,
                goldSamples = summary.goldSamples,
                claimable = summary.claimable,
                eligibilityReason = summary.reason,
                referral = referral ?: it.referral,
                uiClipBalance = summary.uiClipBalance,
                clipQualified = summary.clipQualified,
            )
        }
    }

    private fun requireWallet(): String? {
        val wallet = _state.value.wallet
        if (wallet == null) fail("Connect a wallet first")
        return wallet
    }

    private fun fail(message: String) = _state.update { it.copy(error = message) }

    private fun launchGuarded(label: String, block: suspend () -> Unit) {
        viewModelScope.launch {
            _state.update { it.copy(busy = label, error = null) }
            try {
                block()
            } catch (e: ApiException) {
                fail(e.message ?: "Request failed")
            } catch (e: Exception) {
                fail(e.message ?: e::class.simpleName ?: "Unexpected error")
            } finally {
                _state.update { it.copy(busy = null) }
            }
        }
    }
}
