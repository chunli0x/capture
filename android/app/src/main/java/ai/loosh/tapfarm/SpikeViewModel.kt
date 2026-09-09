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

data class SpikeState(
    val wallet: String? = null,
    val uiEarned: Double = 0.0,
    val claimable: Boolean = false,
    val busy: String? = null,
    val lastSignature: String? = null,
    val error: String? = null,
) {
    val connected: Boolean get() = wallet != null
    val walletShort: String?
        get() = wallet?.let { "${it.take(4)}...${it.takeLast(4)}" }
}

/**
 * Drives the spike: connect a wallet, accrue a balance, claim it on devnet.
 *
 * The claim transaction is built and treasury-signed by the backend; this class
 * never touches Solana's transaction format. All it does is hand the returned
 * bytes to the wallet, which adds the contributor's signature as fee payer and
 * submits. Keeping transaction construction server-side means it can be unit
 * tested (see backend/tests/test_claim_tx.py) instead of only being verifiable
 * on a phone.
 */
class SpikeViewModel : ViewModel() {

    private val api = TapFarmApi()

    private val adapter = MobileWalletAdapter(
        connectionIdentity = ConnectionIdentity(
            identityUri = Uri.parse("https://tapfarm.loosh.ai"),
            iconRelativeUri = Uri.parse("favicon.ico"),
            identityName = "Tap Farm",
        )
    ).apply { blockchain = Solana.Devnet }

    private val _state = MutableStateFlow(SpikeState())
    val state: StateFlow<SpikeState> = _state.asStateFlow()

    fun connect(sender: ActivityResultSender) = launchGuarded("Connecting wallet") {
        when (val result = adapter.connect(sender)) {
            is TransactionResult.Success -> {
                val pubkey = Base58.encode(result.authResult.accounts.first().publicKey)
                _state.update { it.copy(wallet = pubkey) }
                refresh()
            }
            is TransactionResult.NoWalletFound ->
                fail("No MWA wallet found. Install a Solana wallet, or run on a Seeker.")
            is TransactionResult.Failure ->
                fail("Wallet connection failed: ${result.e.message ?: "unknown error"}")
        }
    }

    fun grantTestTasks(tasks: Int = 6) = launchGuarded("Crediting tasks") {
        val wallet = _state.value.wallet ?: return@launchGuarded fail("Connect a wallet first")
        api.grant(wallet, tasks)
        refresh()
    }

    fun claim(sender: ActivityResultSender) = launchGuarded("Preparing claim") {
        val wallet = _state.value.wallet ?: return@launchGuarded fail("Connect a wallet first")

        val prepared = api.prepareClaim(wallet)
        val txBytes = Base64.decode(prepared.transactionBase64, Base64.DEFAULT)

        _state.update { it.copy(busy = "Waiting for wallet approval") }

        // signAndSendTransactions, not signTransactions: the wallet both adds
        // the contributor's fee-payer signature and broadcasts, so there is no
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
                // A declined approval lands here too. The backend has already
                // zeroed the balance in the spike; see the note in main.py.
                fail("Claim not signed: ${result.e.message ?: "declined"}")
        }
    }

    fun dismissError() = _state.update { it.copy(error = null) }

    private suspend fun refresh() {
        val wallet = _state.value.wallet ?: return
        val balance = api.balance(wallet)
        _state.update {
            it.copy(uiEarned = balance.uiEarned, claimable = balance.claimable)
        }
    }

    private fun fail(message: String) = _state.update { it.copy(error = message) }

    private fun launchGuarded(label: String, block: suspend () -> Unit) {
        viewModelScope.launch {
            _state.update { it.copy(busy = label, error = null) }
            try {
                block()
            } catch (e: Exception) {
                fail(e.message ?: e::class.simpleName ?: "Unexpected error")
            } finally {
                _state.update { it.copy(busy = null) }
            }
        }
    }
}
