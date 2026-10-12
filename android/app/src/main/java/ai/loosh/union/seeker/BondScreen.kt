package ai.loosh.union.seeker

import ai.loosh.union.CaptureAccent
import ai.loosh.union.CaptureAccentBright
import ai.loosh.union.CaptureAccentBorder
import ai.loosh.union.CaptureAccentTint
import ai.loosh.union.CaptureInk
import ai.loosh.union.CaptureOutline
import ai.loosh.union.MutedGray
import ai.loosh.union.SuccessGreen
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.solana.mobilewalletadapter.clientlib.ActivityResultSender

/**
 * The hard gate before a first upload: deposit the minimum TEST-SKR bond, a
 * real on-chain escrow. Rendered whenever `/me` reports `unlocked == false`.
 */
@Composable
fun BondScreen(
    s: PilotState,
    vm: SeekerViewModel,
    sender: ActivityResultSender,
    onReviewQueue: () -> Unit,
) {
    NavyBackground(Modifier.fillMaxSize().captureScreenMotion()) {
        Column(
            Modifier
                .fillMaxSize()
                .safeDrawingPadding()
                .verticalScroll(rememberScrollState())
                .padding(20.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            CaptureWordmark()
            Text("Unlock Capture", style = MaterialTheme.typography.displaySmall)
            Text(
                "Submitting content requires posting a \$SKR Bond. On devnet, deposit the minimum TEST-SKR bond. It is a real " +
                    "on-chain escrow — the tokens are transferred out of your wallet and can be " +
                    "slashed for invalid submissions.",
                style = MaterialTheme.typography.bodyMedium,
                color = MutedGray,
                textAlign = TextAlign.Center,
            )
            CapturePanel(Modifier.fillMaxWidth()) {
                PolicyRow(CaptureSymbol.PERSON, "You must be 18 or older.")
                PolicyRow(CaptureSymbol.CAMERA, "No faces, nudity or illegal content.")
            }
            if (s.unlocked) UnlockedBanner()
            BondCard(s, vm, sender)
            QualityCheckCard(s, vm, onReviewQueue)
        }
    }
}

@Composable
private fun PolicyRow(symbol: CaptureSymbol, text: String) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        CaptureIcon(symbol, Modifier.size(20.dp), CaptureInk)
        Text(text, style = MaterialTheme.typography.bodyMedium, color = CaptureInk)
    }
}

@Composable
private fun UnlockedBanner() {
    androidx.compose.material3.Card(
        Modifier.fillMaxWidth(),
        border = BorderStroke(1.dp, CaptureAccentBorder),
        colors = CardDefaults.cardColors(containerColor = CaptureAccentTint),
    ) {
        Row(
            Modifier.padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            CaptureIcon(CaptureSymbol.VERIFIED, Modifier.size(20.dp), SuccessGreen)
            Text("Unlocked — you can capture now", style = MaterialTheme.typography.titleSmall, color = CaptureInk)
        }
    }
}

@Composable
private fun BondCard(s: PilotState, vm: SeekerViewModel, sender: ActivityResultSender) {
    CapturePanel(Modifier.fillMaxWidth(), elevated = true) {
        Text("DEPOSIT THE MINIMUM TEST-SKR BOND", style = MaterialTheme.typography.labelMedium, color = CaptureAccentBright)
        Text(
            "The minimum TEST-SKR bond is a real on-chain escrow. Your tokens are transferred " +
                "into the contract and can be slashed for invalid work; withdraw what remains later.",
            style = MaterialTheme.typography.bodySmall,
            color = MutedGray,
        )
        when {
            s.bonded -> DoneRow("Bond deposited — instant judging is on.")
            s.bondFunded -> {
                DoneRow("Test SKR funded.")
                Button(onClick = { vm.depositBond(sender) }, enabled = !s.busy, modifier = Modifier.fillMaxWidth()) {
                    Text("Deposit bond")
                }
            }
            else -> {
                Button(onClick = { vm.faucet() }, enabled = !s.busy, modifier = Modifier.fillMaxWidth()) {
                    Text("Get test SKR")
                }
                Text(
                    "Fund test SKR first, then deposit the bond.",
                    style = MaterialTheme.typography.labelSmall,
                    color = MutedGray,
                )
            }
        }
    }
}

@Composable
private fun QualityCheckCard(s: PilotState, vm: SeekerViewModel, onReviewQueue: () -> Unit) {
    val required = s.qualityChecksRequired
    val done = required > 0 && s.qualityChecks >= required
    CapturePanel(Modifier.fillMaxWidth(), elevated = true) {
        Text("QUALITY CHECKS", style = MaterialTheme.typography.labelMedium, color = CaptureAccentBright)
        Text(
            "Reviewing other users' submissions helps the network, but it does not yet unlock " +
                "capturing — depositing the bond is the only unlock route today.",
            style = MaterialTheme.typography.bodySmall,
            color = MutedGray,
        )
        if (required > 0) {
            Text(
                "${s.qualityChecks} / $required quality checks",
                style = MaterialTheme.typography.titleMedium,
                color = CaptureAccent,
            )
            LinearProgressIndicator(
                progress = { (s.qualityChecks.toFloat() / required).coerceIn(0f, 1f) },
                modifier = Modifier.fillMaxWidth(),
            )
        }
        if (done) {
            DoneRow("Quality checks complete.")
        } else {
            Button(onClick = onReviewQueue, enabled = !s.busy, modifier = Modifier.fillMaxWidth()) {
                Text("Review submissions")
            }
        }
    }
}

@Composable
private fun DoneRow(text: String) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        CaptureIcon(CaptureSymbol.VERIFIED, Modifier.size(18.dp), SuccessGreen)
        Text(text, style = MaterialTheme.typography.bodySmall, color = SuccessGreen)
    }
}
