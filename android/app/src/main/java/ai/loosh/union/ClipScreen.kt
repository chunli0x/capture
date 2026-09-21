package ai.loosh.union

import android.net.Uri
import android.widget.MediaController
import android.widget.VideoView
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView

/**
 * The clip-judgment task screen: watch, then answer.
 *
 * Playback uses the framework's [VideoView] rather than a media library. The
 * clips are short, local-network MP4s with no DRM, adaptive streaming or
 * playlist behaviour, so a dependency would buy nothing the demo needs.
 *
 * The two answer buttons and "flag as unclear" are the whole interaction. The
 * flag button is hidden, not merely disabled, when the server says flagging is
 * unavailable: during the blind qualification run an escape hatch would be a
 * way past any item a bot could not answer, and a greyed-out control invites
 * people to wonder why.
 */
@Composable
fun ClipScreen(
    task: ClipTask,
    submitted: ClipResult?,
    busy: String?,
    onAnswer: (String) -> Unit,
    onFlag: () -> Unit,
    onNext: () -> Unit,
    onLeave: () -> Unit,
) {
    Column(
        Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text(
            when (task.mode) {
                "practice" -> "Practice"
                "qualify" -> "Qualification"
                else -> "Task"
            },
            style = MaterialTheme.typography.headlineSmall,
        )

        if (task.placeholder) {
            // Loudly, because a synthetic stand-in proves nothing about a task
            // being hard for a bot, and showing one while claiming otherwise
            // is exactly the overclaim this project keeps guarding against.
            Card(Modifier.fillMaxWidth()) {
                Text(
                    "Placeholder clip - not real footage. Not for demo use.",
                    Modifier.padding(12.dp),
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }

        ClipPlayer(
            url = task.clipUrl,
            modifier = Modifier.fillMaxWidth().aspectRatio(16f / 9f),
        )

        Text(task.question, style = MaterialTheme.typography.titleMedium)

        if (submitted == null) {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                task.choices.forEach { choice ->
                    Button(
                        onClick = { onAnswer(choice) },
                        enabled = busy == null,
                        modifier = Modifier.weight(1f),
                    ) { Text(choice.replaceFirstChar { it.uppercase() }) }
                }
            }
            if (task.canFlag) {
                OutlinedButton(
                    onClick = onFlag,
                    enabled = busy == null,
                    modifier = Modifier.fillMaxWidth(),
                ) { Text("Flag as unclear") }
            }
        } else {
            ClipOutcome(submitted)
            Button(
                onClick = onNext,
                enabled = busy == null,
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Next") }
        }

        if (task.reward > 0) {
            Text(
                "Reward: ${task.reward}",
                style = MaterialTheme.typography.bodySmall,
            )
        }
        busy?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
        TextButton(onClick = onLeave) { Text("Back") }
    }
}

@Composable
private fun ClipOutcome(result: ClipResult) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            when {
                result.flagged -> Text("Flagged. Nothing scored, nothing paid.")
                // Practice is the only mode that returns correctness. In a
                // blind run it would be the answer, and in paid work it would
                // reveal which items are the hidden graded ones.
                result.correct == true -> Text("Correct.")
                result.correct == false ->
                    Text("Not quite - the answer was ${result.expected}.")
                result.reward > 0 -> Text("Answer recorded. Reward: ${result.reward}")
                else -> Text("Answer recorded.")
            }

            result.qualification?.let { q ->
                Text(
                    if (q.passed) "Qualified: ${q.correct}/${q.graded} correct."
                    else "Not qualified: ${q.correct}/${q.graded}, " +
                        "${q.required} needed.",
                    style = MaterialTheme.typography.bodyMedium,
                )
                // Reported alongside the result so a pass is never shown
                // without what it was worth.
                Text(
                    "A random guesser clears this gate " +
                        "%.2f%% of the time.".format(q.chancePass * 100),
                    style = MaterialTheme.typography.bodySmall,
                )
                if (!q.passed && q.retryAvailable) {
                    Text(
                        "You can retry once after a short cooldown.",
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
        }
    }
}

@Composable
private fun ClipPlayer(url: String, modifier: Modifier = Modifier) {
    AndroidView(
        modifier = modifier,
        factory = { ctx ->
            VideoView(ctx).apply {
                setMediaController(MediaController(ctx).also { it.setAnchorView(this) })
                setVideoURI(Uri.parse(url))
                // Looping: the judgment is the point, and making someone hunt
                // for a replay button turns a two-second task into a fiddle.
                setOnPreparedListener { player ->
                    player.isLooping = true
                    start()
                }
            }
        },
        update = { view ->
            val current = view.tag as? String
            if (current != url) {
                view.tag = url
                view.setVideoURI(Uri.parse(url))
                view.start()
            }
        },
        onRelease = { it.stopPlayback() },
    )
}

/**
 * The clip campaign's entry screen: prove you're human, then practise, qualify, earn.
 *
 * The order on screen is the order the product claims: liveness first, then
 * work. The earn button stays disabled until the blind gate is passed, and
 * says which of the two is missing rather than just refusing.
 */
@Composable
fun ClipPrimerScreen(
    state: UiState,
    onStart: (String) -> Unit,
    onProveHuman: () -> Unit,
    onRetry: () -> Unit,
    onVerify: (String) -> Unit,
    onNetwork: () -> Unit,
    onBack: () -> Unit,
) {
    Column(
        Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Clip judgment", style = MaterialTheme.typography.headlineSmall)
        Text(
            "Watch a short clip and answer a question that is obvious to you " +
                "and hard for a bot.",
            style = MaterialTheme.typography.bodyMedium,
        )

        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                val proof = state.livenessProof
                Text(
                    if (proof == null) "Not yet verified as human"
                    else "Human check complete",
                    style = MaterialTheme.typography.titleSmall,
                )
                // The server's own wording for what the check establishes.
                // Displayed rather than paraphrased, so the app cannot drift
                // into claiming more than the backend does.
                proof?.let {
                    Text(it.attests, style = MaterialTheme.typography.bodySmall)
                }
            }
        }

        Button(
            onClick = onProveHuman,
            enabled = state.busy == null,
            modifier = Modifier.fillMaxWidth(),
        ) { Text(if (state.livenessProof == null) "Prove you're human" else "Check again") }

        Button(
            onClick = { onStart(ClipMode.PRACTICE) },
            enabled = state.busy == null,
            modifier = Modifier.fillMaxWidth(),
        ) { Text("Practice") }

        Button(
            onClick = { onStart(ClipMode.QUALIFY) },
            enabled = state.busy == null && !state.clipQualified,
            modifier = Modifier.fillMaxWidth(),
        ) { Text(if (state.clipQualified) "Qualified" else "Take the qualification") }

        state.clipQualification?.let { q ->
            if (!q.passed && q.retryAvailable) {
                OutlinedButton(
                    onClick = onRetry,
                    enabled = state.busy == null,
                    modifier = Modifier.fillMaxWidth(),
                ) { Text("Retry qualification") }
            }
        }

        Button(
            onClick = { onStart(ClipMode.EARN) },
            enabled = state.busy == null && state.clipQualified,
            modifier = Modifier.fillMaxWidth(),
        ) { Text("Earn") }

        if (!state.clipQualified) {
            Text(
                "Paid work unlocks after the qualification run.",
                style = MaterialTheme.typography.bodySmall,
            )
        }
        if (state.uiClipBalance > 0) {
            Text(
                "Clip earnings: %.4f".format(state.uiClipBalance),
                style = MaterialTheme.typography.bodySmall,
            )
        }

        // The credential is the product, so it gets a route from the screen
        // people actually stand on rather than being reachable only in theory.
        state.lastPaidClipTaskId?.let { taskId ->
            OutlinedButton(
                onClick = { onVerify(taskId) },
                enabled = state.busy == null,
                modifier = Modifier.fillMaxWidth(),
            ) { Text("View my attestation") }
        }
        OutlinedButton(
            onClick = onNetwork,
            enabled = state.busy == null,
            modifier = Modifier.fillMaxWidth(),
        ) { Text("Network") }

        TextButton(onClick = onBack) { Text("Back") }
    }
}
