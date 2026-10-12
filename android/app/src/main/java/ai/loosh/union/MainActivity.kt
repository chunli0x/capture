package ai.loosh.union

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.enableEdgeToEdge
import androidx.compose.ui.graphics.toArgb
import androidx.activity.compose.setContent
import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.LocalTextStyle
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import coil3.compose.AsyncImage
import com.solana.mobilewalletadapter.clientlib.ActivityResultSender

class MainActivity : ComponentActivity() {

    // Must be constructed during onCreate: ActivityResultSender registers an
    // activity result launcher, which throws if done after the activity starts.
    private lateinit var sender: ActivityResultSender

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.light(CaptureBaseDeep.toArgb(), CaptureBaseDeep.toArgb()),
            navigationBarStyle = SystemBarStyle.light(CaptureBase.toArgb(), CaptureBase.toArgb()),
        )
        sender = ActivityResultSender(this)

        setContent {
            CaptureTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background,
                ) {
                    ai.loosh.union.seeker.SeekerApp(sender)
                }
            }
        }
    }
}

// Legacy accent references retained for the dormant Union flow; repointed at
// the Capture palette so nothing renders green.
private val Accent = CaptureAccent
private val Warn = WarnAmber

@Composable
fun UnionApp(sender: ActivityResultSender, vm: UnionViewModel = viewModel()) {
    val state by vm.state.collectAsState()

    Scaffold { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(horizontal = 20.dp, vertical = 16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Header(state)

            when (state.screen) {
                Screen.CONNECT -> ConnectScreen(
                    state = state,
                    onServerUrlChange = vm::setServerUrl,
                    onTestServer = vm::testServer,
                    onConnect = { vm.connect(sender) },
                )
                Screen.CAMPAIGNS -> CampaignsScreen(
                    state = state,
                    onOpen = vm::openCampaign,
                    onClaim = { vm.claim(sender) },
                )
                Screen.POSE_PRIMER -> PosePrimerScreen(
                    state = state,
                    onStart = vm::startPose,
                    onBack = vm::leavePose,
                )
                Screen.POSE_TASK -> PoseTaskScreen(
                    state = state,
                    onPoseChange = vm::updatePose,
                    onSubmit = vm::submitPose,
                    onNext = vm::nextPoseTask,
                    onRecentre = vm::recentreGhost,
                    onFlag = vm::flagTask,
                    onBack = vm::leavePose,
                )
                Screen.CLIP_PRIMER -> ClipPrimerScreen(
                    state = state,
                    onStart = vm::startClip,
                    onProveHuman = { vm.startLiveness("clip-session") },
                    onRetry = vm::retryClipQualification,
                    onVerify = vm::openVerify,
                    onNetwork = vm::openNetwork,
                    onBack = vm::leaveClip,
                )
                Screen.CLIP_TASK -> ClipScreen(
                    task = state.clipTask ?: return@Column,
                    submitted = state.clipResult,
                    busy = state.busy,
                    onAnswer = vm::answerClip,
                    onFlag = vm::flagClip,
                    onNext = vm::nextClipTask,
                    onLeave = vm::leaveClip,
                )
                Screen.LIVENESS -> LivenessScreen(
                    challengeWire = state.livenessSession?.challenge.orEmpty(),
                    busy = state.busy,
                    onPassed = vm::completeLiveness,
                    onCancel = vm::cancelLiveness,
                )
                Screen.VERIFY -> VerifyScreen(
                    attestation = state.attestation,
                    busy = state.busy,
                    onBack = vm::leaveDetail,
                )
                Screen.NETWORK -> NetworkScreen(
                    stats = state.networkStats,
                    rows = state.leaderboard,
                    busy = state.busy,
                    onBack = vm::leaveDetail,
                )
                Screen.SOLVING -> SolvingScreen(
                    state = state,
                    onToggle = vm::toggleCell,
                    onSubmit = vm::submit,
                    onNext = vm::loadNextTask,
                    onBack = vm::backToCampaigns,
                )
            }

            state.busy?.let { Busy(it) }
            state.error?.let { ErrorCard(it, vm::dismissError) }
        }
    }
}

@Composable
private fun Header(state: UiState) {
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column {
            Text(
                "Union",
                fontSize = 24.sp,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onBackground,
            )
            Text(
                state.walletShort ?: "not connected",
                fontSize = 12.sp,
                fontFamily = FontFamily.Monospace,
                color = Accent,
            )
        }
        if (state.wallet != null) {
            Column(horizontalAlignment = Alignment.End) {
                Text(
                    "%.4f USDC".format(state.uiTotalClaimable),
                    fontSize = 18.sp,
                    fontWeight = FontWeight.SemiBold,
                    fontFamily = FontFamily.Monospace,
                    color = MaterialTheme.colorScheme.onBackground,
                )
                Text(
                    "${state.solved} solved",
                    fontSize = 12.sp,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                )
            }
        }
    }
}

@Composable
private fun ConnectScreen(
    state: UiState,
    onServerUrlChange: (String) -> Unit,
    onTestServer: () -> Unit,
    onConnect: () -> Unit,
) {
    var draft by remember(state.serverUrl) { mutableStateOf(state.serverUrl) }

    Column(
        Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Spacer(Modifier.height(16.dp))
        Text(
            "Label training data. Get paid to the wallet already in your phone.",
            fontSize = 20.sp,
            color = MaterialTheme.colorScheme.onBackground,
        )
        Text(
            "Devnet build. Rewards are test tokens.",
            fontSize = 13.sp,
            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
        )

        // The backend usually runs on a laptop on the same wifi, so the address
        // has to be editable here - otherwise trying the app would mean
        // rebuilding it.
        Card(Modifier.fillMaxWidth()) {
            Column(
                Modifier.padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Text("Server", fontSize = 12.sp, color = Accent)
                OutlinedTextField(
                    value = draft,
                    onValueChange = { draft = it },
                    singleLine = true,
                    placeholder = { Text("192.168.1.20:8000", fontSize = 13.sp) },
                    textStyle = LocalTextStyle.current.copy(
                        fontFamily = FontFamily.Monospace,
                        fontSize = 13.sp,
                    ),
                    modifier = Modifier.fillMaxWidth(),
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(
                        onClick = {
                            onServerUrlChange(draft)
                            onTestServer()
                        },
                        enabled = state.busy == null && draft.isNotBlank(),
                        modifier = Modifier.weight(1f),
                    ) { Text("Save and test", fontSize = 13.sp) }
                }
                if (state.serverReachable) {
                    Text(
                        "Reachable - ${state.campaigns.count { it.isLive }} campaigns live",
                        fontSize = 12.sp,
                        color = Accent,
                    )
                } else {
                    Text(
                        "Run ./scripts/run_demo.sh on your computer; it prints this address.",
                        fontSize = 11.sp,
                        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.55f),
                    )
                }
            }
        }

        Button(
            onClick = onConnect,
            enabled = state.busy == null,
            modifier = Modifier.fillMaxWidth(),
        ) { Text("Connect wallet") }
    }
}

@Composable
private fun CampaignsScreen(
    state: UiState,
    onOpen: (Campaign) -> Unit,
    onClaim: () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        EligibilityCard(state)

        Button(
            onClick = onClaim,
            enabled = state.claimable && state.busy == null,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text(
                if (state.claimable) {
                    "Claim %.4f USDC".format(state.uiTotalClaimable)
                } else {
                    "Claim"
                }
            )
        }

        ReferralCard(state)

        state.lastSignature?.let { signature ->
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text("Paid on devnet", color = Accent, fontWeight = FontWeight.SemiBold)
                    Text(
                        signature,
                        fontFamily = FontFamily.Monospace,
                        fontSize = 10.sp,
                        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
                    )
                }
            }
        }

        Text(
            "Campaigns",
            fontSize = 13.sp,
            fontWeight = FontWeight.SemiBold,
            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
        )
        LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            items(state.campaigns) { campaign ->
                CampaignRow(campaign) { onOpen(campaign) }
            }
        }
    }
}

/**
 * The primer.
 *
 * Named "image-plane pose" here and everywhere else it is user-visible. A flat
 * sprite records x, y, roll and an apparent scale - it cannot express pitch,
 * yaw or depth, so calling it 6D would be an overclaim an egocentric-capture
 * data buyer spots immediately.
 */
@Composable
private fun PosePrimerScreen(
    state: UiState,
    onStart: (String) -> Unit,
    onBack: () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
        TextButton(onClick = onBack) { Text("← Campaigns") }

        Text(
            "Line up the ghost",
            fontSize = 22.sp,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.onBackground,
        )
        Text(
            "Drag the translucent outline onto the object until it matches. "
                + "One finger moves it, two fingers twist it, pinch resizes it.",
            fontSize = 14.sp,
            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.75f),
        )

        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                PrimerRow("1", "Practice", "Instant feedback, and the ghost glows when you are on target.")
                PrimerRow("2", "Qualify", "A blind test. No feedback, no glow, until it is over.")
                PrimerRow("3", "Earn", "Paid labels, claimed to your wallet.")
            }
        }

        state.qualification?.let { q ->
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(14.dp)) {
                    Text(
                        q.summary,
                        fontSize = 13.sp,
                        color = if (q.qualified) Accent else Warn,
                    )
                }
            }
        }

        Button(
            onClick = { onStart(PoseMode.PRACTICE) },
            enabled = state.busy == null,
            modifier = Modifier.fillMaxWidth(),
        ) { Text("Practice") }

        OutlinedButton(
            onClick = { onStart(PoseMode.QUALIFY) },
            enabled = state.busy == null,
            modifier = Modifier.fillMaxWidth(),
        ) { Text("Take the blind test") }

        if (state.poseQualified) {
            Button(
                onClick = { onStart(PoseMode.EARN) },
                enabled = state.busy == null,
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Start earning") }
        }
    }
}

@Composable
private fun PrimerRow(step: String, title: String, body: String) {
    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(step, fontFamily = FontFamily.Monospace, fontSize = 13.sp, color = Accent)
        Column {
            Text(title, fontWeight = FontWeight.SemiBold, fontSize = 14.sp,
                 color = MaterialTheme.colorScheme.onSurface)
            Text(body, fontSize = 12.sp,
                 color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.62f))
        }
    }
}

@Composable
private fun PoseTaskScreen(
    state: UiState,
    onPoseChange: (GhostPose) -> Unit,
    onSubmit: () -> Unit,
    onNext: () -> Unit,
    onRecentre: () -> Unit,
    onFlag: (String) -> Unit,
    onBack: () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            TextButton(onClick = onBack) { Text("← Back") }
            Text(
                when (state.poseMode) {
                    PoseMode.QUALIFY -> state.poseTask?.let { t ->
                        "Blind test ${t.index ?: 1} of ${t.of ?: 1}"
                    } ?: "Blind test"
                    PoseMode.EARN -> "Earning"
                    else -> "Practice"
                },
                fontFamily = FontFamily.Monospace,
                fontSize = 12.sp,
                color = if (state.poseMode == PoseMode.QUALIFY) Warn else Accent,
            )
        }

        val task = state.poseTask
        val obj = state.poseObject
        if (task == null || obj == null) {
            Text("Loading task…", color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f))
            return@Column
        }

        Text(
            "Match the ${obj.label.lowercase()}",
            fontSize = 18.sp,
            fontWeight = FontWeight.SemiBold,
            color = MaterialTheme.colorScheme.onBackground,
        )
        Text(
            "Look for the ${obj.rollFeature} to get the rotation right.",
            fontSize = 12.sp,
            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
        )

        GhostOverlay(
            imageUrl = task.imageUrl,
            spriteUrl = obj.spriteUrl,
            canvasPx = task.canvas,
            spritePxAtScale1 = obj.spritePxAtScale1,
            pose = state.pose,
            // Both come from the server and are null/false outside practice,
            // so a blind run cannot render a proximity hint.
            allowSnap = task.allowSnap,
            truth = task.truth,
            enabled = !state.poseSubmitted,
            onPoseChange = onPoseChange,
        )

        state.poseFeedback?.let { f ->
            Card(Modifier.fillMaxWidth()) {
                Row(
                    Modifier.fillMaxWidth().padding(16.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Text(
                        if (f.withinTolerance) "On target" else "Off target",
                        fontWeight = FontWeight.SemiBold,
                        color = if (f.withinTolerance) Accent else Warn,
                    )
                    Text(
                        "%.0f px · %.1f°".format(f.errorPx, f.errorDeg),
                        fontFamily = FontFamily.Monospace,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                }
            }
        }

        state.qualification?.takeIf { state.poseSubmitted && it.attempted >= it.required }
            ?.let { q ->
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text(
                            if (q.qualified) "Qualified" else "Not qualified",
                            fontWeight = FontWeight.Bold,
                            color = if (q.qualified) Accent else MaterialTheme.colorScheme.error,
                        )
                        Text(q.summary, fontSize = 12.sp,
                             color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f))
                    }
                }
            }

        if (!state.poseSubmitted) {
            Button(
                onClick = onSubmit,
                enabled = state.canSubmitPose,
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Done") }

            // Escape hatches. The ghost is clamped to the frame, but a user who
            // has pushed it into a corner still wants a way back; and forcing a
            // guess on an unclear or empty frame produces a confident wrong
            // label, which is worse for the dataset than no label.
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                OutlinedButton(
                    onClick = onRecentre,
                    enabled = state.busy == null,
                    modifier = Modifier.weight(1f),
                ) { Text("Recentre", fontSize = 13.sp) }

                // The blind set is a fixed number of items, so skipping is
                // refused there - otherwise a labeler could reroll until the
                // set was easy and the gate would measure persistence.
                if (state.poseMode != PoseMode.QUALIFY) {
                    OutlinedButton(
                        onClick = { onFlag("unclear") },
                        enabled = state.busy == null,
                        modifier = Modifier.weight(1f),
                    ) { Text("Unclear", fontSize = 13.sp) }

                    OutlinedButton(
                        onClick = { onFlag("no_object") },
                        enabled = state.busy == null,
                        modifier = Modifier.weight(1f),
                    ) { Text("No object", fontSize = 13.sp) }
                }
            }
        } else {
            Button(
                onClick = onNext,
                enabled = state.busy == null,
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Next") }
        }
    }
}

@Composable
private fun CampaignRow(campaign: Campaign, onClick: () -> Unit) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(enabled = campaign.isLive, onClick = onClick),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface,
        ),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(
                    campaign.title,
                    fontWeight = FontWeight.SemiBold,
                    color = if (campaign.isLive) {
                        MaterialTheme.colorScheme.onSurface
                    } else {
                        MaterialTheme.colorScheme.onSurface.copy(alpha = 0.45f)
                    },
                )
                Text(
                    if (campaign.isLive) "LIVE" else "SOON",
                    fontSize = 11.sp,
                    fontWeight = FontWeight.Bold,
                    color = if (campaign.isLive) Accent else Warn,
                )
            }
            Text(
                campaign.description,
                fontSize = 13.sp,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.65f),
            )
            Text(
                "%.4f USDC per task".format(campaign.rewardPerTask / 1_000_000.0),
                fontSize = 12.sp,
                fontFamily = FontFamily.Monospace,
                color = Accent,
            )
        }
    }
}

@Composable
private fun EligibilityCard(state: UiState) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text("Accuracy", fontSize = 12.sp, color = Accent)
                Text(
                    if (state.goldSamples == 0) "—" else "%.0f%%".format(state.accuracy * 100),
                    fontSize = 12.sp,
                    fontFamily = FontFamily.Monospace,
                    color = MaterialTheme.colorScheme.onSurface,
                )
            }
            LinearProgressIndicator(
                progress = { state.accuracy.toFloat().coerceIn(0f, 1f) },
                modifier = Modifier.fillMaxWidth(),
            )
            Text(
                state.eligibilityReason.ifBlank { "Solve tasks to build a verified record." },
                fontSize = 12.sp,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.65f),
            )
        }
    }
}

/**
 * Referral standing.
 *
 * A referrer is paid out of the platform's margin, never out of the referee's
 * earnings, so nothing here reduces what a referred contributor takes home.
 */
@Composable
private fun ReferralCard(state: UiState) {
    val referral = state.referral ?: return
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text("Referrals", fontSize = 12.sp, color = Accent)
                Text(
                    "${referral.referees} joined",
                    fontSize = 12.sp,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
                )
            }
            Text(
                "%.4f USDC earned".format(referral.uiEarned),
                fontSize = 16.sp,
                fontFamily = FontFamily.Monospace,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                referral.reason,
                fontSize = 11.sp,
                color = if (referral.eligible) {
                    Accent
                } else {
                    Warn
                },
            )
            if (state.uiReferralUnclaimed > 0.0) {
                Text(
                    "%.4f USDC of your claimable balance is referral earnings".format(
                        state.uiReferralUnclaimed
                    ),
                    fontSize = 11.sp,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                )
            }
        }
    }
}

@Composable
private fun SolvingScreen(
    state: UiState,
    onToggle: (Int) -> Unit,
    onSubmit: () -> Unit,
    onNext: () -> Unit,
    onBack: () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
        TextButton(onClick = onBack) { Text("← Campaigns") }

        val task = state.task
        if (task == null) {
            Text(
                "Loading task…",
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
            )
            return@Column
        }

        Text(
            task.prompt,
            fontSize = 19.sp,
            fontWeight = FontWeight.SemiBold,
            color = MaterialTheme.colorScheme.onBackground,
        )

        TapGrid(
            imageUrl = task.imageUrl,
            grid = task.grid,
            selected = state.selected,
            locked = state.feedback != null,
            onToggle = onToggle,
        )

        state.feedback?.let { FeedbackCard(it) }

        if (state.feedback == null) {
            Button(
                onClick = onSubmit,
                enabled = state.canSubmit,
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Submit") }
        } else {
            Button(
                onClick = onNext,
                enabled = state.busy == null,
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Next task") }
        }
    }
}

/**
 * The task image with a tap grid over it.
 *
 * The grid is an overlay rather than sliced tiles so the image loads once and
 * cells line up exactly with the generator's geometry, which places every
 * object wholly inside one cell.
 */
@Composable
private fun TapGrid(
    imageUrl: String,
    grid: Int,
    selected: Set<Int>,
    locked: Boolean,
    onToggle: (Int) -> Unit,
) {
    Box(
        Modifier
            .fillMaxWidth()
            .aspectRatio(1f)
            .clip(RoundedCornerShape(14.dp))
            .background(MaterialTheme.colorScheme.surface),
    ) {
        AsyncImage(
            model = imageUrl,
            contentDescription = "Labeling task",
            modifier = Modifier.fillMaxSize(),
            contentScale = ContentScale.Fit,
        )
        Column(Modifier.fillMaxSize()) {
            repeat(grid) { row ->
                Row(Modifier.fillMaxWidth().weight(1f)) {
                    repeat(grid) { col ->
                        val cell = row * grid + col
                        val isSelected = cell in selected
                        val overlay by animateColorAsState(
                            targetValue = if (isSelected) {
                                Accent.copy(alpha = 0.28f)
                            } else {
                                Color.Transparent
                            },
                            label = "cell-$cell",
                        )
                        Box(
                            Modifier
                                .weight(1f)
                                .fillMaxSize()
                                .background(overlay)
                                .border(
                                    width = if (isSelected) 3.dp else 0.dp,
                                    color = if (isSelected) Accent else Color.Transparent,
                                )
                                .clickable(enabled = !locked) { onToggle(cell) }
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun FeedbackCard(feedback: Feedback) {
    val tint = when {
        !feedback.verified -> MaterialTheme.colorScheme.onSurface
        feedback.correct == true -> Accent
        else -> MaterialTheme.colorScheme.error
    }
    Card(Modifier.fillMaxWidth()) {
        Row(
            Modifier.fillMaxWidth().padding(16.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column {
                Text(feedback.headline, fontWeight = FontWeight.SemiBold, color = tint)
                if (feedback.verified) {
                    Text(
                        "verification task",
                        fontSize = 11.sp,
                        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.55f),
                    )
                }
            }
            Text(
                if (feedback.reward > 0) "+%.4f".format(feedback.reward / 1_000_000.0) else "+0",
                fontFamily = FontFamily.Monospace,
                fontWeight = FontWeight.SemiBold,
                color = tint,
            )
        }
    }
}

@Composable
private fun Busy(label: String) {
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
        Spacer(Modifier.size(10.dp))
        Text(label, fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurface)
    }
}

@Composable
private fun ErrorCard(message: String, onDismiss: () -> Unit) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(message, color = MaterialTheme.colorScheme.error, fontSize = 13.sp)
            OutlinedButton(onClick = onDismiss) { Text("Dismiss") }
        }
    }
}

