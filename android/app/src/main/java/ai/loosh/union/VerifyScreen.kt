package ai.loosh.union

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Card
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/**
 * The verify screen - the portable credential, and the screen the demo ends on.
 *
 * Everything shown here was read back from the chain by the backend, and the
 * two account addresses at the bottom are what let a buyer re-read it without
 * trusting us. That is the actual product; the badges above are a summary of
 * it, not a substitute.
 *
 * The badges say what the chain can support and no more. "Verified human"
 * means our verifier vouched for a liveness result and signed; it does not
 * mean the chain checked a face, which it cannot do. The server's own summary
 * is rendered verbatim underneath for exactly that reason.
 */
@Composable
fun VerifyScreen(
    attestation: Attestation?,
    busy: String?,
    onBack: () -> Unit,
) {
    Column(
        Modifier.fillMaxSize().padding(24.dp).verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Text("Attestation", style = MaterialTheme.typography.headlineSmall)

        when {
            busy != null && attestation == null ->
                Text(busy, style = MaterialTheme.typography.bodyMedium)

            attestation == null ->
                Text(
                    "Nothing to show yet.",
                    style = MaterialTheme.typography.bodyMedium,
                )

            !attestation.found ->
                Card(Modifier.fillMaxWidth()) {
                    Text(
                        "No attestation exists for this human and task.",
                        Modifier.padding(16.dp),
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }

            else -> AttestationCard(attestation)
        }

        TextButton(onClick = onBack) { Text("Back") }
    }
}

@Composable
private fun AttestationCard(attestation: Attestation) {
    Card(Modifier.fillMaxWidth()) {
        Column(
            Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Field("Human", attestation.human.orEmpty())
            Field("Task", attestation.taskId.orEmpty())
            Field("Time", formatUtc(attestation.attestedAt))
            Field("Bond", "%.4f HUMAN".format(attestation.uiBondAmount))
            Field("Status", attestation.status.orEmpty())
            Field("Verifier", attestation.verifier.orEmpty())

            HorizontalDivider(Modifier.padding(vertical = 8.dp))

            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Badge("Verified human", attestation.verifiedHuman)
                Badge("Task complete", attestation.taskComplete)
                Badge("Staked", attestation.staked)
            }

            HorizontalDivider(Modifier.padding(vertical = 8.dp))

            // Verbatim. The badges are a summary; this is the claim, and the
            // app must not soften or sharpen it on the way to the screen.
            Text(attestation.summary, style = MaterialTheme.typography.bodySmall)

            HorizontalDivider(Modifier.padding(vertical = 8.dp))

            Text(
                "Verify on-chain (${attestation.cluster})",
                style = MaterialTheme.typography.titleSmall,
            )
            // The addresses, not a QR code: anyone can paste these into an
            // explorer and read the same records without going through us,
            // which is the whole claim the credential makes.
            Mono("bond", attestation.bondAccount.orEmpty())
            Mono("attestation", attestation.attestationAccount.orEmpty())
        }
    }
}

@Composable
private fun Field(label: String, value: String) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(label, style = MaterialTheme.typography.labelMedium)
        Text(value, style = MaterialTheme.typography.bodyMedium)
    }
}

@Composable
private fun Mono(label: String, value: String) {
    Column {
        Text(label, style = MaterialTheme.typography.labelSmall)
        Text(
            value,
            style = MaterialTheme.typography.bodySmall.copy(
                fontFamily = FontFamily.Monospace
            ),
        )
    }
}

@Composable
private fun Badge(label: String, ok: Boolean) {
    // A cross rather than a hidden row: a missing badge reads as an oversight,
    // a failed one reads as a fact.
    Text(
        if (ok) "✓ $label" else "✗ $label",
        style = MaterialTheme.typography.bodySmall,
    )
}

/**
 * UTC, always.
 *
 * A credential timestamp rendered in whatever timezone the phone happens to
 * be in is a different string on every device, which makes two people
 * comparing the same attestation think they are looking at different ones.
 */
internal fun formatUtc(epochSeconds: Long): String {
    if (epochSeconds <= 0L) return "-"
    val format = SimpleDateFormat("yyyy-MM-dd HH:mm:ss 'UTC'", Locale.US)
    format.timeZone = TimeZone.getTimeZone("UTC")
    return format.format(Date(epochSeconds * 1000))
}

/**
 * The network screen: headline counts, then the quality board.
 *
 * `online now` is labelled an estimate on screen because it is one - a
 * heartbeat the backend cannot prove and nobody can audit. The other two
 * carry the backend's own note about where they came from, so a viewer is
 * never invited to read all three as equally solid.
 */
@Composable
fun NetworkScreen(
    stats: NetworkStats?,
    rows: List<LeaderRow>,
    busy: String?,
    onBack: () -> Unit,
) {
    Column(
        Modifier.fillMaxSize().padding(24.dp).verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Text("Network", style = MaterialTheme.typography.headlineSmall)

        stats?.let {
            Card(Modifier.fillMaxWidth()) {
                Column(
                    Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    Field("Online now (estimate)", it.onlineNowEstimate.toString())
                    Field("Acted today", it.actedToday.toString())
                    Field("Work proven", it.workProven.toString())
                    Text(
                        "Source: ${it.source}",
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
        }

        Text("Quality board", style = MaterialTheme.typography.titleMedium)
        Text(
            "Ranked by rolling gold-standard accuracy. Volume only separates " +
                "contributors who are already equally accurate.",
            style = MaterialTheme.typography.bodySmall,
        )

        if (rows.isEmpty()) {
            Text(
                if (busy != null) busy else "Nobody has done paid work yet.",
                style = MaterialTheme.typography.bodyMedium,
            )
        } else {
            rows.forEach { row ->
                Card(Modifier.fillMaxWidth()) {
                    Row(
                        Modifier.fillMaxWidth().padding(12.dp),
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        Text("#${row.rank}", style = MaterialTheme.typography.titleSmall)
                        Column(Modifier.weight(1f)) {
                            Text(
                                row.humanShort,
                                style = MaterialTheme.typography.bodyMedium.copy(
                                    fontFamily = FontFamily.Monospace
                                ),
                            )
                            Text(
                                "%.1f%% accurate · %d tasks · %.4f HUMAN".format(
                                    row.accuracy * 100, row.workCount, row.uiBond
                                ),
                                style = MaterialTheme.typography.bodySmall,
                            )
                        }
                    }
                }
            }
        }

        TextButton(onClick = onBack) { Text("Back") }
    }
}
