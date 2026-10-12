package ai.loosh.union.seeker

import ai.loosh.union.CaptureAccentBright
import ai.loosh.union.CaptureBase
import ai.loosh.union.CaptureOutline
import ai.loosh.union.ErrorRed
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
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import org.json.JSONObject

/**
 * Lists open uploads awaiting peer review and records accept/reject decisions.
 * Each review increments the reviewer's quality-check count; two agreeing reviews settle a submission.
 */
@Composable
fun ReviewQueueScreen(
    s: PilotState,
    vm: SeekerViewModel,
    onBack: () -> Unit,
) {
    androidx.activity.compose.BackHandler(onBack = onBack)
    LaunchedEffect(Unit) { vm.loadReviewQueue() }
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
            TextButton(onClick = onBack, modifier = Modifier.align(Alignment.Start)) { Text("← Back") }
            Text("Review queue", style = MaterialTheme.typography.displaySmall)
            Text(
                "Accept or reject open uploads to build your free quality-check count. Two agreeing reviews settle a submission.",
                style = MaterialTheme.typography.bodySmall,
                color = MutedGray,
                textAlign = TextAlign.Center,
            )
            if (s.qualityChecksRequired > 0) {
                Text(
                    "${s.qualityChecks} / ${s.qualityChecksRequired} quality checks",
                    style = MaterialTheme.typography.titleMedium,
                    color = CaptureAccentBright,
                )
            }
            if (s.busy && s.reviewQueue.isEmpty()) {
                CircularProgressIndicator()
                Text(s.message, style = MaterialTheme.typography.bodySmall, color = MutedGray)
            } else if (s.reviewQueue.isEmpty()) {
                Column(
                    Modifier.fillMaxWidth().padding(vertical = 24.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    BrandLogo(Modifier.size(28.dp))
                    Text("No reviews to do right now", style = MaterialTheme.typography.titleMedium)
                    Text("Check back later.", style = MaterialTheme.typography.bodySmall, color = MutedGray)
                }
            } else {
                s.reviewQueue.forEach { sub -> ReviewCard(sub, s.busy, vm) }
            }
        }
    }
}

@Composable
private fun ReviewCard(sub: JSONObject, busy: Boolean, vm: SeekerViewModel) {
    val id = sub.getString("id")
    val bounty = sub.optJSONObject("bounty")
    val title = bounty?.optString("title")?.takeIf { it.isNotBlank() } ?: "Open capture"
    val kind = bounty?.optString("kind", KIND_OBJECT) ?: KIND_OBJECT
    Card(Modifier.fillMaxWidth(), border = BorderStroke(1.dp, CaptureOutline)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            Text(
                "Kind: $kind · ${id.take(8)}",
                style = MaterialTheme.typography.bodySmall,
                fontFamily = FontFamily.Monospace,
                color = MutedGray,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(
                    onClick = { vm.submitReview(id, true) },
                    enabled = !busy,
                    modifier = Modifier.weight(1f),
                    colors = ButtonDefaults.buttonColors(containerColor = SuccessGreen, contentColor = CaptureBase),
                ) {
                    Text("Accept")
                }
                OutlinedButton(
                    onClick = { vm.submitReview(id, false) },
                    enabled = !busy,
                    modifier = Modifier.weight(1f),
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = ErrorRed),
                ) {
                    Text("Reject")
                }
            }
        }
    }
}
