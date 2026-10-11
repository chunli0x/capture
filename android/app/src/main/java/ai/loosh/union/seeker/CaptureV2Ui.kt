package ai.loosh.union.seeker

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import ai.loosh.union.AccentCyan
import ai.loosh.union.AccentViolet
import ai.loosh.union.MutedGray

/**
 * The level 0..4 card: name, accepted count, acceptance rate, rate multiplier,
 * bond multiplier, and a progress bar toward the next level. Every value comes
 * from `/me` (or `/actor`) via [PilotState]; nothing is computed from local
 * guesswork beyond the client-side level table used for fallback naming.
 */
@Composable
fun LevelCard(s: PilotState) {
    val progress = levelProgress(s.acceptedCount)
    val nextLevel = progress.next
    val nextThreshold = progress.nextThreshold
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column {
                    Text("LEVEL ${s.level}", style = MaterialTheme.typography.labelSmall, color = AccentViolet)
                    Text(s.levelName, style = MaterialTheme.typography.titleLarge, color = MaterialTheme.colorScheme.onBackground)
                }
                Text("${s.acceptedCount} accepted", style = MaterialTheme.typography.labelSmall, color = MutedGray)
            }

            LinearProgressIndicator(progress = { progress.fraction }, modifier = Modifier.fillMaxWidth())

            if (nextLevel != null && nextThreshold != null) {
                Text(
                    "${(nextThreshold - progress.accepted).coerceAtLeast(0)} more accepted to reach ${levelName(nextLevel)}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                )
            } else {
                Text("Top level reached", style = MaterialTheme.typography.bodySmall, color = AccentCyan)
            }

            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                LevelStat("Acceptance", "${acceptancePercent(s.acceptanceRate)}%")
                LevelStat("Rate ×", "%.2f".format(s.rateMultiplier))
                LevelStat("Bond ×", if (s.bondMultiplier <= 0.0) "waived" else "%.1f".format(s.bondMultiplier))
            }
        }
    }
}

@Composable
private fun LevelStat(label: String, value: String) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(value, style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.onSurface)
        Text(label, style = MaterialTheme.typography.labelSmall, color = MutedGray)
    }
}

/**
 * The judge verdict + payout outcome for the most recent submission, rendered
 * from `{ verdict: { accepted, reason }, payout_usdc, level_after }`.
 *
 * Three states: accepted (+ payout), rejected (+ reason), and "no verdict yet"
 * for a legacy backend that returns a submission without a verdict.
 */
@Composable
fun VerdictCard(result: SubmissionResult, onDismiss: () -> Unit) {
    val accepted = result.verdict?.accepted == true
    val tint = if (accepted) AccentCyan else MaterialTheme.colorScheme.error
    Card(
        Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = tint.copy(alpha = 0.12f)),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(if (accepted) "Accepted" else "Rejected", style = MaterialTheme.typography.titleMedium, color = tint)
            when {
                result.paid ->
                    Text(
                        "Paid ${result.payoutUsdc / 1_000_000.0} TEST-USDC",
                        style = MaterialTheme.typography.bodyMedium,
                        color = tint,
                    )
                result.rejected ->
                    result.verdict?.reason?.takeIf { it.isNotBlank() }?.let {
                        Text(
                            "Reason: $it",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.8f),
                        )
                    }
                else ->
                    Text(
                        "Submitted — awaiting judgment.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
                    )
            }
            result.levelAfter?.let {
                Text("Level after: ${levelName(it)}", style = MaterialTheme.typography.labelSmall, color = AccentViolet)
            }
            TextButton(onClick = onDismiss, modifier = Modifier.align(Alignment.End)) {
                Text("Dismiss", color = tint)
            }
        }
    }
}
