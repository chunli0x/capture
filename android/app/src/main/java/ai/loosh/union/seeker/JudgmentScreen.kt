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
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp

/**
 * The judgment product screen: a judge compares two model outputs (A/B) or rates
 * one 1-5, with a first-class "can't tell". Uncalibrated judges see the
 * calibration progress and the known-consensus pairs first. Test $SKR on devnet.
 */
@Composable
fun JudgmentScreen(s: PilotState, vm: SeekerViewModel, onBond: () -> Unit) {
    NavyBackground(Modifier.fillMaxSize().captureScreenMotion()) {
        Column(
            Modifier
                .fillMaxSize()
                .safeDrawingPadding()
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            CaptureWordmark()
            EditorialHeading("JUDGE.")
            Text(
                "Compare two model outputs and pick the better one. Consensus-aligned judges earn " +
                    "test \$SKR on devnet.",
                style = MaterialTheme.typography.bodyMedium,
                color = MutedGray,
                textAlign = TextAlign.Center,
            )
            JudgeStatsCard(s)
            JudgeTierLadder(judgeLevelFrom(s.judgeAgreementRate))
            if (!s.judgeCalibrated) {
                CalibrationCard(s, vm)
            } else if (s.judgePair == null) {
                EmptyCard(s, vm, onBond)
            } else {
                PairCard(s, vm)
            }
        }
    }
}

@Composable
private fun JudgeStatsCard(s: PilotState) {
    CapturePanel(Modifier.fillMaxWidth()) {
        Text("YOUR JUDGE STATS", style = MaterialTheme.typography.labelMedium, color = CaptureAccentBright)
        Text(
            "Level ${s.judgeLevelName} · ${agreementPercent(s.judgeAgreementRate)}% agreement · ×${"%.2f".format(s.judgeRateMultiplier)} rate",
            style = MaterialTheme.typography.titleMedium,
            color = CaptureInk,
        )
        Text(
            "${s.judgeJudgedCount} judged · ${s.judgeStakedSkr} SKR staked · ${s.judgeWarnings} warnings",
            style = MaterialTheme.typography.bodySmall,
            color = MutedGray,
        )
    }
}

@Composable
private fun CalibrationCard(s: PilotState, vm: SeekerViewModel) {
    CapturePanel(Modifier.fillMaxWidth(), elevated = true) {
        Text("CALIBRATION", style = MaterialTheme.typography.labelMedium, color = CaptureAccentBright)
        Text(
            "Answer ${s.calibrationRequired} known pairs before you can stake and earn. " +
                "Calibration is unpaid. ${s.calibrationCorrect} correct so far.",
            style = MaterialTheme.typography.bodySmall,
            color = MutedGray,
        )
        val fraction =
            if (s.calibrationRequired > 0) {
                (s.calibrationCompleted.toFloat() / s.calibrationRequired).coerceIn(0f, 1f)
            } else {
                0f
            }
        LinearProgressIndicator(progress = { fraction }, modifier = Modifier.fillMaxWidth())
        PairChoice(s, vm)
    }
}

@Composable
private fun EmptyCard(s: PilotState, vm: SeekerViewModel, onBond: () -> Unit) {
    CapturePanel(Modifier.fillMaxWidth(), elevated = true) {
        Text("No pairs to judge right now", style = MaterialTheme.typography.titleMedium, color = CaptureInk)
        if (!s.bonded) {
            Button(onClick = onBond, modifier = Modifier.fillMaxWidth()) { Text("Deposit the SKR bond") }
        }
        Button(onClick = { vm.judgeNext() }, enabled = !s.busy, modifier = Modifier.fillMaxWidth()) {
            Text("Refresh")
        }
    }
}

@Composable
private fun PairCard(s: PilotState, vm: SeekerViewModel) {
    CapturePanel(Modifier.fillMaxWidth(), elevated = true) {
        val pair = s.judgePair
        if (pair == null) {
            Text("No pair loaded", style = MaterialTheme.typography.bodyMedium, color = MutedGray)
        } else {
            Text("TASK", style = MaterialTheme.typography.labelMedium, color = CaptureAccentBright)
            pair.optString("rubric", "").takeIf { it.isNotBlank() }?.let {
                Text(it, style = MaterialTheme.typography.bodyMedium, color = CaptureInk)
            }
            PairChoice(s, vm)
        }
    }
}

@Composable
private fun PairChoice(s: PilotState, vm: SeekerViewModel) {
    val pair = s.judgePair ?: return
    val taskType = pair.optString("task_type", "preference")
    if (taskType == "rating") {
        Text("Rate this output (1–5)", style = MaterialTheme.typography.titleMedium, color = CaptureInk)
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            for (r in 1..5) {
                Button(
                    onClick = { vm.submitJudgment(rating = r) },
                    enabled = !s.busy,
                    modifier = Modifier.weight(1f),
                ) { Text("$r") }
            }
        }
        OutlinedButton(
            onClick = { vm.submitJudgment(choice = "cant_tell") },
            enabled = !s.busy,
            modifier = Modifier.fillMaxWidth(),
        ) { Text("Can't tell") }
    } else {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(
                onClick = { vm.submitJudgment(choice = "a") },
                enabled = !s.busy,
                modifier = Modifier.weight(1f),
            ) { Text("A") }
            Button(
                onClick = { vm.submitJudgment(choice = "b") },
                enabled = !s.busy,
                modifier = Modifier.weight(1f),
            ) { Text("B") }
        }
        OutlinedButton(
            onClick = { vm.submitJudgment(choice = "cant_tell") },
            enabled = !s.busy,
            modifier = Modifier.fillMaxWidth(),
        ) { Text("Can't tell") }
    }
    pair.optString("output_a_url", "").takeIf { it.isNotBlank() }?.let {
        Text("A: $it", style = MaterialTheme.typography.labelSmall, color = MutedGray)
    }
    pair.optString("output_b_url", "").takeIf { it.isNotBlank() }?.let {
        Text("B: $it", style = MaterialTheme.typography.labelSmall, color = MutedGray)
    }
}
