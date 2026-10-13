package ai.loosh.union.seeker

import ai.loosh.union.CaptureAccentBright
import ai.loosh.union.CaptureInk
import ai.loosh.union.MutedGray
import ai.loosh.union.SuccessGreen
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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import kotlin.math.floor

/** 1 test SKR = 1_000_000 base units (6 decimals), matching the SPL mint. */
private const val SKR_UNITS = 1_000_000.0

/** Formats SKR base units as a human amount, e.g. 1_000_000 -> "1.00". */
fun formatSkr(units: Long): String {
    val skr = units / SKR_UNITS
    return if (skr == floor(skr)) "%.0f".format(skr) else "%.2f".format(skr)
}

/** The balances page: what a judge has earned and staked (test $SKR, devnet). */
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
                "Test \$SKR on devnet — not real value.",
                style = MaterialTheme.typography.bodyMedium,
                color = MutedGray,
            )
            BalanceCard(s)
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
        AmountRow("Earned", formatSkr(s.judgeEarnedSkr))
        val pending = (s.judgeEarnedSkr - s.judgeSettledSkr).coerceAtLeast(0)
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            AmountRow("Pending", formatSkr(pending), Modifier.weight(1f))
            AmountRow("Settled", formatSkr(s.judgeSettledSkr), Modifier.weight(1f))
        }
        AmountRow("Staked", formatSkr(s.judgeStakedSkr))
        Text(
            "Level ${s.judgeLevelName} · ×${"%.2f".format(s.judgeRateMultiplier)} rate · ${s.judgeWarnings} warning${if (s.judgeWarnings == 1) "" else "s"}",
            style = MaterialTheme.typography.bodySmall,
            color = MutedGray,
        )
    }
}

@Composable
private fun AmountRow(label: String, amount: String, modifier: Modifier = Modifier) {
    Column(modifier.padding(vertical = 6.dp)) {
        Text(label, style = MaterialTheme.typography.labelSmall, color = MutedGray)
        Text(
            "$amount SKR",
            style = MaterialTheme.typography.headlineSmall,
            color = CaptureInk,
        )
    }
}
