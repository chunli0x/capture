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
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import coil3.compose.AsyncImage

/**
 * The judgment product screen: a judge compares two model outputs (A/B) or rates
 * one 1-5, with a first-class "can't tell". Earns test USDC; bond is test USDC.
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
                    "test USDC on devnet.",
                style = MaterialTheme.typography.bodyMedium,
                color = MutedGray,
                textAlign = TextAlign.Center,
            )
            JudgeStatsCard(s)
            if (s.judgePair == null) {
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
            "${s.judgeJudgedCount} judged · ${formatToken(s.judgeStakedUsdc)} USDC staked · ${s.judgeWarnings} warnings",
            style = MaterialTheme.typography.bodySmall,
            color = MutedGray,
        )
    }
}

@Composable
private fun EmptyCard(s: PilotState, vm: SeekerViewModel, onBond: () -> Unit) {
    CapturePanel(Modifier.fillMaxWidth(), elevated = true) {
        Text("No pairs to judge right now", style = MaterialTheme.typography.titleMedium, color = CaptureInk)
        if (!s.bonded) {
            Button(onClick = onBond, modifier = Modifier.fillMaxWidth()) { Text("Deposit the USDC bond") }
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
    val required = if (taskType == "rating") 1 else 2
    var okCount by remember(pair) { mutableStateOf(0) }
    var failCount by remember(pair) { mutableStateOf(0) }
    val report: (Boolean) -> Unit = { if (it) okCount++ else failCount++ }
    val imagesReady = failCount == 0 && okCount >= required

    if (taskType == "rating") {
        Text("Rate this output (1–5)", style = MaterialTheme.typography.titleMedium, color = CaptureInk)
        OutputImage(pair.optString("output_a_url", ""), "Output", Modifier.fillMaxWidth(), report)
        if (failCount > 0) {
            OutlinedButton(
                onClick = { vm.judgeNext() },
                enabled = !s.busy,
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Couldn't load the image — try another") }
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            for (r in 1..5) {
                Button(
                    onClick = { vm.submitJudgment(rating = r) },
                    enabled = !s.busy && imagesReady,
                    modifier = Modifier.weight(1f),
                ) { Text("$r") }
            }
        }
        OutlinedButton(
            onClick = { vm.submitJudgment(choice = "cant_tell") },
            enabled = !s.busy && imagesReady,
            modifier = Modifier.fillMaxWidth(),
        ) { Text("Can't tell") }
    } else {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutputImage(pair.optString("output_a_url", ""), "A", Modifier.weight(1f), report)
            OutputImage(pair.optString("output_b_url", ""), "B", Modifier.weight(1f), report)
        }
        if (failCount > 0) {
            OutlinedButton(
                onClick = { vm.judgeNext() },
                enabled = !s.busy,
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Couldn't load an image — try another") }
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(
                onClick = { vm.submitJudgment(choice = "a") },
                enabled = !s.busy && imagesReady,
                modifier = Modifier.weight(1f),
            ) { Text("A") }
            Button(
                onClick = { vm.submitJudgment(choice = "b") },
                enabled = !s.busy && imagesReady,
                modifier = Modifier.weight(1f),
            ) { Text("B") }
        }
        OutlinedButton(
            onClick = { vm.submitJudgment(choice = "cant_tell") },
            enabled = !s.busy && imagesReady,
            modifier = Modifier.fillMaxWidth(),
        ) { Text("Can't tell") }
    }
}

@Composable
private fun OutputImage(url: String, label: String, modifier: Modifier = Modifier, onState: (Boolean) -> Unit = {}) {
    Column(modifier, horizontalAlignment = Alignment.CenterHorizontally) {
        Text(label, style = MaterialTheme.typography.labelMedium, color = CaptureAccentBright)
        if (url.isBlank()) {
            LaunchedEffect(url) { onState(false) }
            Text("No output", style = MaterialTheme.typography.bodySmall, color = MutedGray)
        } else {
            AsyncImage(
                model = url,
                contentDescription = "Output $label",
                contentScale = ContentScale.Crop,
                onSuccess = { onState(true) },
                onError = { onState(false) },
                modifier = Modifier
                    .fillMaxWidth()
                    .aspectRatio(1f)
                    .clip(RoundedCornerShape(12.dp)),
            )
        }
    }
}
