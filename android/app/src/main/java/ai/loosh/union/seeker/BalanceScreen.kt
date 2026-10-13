package ai.loosh.union.seeker

import ai.loosh.union.CaptureAccentBright
import ai.loosh.union.CaptureInk
import ai.loosh.union.MutedGray
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import kotlin.math.floor

/** 1 token = 1_000_000 base units (6 decimals), matching the SPL mints. */
private const val TOKEN_UNITS = 1_000_000.0

/** Formats token base units as a human amount, e.g. 1_000_000 -> "1.00". */
fun formatToken(units: Long): String {
    val tokens = units / TOKEN_UNITS
    return if (tokens == floor(tokens)) "%.0f".format(tokens) else "%.2f".format(tokens)
}

/** The balances page: what a judge has earned (USDC) and staked (SKR), plus the
 *  level ladder. Test tokens on devnet, not real value. */
@Composable
fun BalanceScreen(s: PilotState, vm: SeekerViewModel, onBack: () -> Unit) {
    NavyBackground(Modifier.fillMaxSize().captureScreenMotion()) {
        Column(
            Modifier
                .fillMaxSize()
                .safeDrawingPadding()
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            CaptureWordmark()
            EditorialHeading("BALANCES.")
            Text(
                "Earned in test USDC, staked in test \$SKR — devnet only, not real value.",
                style = MaterialTheme.typography.bodyMedium,
                color = MutedGray,
            )
            BalanceCard(s)
            JudgeTierLadder(judgeLevelFrom(s.judgeAgreementRate))
            Button(onClick = { vm.refresh() }, enabled = !s.busy, modifier = Modifier.fillMaxWidth()) {
                Text("Refresh")
            }
            Button(onClick = onBack, modifier = Modifier.fillMaxWidth()) {
                Text("Back to judging")
            }
        }
    }
}

@Composable
private fun BalanceCard(s: PilotState) {
    CapturePanel(Modifier.fillMaxWidth(), elevated = true) {
        Text("YOUR BALANCE", style = MaterialTheme.typography.labelMedium, color = CaptureAccentBright)
        AmountRow("Earned", formatToken(s.judgeEarnedUsdc), "USDC")
        val pending = (s.judgeEarnedUsdc - s.judgeSettledUsdc).coerceAtLeast(0)
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            AmountRow("Pending", formatToken(pending), "USDC", Modifier.weight(1f))
            AmountRow("Settled", formatToken(s.judgeSettledUsdc), "USDC", Modifier.weight(1f))
        }
        AmountRow("Staked", formatToken(s.judgeStakedSkr), "SKR")
        Text(
            "Level ${s.judgeLevelName} · ×${"%.2f".format(s.judgeRateMultiplier)} rate · ${s.judgeWarnings} warning${if (s.judgeWarnings == 1) "" else "s"}",
            style = MaterialTheme.typography.bodySmall,
            color = MutedGray,
        )
    }
}

@Composable
private fun AmountRow(label: String, amount: String, unit: String, modifier: Modifier = Modifier) {
    Column(modifier.padding(vertical = 6.dp)) {
        Text(label, style = MaterialTheme.typography.labelSmall, color = MutedGray)
        Text(
            "$amount $unit",
            style = MaterialTheme.typography.headlineSmall,
            color = CaptureInk,
        )
    }
}
