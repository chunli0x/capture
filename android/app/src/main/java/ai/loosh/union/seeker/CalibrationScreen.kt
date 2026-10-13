package ai.loosh.union.seeker

import ai.loosh.union.CaptureAccentBright
import ai.loosh.union.CaptureBaseDeep
import ai.loosh.union.CaptureInk
import ai.loosh.union.CaptureOutline
import ai.loosh.union.CaptureRadii
import ai.loosh.union.CaptureSurface2
import ai.loosh.union.MutedGray
import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp

/**
 * The calibration page: how judging works (examples), what it pays, and the
 * judge's own standing. Large and gamified, but informational — it does not
 * gate staking.
 */
@Composable
fun CalibrationScreen(s: PilotState, vm: SeekerViewModel, onBack: () -> Unit) {
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
            EditorialHeading("CALIBRATE.")
            Text(
                "How to judge, what it pays, and where you stand.",
                style = MaterialTheme.typography.bodyMedium,
                color = CaptureInk,
            )
            ExampleCard()
            PayCard(s)
            StandingCard(s)
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
private fun ExampleCard() {
    CapturePanel(Modifier.fillMaxWidth()) {
        Text("EXAMPLES", style = MaterialTheme.typography.labelMedium, color = CaptureAccentBright)
        Text("Preference: pick the better output", style = MaterialTheme.typography.titleSmall, color = CaptureInk)
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutputBox("A", "Output A", Modifier.weight(1f))
            OutputBox("B", "Output B", Modifier.weight(1f))
        }
        Text("Rating: score one output 1-5", style = MaterialTheme.typography.titleSmall, color = CaptureInk)
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            for (r in 1..5) {
                Text(
                    "$r",
                    style = MaterialTheme.typography.titleMedium,
                    color = CaptureInk,
                    textAlign = TextAlign.Center,
                    modifier = Modifier
                        .weight(1f)
                        .background(CaptureSurface2, CaptureRadii.pill)
                        .border(1.dp, CaptureOutline, CaptureRadii.pill)
                        .padding(vertical = 10.dp),
                )
            }
        }
        Text(
            "\"Can't tell\" is always an option. It pays a small flat and reroutes the pair.",
            style = MaterialTheme.typography.bodySmall,
            color = MutedGray,
        )
        Text(
            "Video / frame sequence — COMING SOON",
            style = MaterialTheme.typography.titleSmall,
            color = CaptureInk,
        )
        Text(
            "Judge a short motion clip instead of a still frame. The next tier.",
            style = MaterialTheme.typography.bodySmall,
            color = MutedGray,
        )
    }
}

@Composable
private fun OutputBox(label: String, caption: String, modifier: Modifier = Modifier) {
    Column(
        modifier
            .background(CaptureBaseDeep, CaptureRadii.md)
            .border(2.dp, CaptureOutline, CaptureRadii.md)
            .padding(12.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(label, style = MaterialTheme.typography.headlineSmall, color = CaptureInk)
        Text(caption, style = MaterialTheme.typography.labelSmall, color = MutedGray)
    }
}

@Composable
private fun PayCard(s: PilotState) {
    CapturePanel(Modifier.fillMaxWidth()) {
        Text("WHAT YOU EARN", style = MaterialTheme.typography.labelMedium, color = CaptureAccentBright)
        val mult = s.judgeRateMultiplier
        Text(
            "Base \$0.02 USDC per aligned judgment × your ×${"%.2f".format(mult)} multiplier = \$" +
                "%.4f".format(0.02 * mult) + ".",
            style = MaterialTheme.typography.bodySmall,
            color = CaptureInk,
        )
        Text("Dissent pays \$0.", style = MaterialTheme.typography.bodySmall, color = CaptureInk)
        Text("\"Can't tell\" pays a flat \$0.005.", style = MaterialTheme.typography.bodySmall, color = CaptureInk)
        Text(
            "Paid in test USDC on devnet — not real value.",
            style = MaterialTheme.typography.labelSmall,
            color = MutedGray,
        )
    }
}

@Composable
private fun StandingCard(s: PilotState) {
    CapturePanel(Modifier.fillMaxWidth(), elevated = true) {
        Text("YOUR STANDING", style = MaterialTheme.typography.labelMedium, color = CaptureAccentBright)
        Text(
            "${agreementPercent(s.judgeAgreementRate)}%",
            style = MaterialTheme.typography.headlineMedium,
            color = CaptureInk,
        )
        Text("agreement with the crowd", style = MaterialTheme.typography.labelSmall, color = MutedGray)
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Metric("Judged", "${s.judgeJudgedCount}", Modifier.weight(1f))
            Metric("Level", s.judgeLevelName, Modifier.weight(1f))
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Metric("Earned", "${formatToken(s.judgeEarnedUsdc)} USDC", Modifier.weight(1f))
            Metric("Warnings", "${s.judgeWarnings}", Modifier.weight(1f))
        }
    }
}

@Composable
private fun Metric(label: String, value: String, modifier: Modifier = Modifier) {
    Column(modifier.padding(vertical = 6.dp)) {
        Text(label, style = MaterialTheme.typography.labelSmall, color = MutedGray)
        Text(value, style = MaterialTheme.typography.titleMedium, color = CaptureInk)
    }
}
