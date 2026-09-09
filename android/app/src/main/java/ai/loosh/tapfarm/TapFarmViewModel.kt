package ai.loosh.tapfarm

import android.net.Uri
import android.util.Base64
import androidx.lifecycle.ViewModel
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

enum class Screen { CONNECT, CAMPAIGNS, SOLVING }

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
    val busy: String? = null,
    val error: String? = null,
    val lastSignature: String? = null,
) {
    val walletShort: String?
        get() = wallet?.let { "${it.take(4)}…${it.takeLast(4)}" }
    val canSubmit: Boolean
        get() = task != null && feedback == null && busy == null
}

class TapFarmViewModel : ViewModel() {

    private val api = TapFarmApi()

    private val adapter = MobileWalletAdapter(
        connectionIdentity = ConnectionIdentity(
            identityUri = Uri.parse("https://tapfarm.loosh.ai"),
            iconUri = Uri.parse("favicon.ico"),
            identityName = "Tap Farm",
        )
    ).apply { blockchain = Solana.Devnet }

    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state.asStateFlow()

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
