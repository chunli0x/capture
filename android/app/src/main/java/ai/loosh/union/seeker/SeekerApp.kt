package ai.loosh.union.seeker

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.Preview
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.camera.video.FallbackStrategy
import androidx.camera.video.FileOutputOptions
import androidx.camera.video.Quality
import androidx.camera.video.QualitySelector
import androidx.camera.video.Recorder
import androidx.camera.video.Recording
import androidx.camera.video.VideoCapture
import androidx.camera.video.VideoRecordEvent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.animateContentSize
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.scaleIn
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.BorderStroke
import ai.loosh.union.CaptureOutline
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.media3.common.MediaItem
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.PlayerView
import com.solana.mobilewalletadapter.clientlib.ActivityResultSender
import java.io.File
import kotlinx.coroutines.delay
import org.json.JSONObject
import ai.loosh.union.*
import ai.loosh.union.LivenessScreen
import ai.loosh.union.MutedGray
import ai.loosh.union.WarnAmber
import ai.loosh.union.CaptureBase
import ai.loosh.union.CaptureRadii

@Composable
fun SeekerApp(sender: ActivityResultSender, vm: SeekerViewModel = viewModel()) {
    val s by vm.state.collectAsState()
    var server by remember(s.server) { mutableStateOf(s.server) }
    var creating by remember { mutableStateOf(false) }
    var onboarded by remember { mutableStateOf(vm.onboarded()) }
    var tutorialDone by remember { mutableStateOf(vm.tutorialDone()) }
    var showGallery by remember { mutableStateOf(false) }
    var galleryReason by remember { mutableStateOf<String?>(null) }
    var showLevel by remember { mutableStateOf(false) }
    var showProfile by remember { mutableStateOf(false) }
    var showReviewQueue by remember { mutableStateOf(false) }
    var captureKind by remember { mutableStateOf(KIND_OBJECT) }
    androidx.activity.compose.BackHandler(enabled = showProfile && s.selected == null) { showProfile = false }
    var previousLevel by remember { mutableIntStateOf(s.level) }
    var observedResult by remember { mutableStateOf(s.lastResult) }
    var celebrateLevel by remember { mutableStateOf<Int?>(null) }
    LaunchedEffect(s.level, s.lastResult) {
        val outcome = s.lastResult
        if (outcome != null && outcome !== observedResult && outcome.verdict?.accepted == true &&
            (outcome.levelAfter ?: previousLevel) > previousLevel) {
            celebrateLevel = outcome.levelAfter
        }
        previousLevel = s.level
        observedResult = outcome
    }
    var showLiveness by remember { mutableStateOf(false) }
    var pendingKind by remember { mutableStateOf<String?>(null) }
    var lastCaptureKind by remember { mutableStateOf(KIND_OBJECT) }
    LaunchedEffect(s.selected) { s.selected?.let { lastCaptureKind = bountyKind(it) } }
    val beginCapture: (String) -> Unit = { kind ->
        if (s.livenessVerified) vm.startOpenCapture(kind)
        else {
            pendingKind = kind
            showLiveness = true
            vm.startLiveness()
        }
    }

    if (!onboarded) {
        OnboardingScreen(onDone = {
            vm.setOnboarded()
            onboarded = true
        })
        return
    }
    if (!tutorialDone) {
        CaptureTutorialScreen(onDone = {
            vm.setTutorialDone()
            tutorialDone = true
        })
        return
    }

    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(s.transient, s.status) {
        if (s.status == AsyncStatus.Success && s.transient != null) {
            snackbar.showSnackbar(s.transient!!, duration = SnackbarDuration.Short)
            vm.dismissTransient()
        }
    }

    // Capture v2 liveness gate: prove human once per session before the first upload.
    if (showLiveness) {
        val challenge = s.livenessChallenge
        if (challenge == null) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    CircularProgressIndicator()
                    Text(s.message, style = MaterialTheme.typography.bodySmall, color = MutedGray)
                }
            }
        } else {
            LivenessScreen(
                challengeWire = challenge,
                busy = s.message.takeIf { s.busy },
                onPassed = { vm.completeLiveness(it) },
                onCancel = {
                    vm.cancelLiveness()
                    showLiveness = false
                    pendingKind = null
                },
            )
        }
        LaunchedEffect(s.livenessVerified, s.busy) {
            if (s.livenessVerified && !s.busy) {
                showLiveness = false
                val kind = pendingKind
                pendingKind = null
                if (kind != null) vm.startOpenCapture(kind)
            }
        }
        return
    }

    if (showGallery) {
        ExampleGalleryScreen(onBack = { showGallery = false }, reason = galleryReason)
        return
    }

    if (showLevel) {
        LevelScreen(s, onBack = { showLevel = false })
        return
    }

    if (showReviewQueue) {
        ReviewQueueScreen(s, vm, onBack = { showReviewQueue = false })
        return
    }

    // Capture v2 bond gate: a new user cannot submit their first upload until
    // they deposit the SKR bond or complete the free quality checks.
    if (s.wallet.isNotEmpty() && s.selected == null && !s.unlocked) {
        BondScreen(
            s = s,
            vm = vm,
            sender = sender,
            onReviewQueue = { showReviewQueue = true },
        )
        return
    }

    celebrateLevel?.let { level -> LevelUpOverlay(level) { celebrateLevel = null } }

    Scaffold(
        modifier = Modifier.fillMaxSize(),
        containerColor = Color.Transparent,
        snackbarHost = { SnackbarHost(snackbar) },
    ) { padding ->
        NavyBackground(Modifier.fillMaxSize().padding(padding)) {
            Column(Modifier.fillMaxSize().captureScreenMotion(s.selected?.optString("id"))) {
                CaptureHeader(s, onLevel = { showLevel = true })
                TestnetBanner()

                if (s.status == AsyncStatus.Working) {
                    LinearProgressIndicator(Modifier.fillMaxWidth())
                    Text(
                        s.message,
                        style = MaterialTheme.typography.labelSmall,
                        fontFamily = FontFamily.Monospace,
                        color = MutedGray,
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
                    )
                }

                s.error?.let { CaptureErrorCard(it, vm::dismissError) }

                val verdictContent: @Composable () -> Unit = {
                    s.lastResult?.let { result ->
                        androidx.compose.runtime.key(result) {
                            VerdictCard(result, vm::dismissVerdict, onGallery = {
                                galleryReason = result.verdict?.reason
                                showGallery = true
                            }, s = s, onCaptureAgain = {
                                vm.dismissVerdict()
                                beginCapture(lastCaptureKind)
                            })
                        }
                    }
                }
                Box(Modifier.fillMaxWidth().weight(1f)) {
                    if (s.wallet.isNotEmpty() && s.selected == null) {
                        CaptureHome(
                            s = s,
                            creating = creating,
                            onCreatingChange = { creating = it },
                            vm = vm,
                            sender = sender,
                            onCapture = beginCapture,
                            onGallery = { galleryReason = null; showGallery = true },
                            verdict = verdictContent,
                            profile = showProfile,
                            kind = captureKind,
                            onKindChange = { captureKind = it },
                            onLevel = { showLevel = true },
                            onProfile = { showProfile = true },
                        )
                    } else {
                        val scroll = rememberScrollState()
                        LaunchedEffect(s.selected?.optString("id")) { scroll.scrollTo(0) }
                        Column(Modifier.fillMaxSize().verticalScroll(scroll).padding(horizontal = 20.dp, vertical = 12.dp),
                            verticalArrangement = Arrangement.spacedBy(12.dp)) {
                            if (s.wallet.isEmpty()) {
                                WalletGate(
                                    busy = s.busy,
                                    error = s.error,
                                    onConnect = { over18 -> vm.connect(sender, over18) },
                                    onDismissError = vm::dismissError,
                                )
                            } else {
                                verdictContent()
                                if (s.busy && s.message.startsWith("Submitting labels")) JudgePendingScreen(s.image)
                                SelectedEditor(s, vm, sender)
                            }
                        }
                    }
                }
                if (s.selected == null && s.wallet.isNotEmpty()) {
                    Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                        FloatingBottomBar(showProfile, !s.busy,
                            onGallery = { galleryReason = null; showGallery = true },
                            onCapture = { showProfile = false; beginCapture(captureKind) },
                            onProfile = { showProfile = true })
                    }
                }
            }
        }
    }
}

@Composable
private fun CaptureHeader(s: PilotState, onLevel: () -> Unit) {
    Row(Modifier.fillMaxWidth().captureGlass().padding(horizontal = 20.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
        CaptureWordmark()
        LevelBadgeRing(s, onLevel)
    }
}

/** A persistent, unmissable testnet disclaimer pinned under the header. */
@Composable
private fun TestnetBanner() {
    Row(
        Modifier
            .fillMaxWidth()
            .background(CaptureSurface2)
            .border(1.dp, CaptureInk)
            .padding(horizontal = 16.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            "TESTNET",
            style = MaterialTheme.typography.labelLarge,
            color = CaptureInk,
            textAlign = TextAlign.Center,
        )
    }
}

@Composable
private fun CaptureErrorCard(message: String, onDismiss: () -> Unit) {
    Card(
        Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 4.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.error.copy(alpha = 0.12f)),
    ) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(
                message,
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodySmall,
            )
            TextButton(onClick = onDismiss, modifier = Modifier.align(Alignment.End)) {
                Text("Dismiss", color = MaterialTheme.colorScheme.error)
            }
        }
    }
}

@Composable
private fun SectionHeader(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.headlineSmall,
        color = MaterialTheme.colorScheme.onBackground,
    )
}

@Composable
private fun EmptyState(title: String, subtitle: String) {
    AnimatedVisibility(
        visible = true,
        enter = fadeIn() + scaleIn(initialScale = 0.9f),
    ) {
        Column(
            Modifier
                .fillMaxWidth()
                .padding(vertical = 24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            BrandLogo(Modifier.size(28.dp))
            Text(
                title,
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                subtitle,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                textAlign = TextAlign.Center,
            )
        }
    }
}

@Composable
private fun WalletGate(
    busy: Boolean,
    error: String?,
    onConnect: (Boolean) -> Unit,
    onDismissError: () -> Unit,
) {
    var over18 by remember { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
        EditorialHeading("SIGN IN.")
        Text(
            "Capture objects, scenes, or actions, label them by hand, and review each submission independently.",
            style = MaterialTheme.typography.bodyMedium,
            color = CaptureInk,
        )
        if (error != null) {
            Row(
                Modifier.fillMaxWidth().background(ErrorRedBg, CaptureRadii.md).border(1.dp, ErrorRed, CaptureRadii.md).padding(horizontal = 14.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("!", style = MaterialTheme.typography.titleMedium, color = ErrorRed, modifier = Modifier.padding(end = 10.dp))
                Text(error, style = MaterialTheme.typography.bodyMedium, color = ErrorRed, modifier = Modifier.weight(1f))
                TextButton(onClick = onDismissError) { Text("Dismiss", color = ErrorRed) }
            }
        }
        Row(
            Modifier.fillMaxWidth().background(WarnAmberBg, CaptureRadii.md).padding(horizontal = 14.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(Modifier.size(20.dp).border(1.dp, WarnAmber, CircleShape), contentAlignment = Alignment.Center) {
                Text("i", style = MaterialTheme.typography.labelSmall, color = WarnAmber)
            }
            Spacer(Modifier.width(10.dp))
            Text(
                "Approved captures are paid in TEST-USDC (devnet). Bonded uploads are auto-judged; free uploads are peer-reviewed.",
                style = MaterialTheme.typography.bodySmall,
                color = WarnAmber,
            )
        }
        Row(
            Modifier.fillMaxWidth().background(CaptureSurface2, CaptureRadii.md).border(1.dp, CaptureOutline, CaptureRadii.md).padding(horizontal = 14.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Checkbox(checked = over18, onCheckedChange = { over18 = it }, enabled = !busy)
            Text("I confirm I am 18 or older", style = MaterialTheme.typography.bodyMedium, color = CaptureInk)
        }
        Text(
            "Designed for the Solana Seeker Mobile",
            style = MaterialTheme.typography.bodyMedium,
            color = CaptureInk,
        )
        Button(
            onClick = { onConnect(over18) },
            enabled = !busy && over18,
            modifier = Modifier.fillMaxWidth().height(52.dp),
            colors = ButtonDefaults.buttonColors(containerColor = CaptureAction, contentColor = Color.White, disabledContainerColor = ButtonGrey, disabledContentColor = ButtonGreyInk),
            shape = CaptureRadii.pill,
        ) {
            Text("Sign in with Seeker Wallet", style = MaterialTheme.typography.titleMedium)
        }
    }
}

@Composable
private fun WalletActions(s: PilotState, vm: SeekerViewModel) {
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        OutlinedButton(onClick = { vm.refresh() }, enabled = !s.busy, modifier = Modifier.weight(1f)) {
            Text("Refresh")
        }
        TextButton(onClick = { vm.logout() }, enabled = !s.busy) { Text("Sign out") }
    }
}

@Composable
private fun SelectedEditor(s: PilotState, vm: SeekerViewModel, sender: ActivityResultSender) {
    val selected = s.selected ?: return
    val kind = bountyKind(selected)
    TextButton(onClick = { vm.close() }, enabled = !s.busy) { Text("\u2190 BACK TO CAPTURE") }
    Text(
        if (selected.isNull("bounty")) "Open capture" else selected.getJSONObject("bounty").getString("title"),
        style = MaterialTheme.typography.titleLarge,
        color = MaterialTheme.colorScheme.onBackground,
    )
    Text(
        when {
            s.reviewing -> "Independent review: label this capture without seeing other labels."
            kind == "action" -> "Record one action clip (\u2264 30 s), then choose a tag and trim. Avoid people and private information."
            else -> "Capture only objects or scenes you have permission to share. Avoid people and private information."
        },
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
    )
    val editable =
        s.reviewing ||
            (selected.getString("worker") == s.wallet &&
                selected.getString("status") == "claimed")
    val canCapture =
        s.image == null &&
            s.videoDurationMs == null &&
            selected.isNull("media_hash") &&
            selected.getString("worker") == s.wallet
    when (kind) {
        "action" ->
            if (canCapture) {
                CaptureVideo(!s.busy) { data, durationMs -> vm.capture(selected.getString("id"), data, durationMs) }
            } else if (s.videoDurationMs != null) {
                ActionEditor(s, editable, !s.busy, vm::submitAction)
            } else {
                Text("Action clip already captured.")
            }
        "place" ->
            if (canCapture) {
                CapturePhoto(!s.busy) { data -> vm.capture(selected.getString("id"), data) }
            } else if (s.image != null) {
                PlaceEditor(s, editable, !s.busy, vm::submitPlace)
            }
        else ->
            if (canCapture) {
                CapturePhoto(!s.busy) { data -> vm.capture(selected.getString("id"), data) }
            } else if (s.image != null) {
                PhotoEditor(s, editable, !s.busy, vm::submit)
            }
    }
}

@Composable
private fun CaptureHome(
    s: PilotState,
    creating: Boolean,
    onCreatingChange: (Boolean) -> Unit,
    vm: SeekerViewModel,
    sender: ActivityResultSender,
    onCapture: (String) -> Unit,
    onGallery: () -> Unit,
    verdict: @Composable () -> Unit,
    profile: Boolean,
    kind: String,
    onKindChange: (String) -> Unit,
    onLevel: () -> Unit,
    onProfile: () -> Unit,
) {
    val list = rememberLazyListState()
    LaunchedEffect(s.lastResult, profile) { list.scrollToItem(0) }
    LazyColumn(Modifier.fillMaxSize(), state = list, contentPadding = PaddingValues(horizontal = 20.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)) {
        if (s.lastResult != null) item(key = "verdict") { Column(verticalArrangement = Arrangement.spacedBy(12.dp)) { verdict() } }
        if (profile) {
            item(key = "profile") {
                Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
                    Text("Profile", style = MaterialTheme.typography.displaySmall)
                    Text("${s.wallet.take(6)}…${s.wallet.takeLast(4)}", style = MaterialTheme.typography.bodySmall, color = MutedGray)
                    LevelCard(s)
                    MetricTiles(s)
                    RateTicker(s)
                    SettleEarnings(s, vm)
                    Text("DEVNET · TEST-SKR REWARDS · TEST-SKR BOND", style = MaterialTheme.typography.labelSmall, color = MutedGray)
                    WalletActions(s, vm)
                    CapturePanel(Modifier.fillMaxWidth()) {
                        Text("Albums and teams", style = MaterialTheme.typography.titleLarge)
                        ComingSoonBadge()
                        Text("Album collections and team participation are planned for a future release.",
                            style = MaterialTheme.typography.bodyMedium, color = CaptureInk)
                    }
                    CapturePanel(Modifier.fillMaxWidth()) {
                        Text("Leaderboard", style = MaterialTheme.typography.titleLarge)
                        ComingSoonBadge()
                        Text("Increase your payout bonus", style = MaterialTheme.typography.titleMedium)
                        Text("Rankings and leaderboard rewards are planned for a future release.",
                            style = MaterialTheme.typography.bodyMedium, color = CaptureInk)
                    }
                    Dashboard(s, creating, onCreatingChange, vm, sender)
                }
            }
        } else {
            item(key = "stats") {
                Row(Modifier.fillMaxWidth().captureCardMotion(0), horizontalArrangement = Arrangement.SpaceEvenly) {
                    StatPill(CaptureSymbol.RING, "L${s.level}", "Level ${s.level}", onLevel)
                    StatPill(CaptureSymbol.BOLT, "×${String.format(java.util.Locale.US, "%.2f", s.rateMultiplier)}", "Rate multiplier", onLevel)
                    // The pinned contract has no streak field; never invent a count.
                    StatPill(CaptureSymbol.STREAK, "—", "Streak unavailable", onProfile)
                }
            }
            item(key = "capture") {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    CaptureButton(enabled = !s.busy, onCapture = { onCapture(kind) }, onGallery = onGallery)
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        listOf(Triple(KIND_OBJECT, CaptureSymbol.OBJECT, "Object photo"),
                            Triple(KIND_PLACE, CaptureSymbol.PLACE, "Place photo"),
                            Triple(KIND_ACTION, CaptureSymbol.VIDEO, "Action clip")).forEach { (value, icon, label) ->
                            IconButton(onClick = { onKindChange(value) }, enabled = !s.busy,
                                modifier = Modifier.semantics { selected = kind == value }.background(if (kind == value) CaptureAccentTint else CaptureSurface, CaptureRadii.pill)) {
                                CaptureIcon(icon, Modifier.size(22.dp), if (kind == value) CaptureAccent else MutedGray, label)
                            }
                        }
                    }
                }
            }
            item(key = "rank") { ProgressRingCard(s, onLevel) }
        }
    }
}

@Composable
private fun SettleEarnings(s: PilotState, vm: SeekerViewModel) {
    CapturePanel(Modifier.fillMaxWidth(), elevated = true) {
        Text("ACCRUED EARNINGS", style = MaterialTheme.typography.labelMedium, color = MutedGray)
        Text(
            String.format(java.util.Locale.US, "%.2f TEST-USDC", s.pendingUsdc / 1_000_000.0),
            style = CaptureNumeric,
            color = CaptureAccent,
        )
        Text(
            "Accepted uploads accrue here. Settling sends the balance to your wallet in one transfer.",
            style = MaterialTheme.typography.bodySmall,
            color = MutedGray,
        )
        Button(
            onClick = { vm.settle() },
            enabled = !s.busy && s.pendingUsdc > 0,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text("Settle to wallet")
        }
    }
}

@Composable
private fun Dashboard(
    s: PilotState,
    creating: Boolean,
    onCreatingChange: (Boolean) -> Unit,
    vm: SeekerViewModel,
    sender: ActivityResultSender,
) {
    if (s.worker) {
        Card(Modifier.fillMaxWidth(), border = BorderStroke(1.dp, CaptureOutline)) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("WORKER BOND", style = MaterialTheme.typography.labelSmall, color = CaptureAccent)
                Text(
                    "${s.bond} TEST-SKR base units. Locked while any fulfillment is pending; 24-hour cooldown after a deposit.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { vm.transact("/bond/deposit", sender) }, enabled = !s.busy) {
                        Text("Deposit bond")
                    }
                    OutlinedButton(onClick = { vm.transact("/bond/withdraw", sender) }, enabled = !s.busy) {
                        Text("Withdraw")
                    }
                }
            }
        }
    } else {
        Card(Modifier.fillMaxWidth(), border = BorderStroke(1.dp, CaptureOutline)) {
            Text(
                "Ask the operator to enroll this wallet before capturing or reviewing.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
                modifier = Modifier.padding(16.dp),
            )
        }
    }

    Button(onClick = { onCreatingChange(!creating) }, enabled = !s.busy, modifier = Modifier.fillMaxWidth()) {
        Text(if (creating) "Close new bounty" else "Create bounty")
    }
    if (creating) CreateBountyForm(s.taxonomy, s.busy, vm::create)

    SectionHeader("Bounties")
    if (s.bounties.isEmpty()) {
        EmptyState("No open bounties yet", "Check back soon — new bounties appear here.")
    }
    s.bounties.forEach { b ->
        Card(Modifier.fillMaxWidth(), border = BorderStroke(1.dp, CaptureOutline)) {
            Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(b.getString("title"), style = MaterialTheme.typography.titleMedium)
                Text(
                    "${b.getLong("reward_usdc_units") / 1_000_000.0} TEST-USDC per accepted ${rewardNoun(b.optString("kind", KIND_OBJECT))} \u00b7 ${b.getInt("slots")} slots \u00b7 ${b.getString("status")}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
                )
                Text(
                    "Funding total: ${b.getLong("reward_usdc_units") * b.getInt("slots") / 1_000_000.0} TEST-USDC. Pilot fee: 0.",
                    style = MaterialTheme.typography.bodySmall,
                    fontFamily = FontFamily.Monospace,
                    color = CaptureAccentBright,
                )
                val mine = b.getString("requester") == s.wallet
                val id = b.getString("id")
                if (mine && b.getString("status") == "draft")
                    Button(
                        onClick = { vm.transact("/bounties/$id/fund", sender) },
                        enabled = !s.busy,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text("Fund escrow")
                    }
                if (
                    !mine &&
                        s.worker &&
                        b.getString("status") == "open" &&
                        b.getLong("deadline") > System.currentTimeMillis() / 1000
                )
                    Button(
                        onClick = { vm.claim(id) },
                        enabled = !s.busy,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text("Claim a slot")
                    }
                if (
                    mine &&
                        b.getString("status") != "draft" &&
                        b.getLong("deadline") <= System.currentTimeMillis() / 1000
                )
                    OutlinedButton(
                        onClick = { vm.transact("/bounties/$id/refund", sender) },
                        enabled = !s.busy,
                    ) {
                        Text("Refund available escrow")
                    }
            }
        }
    }

    SectionHeader("Your submissions and requests")
    if (s.submissions.isEmpty()) {
        EmptyState("No submissions yet", "Claim a bounty and capture to get started.")
    }
    s.submissions.forEach { sub ->
        Card(Modifier.fillMaxWidth(), border = BorderStroke(1.dp, CaptureOutline)) {
            Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                // Open uploads have no bounty (bounty_id is NULL); render a
                // fallback title instead of dereferencing a missing object.
                val title = if (sub.isNull("bounty")) "Open capture" else sub.getJSONObject("bounty").getString("title")
                Text(title, style = MaterialTheme.typography.titleMedium)
                val status = sub.getString("status")
                val id = sub.getString("id")
                Text(
                    "Status: $status",
                    style = MaterialTheme.typography.bodySmall,
                    color = if (status == "eligible") CaptureAccent else MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
                )
                OutlinedButton(onClick = { vm.open(sub, false) }, enabled = !s.busy) {
                    Text(if (sub.isNull("media_hash")) "Capture" else "Open submission and labels")
                }
                if (status == "eligible" && sub.getString("worker") == s.wallet)
                    Button(
                        onClick = { vm.transact("/submissions/$id/fulfill", sender) },
                        enabled = !s.busy,
                    ) {
                        Text("Register eligible work")
                    }
                if (
                    status == "registered" &&
                        sub.getJSONObject("bounty").getString("requester") == s.wallet
                ) {
                    Button(
                        onClick = { vm.transact("/submissions/$id/accept", sender) },
                        enabled = !s.busy,
                    ) {
                        Text("Accept and pay")
                    }
                    OutlinedButton(
                        onClick = { vm.transact("/submissions/$id/reject", sender) },
                        enabled = !s.busy,
                    ) {
                        Text("Reject without payment")
                    }
                }
                if (
                    status == "registered" &&
                        sub.getJSONObject("bounty").getLong("deadline") <=
                            System.currentTimeMillis() / 1000
                )
                    OutlinedButton(
                        onClick = { vm.transact("/submissions/$id/expire", sender) },
                        enabled = !s.busy,
                    ) {
                        Text("Expire and unlock bond")
                    }
            }
        }
    }

    if (s.reviewer) {
        SectionHeader("Independent reviews")
        Text(
            "Pilot reviews are unpaid. Two distinct agreeing reviews establish eligibility; they do not release money.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
        )
        if (s.reviews.isEmpty()) {
            EmptyState("No reviews to do right now", "Check back later.")
        }
        s.reviews.forEach { sub ->
            OutlinedButton(
                onClick = { vm.open(sub, true) },
                enabled = !s.busy,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text("Review: ${sub.getJSONObject("bounty").getString("title")}")
            }
        }
    }

    val pending = s.transactions.filter { !it.getBoolean("confirmed") }
    if (pending.isNotEmpty()) {
        SectionHeader("Transaction recovery")
        Text(
            "If your wallet sent a transaction but the app did not record confirmation, recover it here. An unsigned or canceled transaction has no payment effect.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
        )
        pending.take(10).forEach { tx ->
            Card(Modifier.fillMaxWidth(), border = BorderStroke(1.dp, CaptureOutline)) {
                Row(
                    Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 12.dp, vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Box(
                        Modifier
                            .size(8.dp)
                            .background(WarnAmber, CircleShape),
                    )
                    OutlinedButton(
                        onClick = { vm.recover(tx.getString("id")) },
                        enabled = !s.busy,
                        modifier = Modifier.weight(1f),
                    ) {
                        Text("Recover ${tx.getString("action")} \u00b7 ${tx.getString("id").take(6)}")
                    }
                }
            }
        }
    }
}

@Composable
private fun CreateBountyForm(
    taxonomy: List<TaxonomyCategory>,
    busy: Boolean,
    create: (String, List<Int>, String, String, String, String) -> Unit,
) {
    var title by remember { mutableStateOf("") }
    var reward by remember { mutableStateOf("1") }
    var slots by remember { mutableStateOf("1") }
    var hours by remember { mutableStateOf("24") }
    var kind by remember { mutableStateOf(KIND_OBJECT) }
    var selectedIds by remember { mutableStateOf(setOf<Int>()) }
    OutlinedTextField(title, { title = it }, label = { Text("Bounty title") }, modifier = Modifier.fillMaxWidth())
    Text("Kind", style = MaterialTheme.typography.labelLarge)
    LabelChipFlow {
        LabelChip("Object", kind == KIND_OBJECT, CaptureAccent, glyph = ChipGlyph.CHECK) {
            kind = KIND_OBJECT
            selectedIds = emptySet()
        }
        LabelChip("Place", kind == KIND_PLACE, CaptureAccent, glyph = ChipGlyph.CHECK) {
            kind = KIND_PLACE
            selectedIds = emptySet()
        }
        LabelChip("Action", kind == KIND_ACTION, CaptureAccent, glyph = ChipGlyph.CHECK) {
            kind = KIND_ACTION
            selectedIds = emptySet()
        }
    }
    Text("Categories", style = MaterialTheme.typography.labelLarge)
    val available = categoriesForKind(taxonomy, kind)
    if (available.isEmpty()) {
        Text(
            "No $kind categories in the registry yet.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
        )
    } else {
        LabelChipFlow {
            available.forEach { c ->
                LabelChip(
                    c.name,
                    c.id in selectedIds,
                    CaptureAccent,
                    enabled = !busy,
                    glyph = ChipGlyph.CHECK,
                ) {
                    selectedIds =
                        if (c.id in selectedIds) selectedIds - c.id else selectedIds + c.id
                }
            }
        }
    }
    OutlinedTextField(reward, { reward = it }, label = { Text("TEST-USDC per accepted submission") }, modifier = Modifier.fillMaxWidth())
    OutlinedTextField(slots, { slots = it }, label = { Text("Payable slots (1\u2013100)") }, modifier = Modifier.fillMaxWidth())
    OutlinedTextField(hours, { hours = it }, label = { Text("Deadline in hours (1\u2013720)") }, modifier = Modifier.fillMaxWidth())
    Button(
        onClick = { create(title, selectedIds.toList(), reward, slots, hours, kind) },
        enabled = !busy && title.isNotBlank() && selectedIds.isNotEmpty(),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Text("Save draft")
    }
}

@Composable
private fun PhotoEditor(
    s: PilotState,
    editable: Boolean,
    enabled: Boolean,
    submit: (List<LabelBox>, SecondarySelection) -> Unit,
) {
    val bitmap = s.image ?: return
    val selected = s.selected ?: return
    val categories = selected.getJSONObject("bounty").getJSONArray("categories")
    var category by
        remember(selected, s.reviewing) {
            mutableIntStateOf(categories.getJSONObject(0).getInt("id"))
        }
    var boxes by
        remember(selected, s.reviewing) {
            mutableStateOf(
                if (s.reviewing || selected.isNull("boxes")) emptyList()
                else
                    selected.getJSONArray("boxes").let { array ->
                        (0 until array.length()).map {
                            val b = array.getJSONObject(it)
                            LabelBox(
                                b.getInt("category_id"),
                                b.getDouble("x").toFloat(),
                                b.getDouble("y").toFloat(),
                                b.getDouble("w").toFloat(),
                                b.getDouble("h").toFloat(),
                            )
                        }
                    }
            )
        }
    var start by remember { mutableStateOf<Offset?>(null) }
    var end by remember { mutableStateOf<Offset?>(null) }
    var selectedBox by remember { mutableStateOf<Int?>(null) }
    var secondary by remember(selected, s.reviewing) { mutableStateOf(SecondarySelection()) }

    if (editable) {
        Text(
            "Choose one object, then drag a box over each instance.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
        )
        LabelChipFlow {
            for (i in 0 until categories.length()) {
                val c = categories.getJSONObject(i)
                LabelChip(
                    c.getString("name"),
                    category == c.getInt("id"),
                    CaptureAccent,
                    enabled = enabled,
                    glyph = ChipGlyph.CHECK,
                ) { category = c.getInt("id") }
            }
        }
        SecondaryPicker(s.taxonomy, secondary, enabled) { secondary = it }
    }

    Box(
        Modifier
            .fillMaxWidth()
            .aspectRatio(bitmap.width.toFloat() / bitmap.height)
            .clip(CaptureRadii.md)
            .background(MaterialTheme.colorScheme.surface),
    ) {
        Image(bitmap.asImageBitmap(), "Approved object photo", Modifier.fillMaxSize())
        Canvas(
            Modifier
                .fillMaxSize()
                .pointerInput(editable, enabled, category, boxes, selectedBox) {
                    if (editable && enabled) {
                        detectTapGestures { tap ->
                            val tx = tap.x / size.width
                            val ty = tap.y / size.height
                            selectedBox = boxes.indices.reversed().firstOrNull { i ->
                                val b = boxes[i]
                                tx >= b.x && tx <= b.x + b.w && ty >= b.y && ty <= b.y + b.h
                            }
                        }
                    }
                }
                .pointerInput(editable, enabled, category) {
                    if (editable && enabled)
                        detectDragGestures(
                            onDragStart = {
                                start = Offset(it.x / size.width, it.y / size.height)
                                end = start
                            },
                            onDragEnd = {
                                val a = start
                                val b = end
                                if (a != null && b != null && boxes.size < 100)
                                    dragBox(category, a.x, a.y, b.x, b.y)?.let { boxes = boxes + it }
                                start = null
                                end = null
                            },
                            onDragCancel = {
                                start = null
                                end = null
                            },
                            onDrag = { change, _ ->
                                change.consume()
                                end =
                                    Offset(
                                        change.position.x / size.width,
                                        change.position.y / size.height,
                                    )
                            },
                        )
                },
        ) {
            val preview =
                if (start != null && end != null)
                    dragBox(category, start!!.x, start!!.y, end!!.x, end!!.y)
                else null
            (boxes + listOfNotNull(preview)).forEachIndexed { index, b ->
                val isPreview = index == boxes.size
                val isSelected = index == selectedBox && !isPreview
                val color =
                    when {
                        isPreview -> CaptureAccent.copy(alpha = 0.6f)
                        isSelected -> CaptureAccent
                        else -> CaptureAccent
                    }
                drawRect(
                    color,
                    Offset(b.x * size.width, b.y * size.height),
                    Size(b.w * size.width, b.h * size.height),
                    style = Stroke(if (isSelected) 4.dp.toPx() else 3.dp.toPx()),
                )
                if (isSelected || isPreview) {
                    drawCircle(CaptureAccent, 3.dp.toPx(), Offset(b.x * size.width, b.y * size.height))
                }
            }
        }
        // Centered empty-state helper overlaid on the image.
        if (boxes.isEmpty()) {
            Text(
                "Drag to draw a box around each object",
                style = MaterialTheme.typography.labelMedium,
                color = CaptureAccentBright,
                modifier = Modifier
                    .align(Alignment.Center)
                    .background(MaterialTheme.colorScheme.background.copy(alpha = 0.6f), RoundedCornerShape(8.dp))
                    .padding(horizontal = 12.dp, vertical = 6.dp),
            )
        }
    }

    // Box count badge in the editor header, not a floating Text.
    Text(
        "${boxes.size} boxes",
        style = MaterialTheme.typography.labelMedium,
        color = CaptureAccentBright,
    )
    boxes.forEachIndexed { index, b ->
        Text(
            "${index + 1}: category ${b.categoryId}, x=${"%.2f".format(b.x)}, y=${"%.2f".format(b.y)}, width=${"%.2f".format(b.w)}, height=${"%.2f".format(b.h)}",
            style = MaterialTheme.typography.bodySmall,
            fontFamily = FontFamily.Monospace,
            color = if (index == selectedBox) CaptureAccent else MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
        )
    }
    if (editable) {
        var coordinates by remember { mutableStateOf("0.1, 0.1, 0.5, 0.5") }
        var inputError by remember { mutableStateOf<String?>(null) }
        var showCoords by remember { mutableStateOf(false) }
        TextButton(onClick = { showCoords = !showCoords }) {
            Text(if (showCoords) "Hide coordinates" else "Add by coordinates")
        }
        if (showCoords) {
            OutlinedTextField(
                coordinates,
                { coordinates = it },
                label = { Text("x, y, width, height (0\u20131)") },
                modifier = Modifier.fillMaxWidth(),
                isError = inputError != null,
            )
            inputError?.let {
                Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(
                    onClick = {
                        val v = coordinates.split(',').mapNotNull { it.trim().toFloatOrNull() }
                        val box =
                            if (
                                v.size == 4 &&
                                    v.all { it.isFinite() && it in 0f..1f } &&
                                    v[0] + v[2] <= 1 &&
                                    v[1] + v[3] <= 1
                            )
                                dragBox(category, v[0], v[1], v[0] + v[2], v[1] + v[3])
                            else null
                        if (box != null && boxes.size < 100) {
                            boxes = boxes + box
                            inputError = null
                        } else inputError = "Enter a nonempty box within the image."
                    },
                    enabled = enabled,
                ) {
                    Text("Add coordinate box")
                }
                OutlinedButton(
                    onClick = {
                        boxes = boxes.dropLast(1)
                        selectedBox = null
                    },
                    enabled = enabled && boxes.isNotEmpty(),
                ) {
                    Text("Undo last box")
                }
            }
            if (selectedBox != null && selectedBox!! < boxes.size) {
                TextButton(onClick = {
                    boxes = boxes.filterIndexed { i, _ -> i != selectedBox }
                    selectedBox = null
                }) {
                    Text("Delete selected box \u2715", color = CaptureAccent)
                }
            }
        }
        Button(
            onClick = { submit(boxes, secondary) },
            enabled = enabled && boxes.isNotEmpty() && secondary.postures.isNotEmpty(),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text(if (s.reviewing) "Submit independent review" else "Submit immutable labels")
        }
    }
}

@Composable
private fun CapturePhoto(enabled: Boolean, onPhoto: (ByteArray) -> Unit) {
    val context = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current
    var permission by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
                PackageManager.PERMISSION_GRANTED
        )
    }
    val request =
        rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
            permission = it
        }
    var capture by remember { mutableStateOf<ImageCapture?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var capturing by remember { mutableStateOf(false) }
    var pending by remember { mutableStateOf<ByteArray?>(null) }
    val previewView = remember { PreviewView(context) }
    val live = remember { java.util.concurrent.atomic.AtomicBoolean(true) }
    DisposableEffect(Unit) {
        live.set(true)
        onDispose { live.set(false) }
    }
    if (!permission) {
        Card(Modifier.fillMaxWidth(), border = BorderStroke(1.dp, CaptureOutline)) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(
                    "The camera is used once, to capture the object or scene you're labeling. Nothing is analyzed on device beyond this capture.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
                )
                Button(
                    onClick = { request.launch(Manifest.permission.CAMERA) },
                    enabled = enabled,
                    modifier = Modifier.fillMaxWidth(),
                ) { Text("Allow camera") }
            }
        }
        return
    }
    DisposableEffect(lifecycle, previewView) {
        val future = ProcessCameraProvider.getInstance(context)
        var provider: ProcessCameraProvider? = null
        var disposed = false
        val executor = ContextCompat.getMainExecutor(context)
        future.addListener(
            {
                if (!disposed)
                    try {
                        provider = future.get()
                        previewView.scaleType = PreviewView.ScaleType.FILL_CENTER
                        val preview =
                            Preview.Builder().build().also {
                                it.surfaceProvider = previewView.surfaceProvider
                            }
                        val camera =
                            ImageCapture.Builder()
                                .setResolutionSelector(
                                    ResolutionSelector.Builder()
                                        .setResolutionStrategy(
                                            ResolutionStrategy(
                                                android.util.Size(1600, 1200),
                                                ResolutionStrategy
                                                    .FALLBACK_RULE_CLOSEST_LOWER_THEN_HIGHER,
                                            )
                                        )
                                        .build()
                                )
                                .build()
                        provider?.bindToLifecycle(
                            lifecycle,
                            CameraSelector.DEFAULT_BACK_CAMERA,
                            preview,
                            camera,
                        )
                        capture = camera
                    } catch (e: Exception) {
                        error = e.message ?: "Camera unavailable"
                    }
            },
            executor,
        )
        onDispose {
            disposed = true
            provider?.unbindAll()
            capture = null
        }
    }

    if (pending != null) {
        ConfirmationStrip(
            onRetake = { pending = null },
            onUse = { onPhoto(pending!!); pending = null },
        )
        return
    }

    Box(
        Modifier
            .fillMaxWidth()
            .aspectRatio(3f / 4f)
            .clip(CaptureRadii.md)
            .background(CaptureBase),
    ) {
        AndroidView(factory = { previewView }, modifier = Modifier.fillMaxSize())
        ViewfinderGrid(Modifier.fillMaxSize())
        LowAngleGuidance(Modifier.align(Alignment.TopCenter))
        if (capturing) {
            Box(
                Modifier
                    .fillMaxSize()
                    .background(CaptureInk.copy(alpha = 0.25f)),
            )
        }
        ShutterButton(
            enabled = enabled && capture != null && !capturing,
            modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 24.dp),
            onClick = {
                val camera = capture
                if (camera != null) {
                    capturing = true
                    val file = File.createTempFile("seeker-capture-", ".jpg", context.cacheDir)
                    camera.takePicture(
                        ImageCapture.OutputFileOptions.Builder(file).build(),
                        ContextCompat.getMainExecutor(context),
                        object : ImageCapture.OnImageSavedCallback {
                            override fun onImageSaved(output: ImageCapture.OutputFileResults) {
                                try {
                                    if (live.get()) pending = file.readBytes()
                                } finally {
                                    file.delete()
                                    capturing = false
                                }
                            }

                            override fun onError(exc: ImageCaptureException) {
                                file.delete()
                                capturing = false
                                error = exc.message
                            }
                        },
                    )
                }
            },
        )
    }
    error?.let { CaptureErrorCard(it) { error = null } }
}

/** The bounty kind governing a submission's media + label shape (`object|place|action`). */
private fun bountyKind(selected: JSONObject): String =
    if (selected.has("kind")) selected.getString("kind")
    else selected.optJSONObject("bounty")?.optString("kind", "object") ?: "object"

/** Kind-aware noun for reward copy; object keeps the phase-1 "photo", others go neutral. */
private fun rewardNoun(kind: String): String =
    if (kind == KIND_OBJECT) "photo" else "submission"

@Composable
private fun PlaceEditor(
    s: PilotState,
    editable: Boolean,
    enabled: Boolean,
    submit: (Int, SecondarySelection) -> Unit,
) {
    val bitmap = s.image ?: return
    val selected = s.selected ?: return
    val categories = selected.getJSONObject("bounty").getJSONArray("categories")
    val existing = selected.optJSONObject("scene")
    var category by
        remember(selected, s.reviewing) {
            mutableIntStateOf(
                existing?.optInt("category_id", -1)?.takeIf { it >= 0 }
                    ?: categories.getJSONObject(0).getInt("id")
            )
        }
    Image(
        bitmap.asImageBitmap(),
        "Approved place photo",
        Modifier
            .fillMaxWidth()
            .aspectRatio(bitmap.width.toFloat() / bitmap.height)
            .clip(CaptureRadii.md),
    )
    PickerHelper("Choose the single scene class")
    LabelChipFlow {
        for (i in 0 until categories.length()) {
            val c = categories.getJSONObject(i)
            LabelChip(
                c.getString("name"),
                category == c.getInt("id"),
                CaptureAccent,
                enabled = enabled && editable,
                glyph = ChipGlyph.CHECK,
            ) { category = c.getInt("id") }
        }
    }
    var secondary by remember(selected, s.reviewing) { mutableStateOf(SecondarySelection()) }
    if (editable) {
        SecondaryPicker(s.taxonomy, secondary, enabled) { secondary = it }
        Button(onClick = { submit(category, secondary) }, enabled = enabled && secondary.postures.isNotEmpty(), modifier = Modifier.fillMaxWidth()) {
            Text(if (s.reviewing) "Submit independent review" else "Submit immutable label")
        }
    }
}

@Composable
private fun ActionEditor(
    s: PilotState,
    editable: Boolean,
    enabled: Boolean,
    submit: (Int, TrimRange, SecondarySelection) -> Unit,
) {
    val selected = s.selected ?: return
    val durationMs = s.videoDurationMs ?: return
    val categories = selected.getJSONObject("bounty").getJSONArray("categories")
    val existing = actionLabelOf(selected)
    var category by
        remember(selected, s.reviewing) {
            mutableIntStateOf(
                existing?.categoryId?.takeIf { it >= 0 }
                    ?: categories.getJSONObject(0).getInt("id")
            )
        }
    var startMs by
        remember(selected, s.reviewing) {
            mutableIntStateOf(existing?.startMs ?: 0)
        }
    var endMs by
        remember(selected, s.reviewing, durationMs) {
            mutableIntStateOf(existing?.endMs ?: durationMs)
        }
    if (durationMs < 2) {
        Text("Clip is too short to trim.", color = MaterialTheme.colorScheme.error)
        return
    }
    val videoUri = s.videoUri
    if (videoUri == null) {
        Text("Loading approved video\u2026")
        return
    }
    val context = LocalContext.current
    val player =
        remember(videoUri) {
            ExoPlayer.Builder(context).build().apply {
                setMediaItem(MediaItem.fromUri(videoUri))
                prepare()
                playWhenReady = false
            }
        }
    DisposableEffect(player) { onDispose { player.release() } }
    // Pin the preview to the trim start on first show, then follow the sliders.
    LaunchedEffect(player) { player.seekTo(startMs.toLong()) }
    AndroidView(
        factory = { ctx -> PlayerView(ctx).apply { this.player = player; useController = false } },
        modifier = Modifier
            .fillMaxWidth()
            .height(240.dp)
            .clip(CaptureRadii.md),
    )
    Text(
        "Clip length $durationMs ms. Choose one action tag, then set the trim.",
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
    )
    PickerHelper("Choose the single action tag")
    LabelChipFlow {
        for (i in 0 until categories.length()) {
            val c = categories.getJSONObject(i)
            LabelChip(
                c.getString("name"),
                category == c.getInt("id"),
                CaptureAccent,
                enabled = enabled && editable,
                glyph = ChipGlyph.CHECK,
            ) { category = c.getInt("id") }
        }
    }
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text("Start", style = MaterialTheme.typography.labelSmall, color = MutedGray)
        Text("$startMs ms", style = MaterialTheme.typography.labelSmall, fontFamily = FontFamily.Monospace, color = CaptureAccent)
    }
    Slider(
        value = startMs.toFloat(),
        onValueChange = {
            startMs = it.toInt().coerceIn(0, endMs - 1)
            player.seekTo(startMs.toLong())
        },
        valueRange = 0f..durationMs.toFloat(),
        enabled = enabled && editable,
    )
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text("End", style = MaterialTheme.typography.labelSmall, color = MutedGray)
        Text("$endMs ms", style = MaterialTheme.typography.labelSmall, fontFamily = FontFamily.Monospace, color = CaptureAccent)
    }
    Slider(
        value = endMs.toFloat(),
        onValueChange = {
            endMs = it.toInt().coerceIn(startMs + 1, durationMs)
            player.seekTo(endMs.toLong())
        },
        valueRange = 0f..durationMs.toFloat(),
        enabled = enabled && editable,
    )
    val trim = trimRange(startMs, endMs, durationMs)
    if (trim != null) {
        Text(
            "Trim ${trim.startMs}\u2013${trim.endMs} ms",
            style = MaterialTheme.typography.labelMedium,
            fontFamily = FontFamily.Monospace,
            color = CaptureAccentBright,
        )
    } else {
        Text(
            "Trim must be start < end",
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.error,
        )
    }
    var secondary by remember(selected, s.reviewing) { mutableStateOf(SecondarySelection()) }
    if (editable) {
        SecondaryPicker(s.taxonomy, secondary, enabled) { secondary = it }
        Button(
            onClick = { trim?.let { submit(category, it, secondary) } },
            enabled = enabled && trim != null && secondary.postures.isNotEmpty(),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text(if (s.reviewing) "Submit independent review" else "Submit immutable labels")
        }
    }
}

/** Reads a previously submitted action label from the submission payload, if the server sent one. */
private fun actionLabelOf(selected: JSONObject): ActionLabel? {
    val raw =
        selected.optJSONObject("action")
            ?: selected.optJSONObject("boxes")?.optJSONObject("action")
            ?: return null
    val categoryId = raw.optInt("category_id", -1)
    val startMs = raw.optInt("start_ms", -1)
    val endMs = raw.optInt("end_ms", -1)
    return if (categoryId >= 0 && startMs >= 0 && endMs > startMs) {
        ActionLabel(categoryId, startMs, endMs)
    } else null
}

@Composable
private fun CaptureVideo(enabled: Boolean, onVideo: (ByteArray, Int) -> Unit) {
    val context = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current
    var permission by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
                PackageManager.PERMISSION_GRANTED
        )
    }
    val request =
        rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
            permission = it
        }
    var videoCapture by remember { mutableStateOf<VideoCapture<Recorder>?>(null) }
    var recording by remember { mutableStateOf<Recording?>(null) }
    var recordingActive by remember { mutableStateOf(false) }
    var elapsedMs by remember { mutableIntStateOf(0) }
    var error by remember { mutableStateOf<String?>(null) }
    var pending by remember { mutableStateOf<Pair<ByteArray, Int>?>(null) }
    var endedByCap by remember { mutableStateOf(false) }
    val previewView = remember { PreviewView(context) }
    val live = remember { java.util.concurrent.atomic.AtomicBoolean(true) }
    DisposableEffect(Unit) {
        live.set(true)
        onDispose { live.set(false) }
    }
    if (!permission) {
        Card(Modifier.fillMaxWidth(), border = BorderStroke(1.dp, CaptureOutline)) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(
                    "The camera records one short action clip (\u2264 30 s) for labeling. Nothing is analyzed on device beyond this clip.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
                )
                Button(
                    onClick = { request.launch(Manifest.permission.CAMERA) },
                    enabled = enabled,
                    modifier = Modifier.fillMaxWidth(),
                ) { Text("Allow camera") }
            }
        }
        return
    }
    DisposableEffect(lifecycle, previewView) {
        val future = ProcessCameraProvider.getInstance(context)
        var provider: ProcessCameraProvider? = null
        var disposed = false
        val executor = ContextCompat.getMainExecutor(context)
        future.addListener(
            {
                if (!disposed)
                    try {
                        provider = future.get()
                        previewView.scaleType = PreviewView.ScaleType.FILL_CENTER
                        val preview =
                            Preview.Builder().build().also {
                                it.surfaceProvider = previewView.surfaceProvider
                            }
                        val recorder =
                            Recorder.Builder()
                                .setQualitySelector(
                                    QualitySelector.from(
                                        Quality.SD,
                                        FallbackStrategy.lowerQualityOrHigherThan(Quality.SD),
                                    )
                                )
                                .build()
                        val capture = VideoCapture.withOutput(recorder)
                        provider?.bindToLifecycle(
                            lifecycle,
                            CameraSelector.DEFAULT_BACK_CAMERA,
                            preview,
                            capture,
                        )
                        videoCapture = capture
                    } catch (e: Exception) {
                        error = e.message ?: "Camera unavailable"
                    }
            },
            executor,
        )
        onDispose {
            disposed = true
            recording?.stop()
            provider?.unbindAll()
            videoCapture = null
            recording = null
        }
    }
    // Hard duration cap: stop automatically once MAX_ACTION_MS elapses.
    LaunchedEffect(recordingActive) {
        if (recordingActive) {
            val startedAt = android.os.SystemClock.elapsedRealtime()
            while (recordingActive) {
                val e = (android.os.SystemClock.elapsedRealtime() - startedAt).toInt()
                elapsedMs = e
                if (e >= MAX_ACTION_MS) {
                    endedByCap = true
                    recording?.stop()
                    break
                }
                delay(100)
            }
        }
    }

    if (pending != null) {
        ConfirmationStrip(
            onRetake = {
                pending = null
                endedByCap = false
            },
            onUse = {
                onVideo(pending!!.first, pending!!.second)
                pending = null
            },
        )
        return
    }

    Box(
        Modifier
            .fillMaxWidth()
            .aspectRatio(3f / 4f)
            .clip(CaptureRadii.md)
            .background(CaptureBase),
    ) {
        AndroidView(factory = { previewView }, modifier = Modifier.fillMaxSize())
        ViewfinderGrid(Modifier.fillMaxSize())
        LowAngleGuidance(Modifier.align(Alignment.TopCenter))
        // Monospace timer overlay.
        val timerColor =
            when {
                elapsedMs >= MAX_ACTION_MS -> MaterialTheme.colorScheme.error
                elapsedMs >= 25_000 -> WarnAmber
                else -> CaptureInk
            }
        Text(
            "${formatClock(elapsedMs)} / 0:30",
            style = MaterialTheme.typography.labelMedium,
            fontFamily = FontFamily.Monospace,
            color = timerColor,
            modifier = Modifier
                .align(Alignment.TopEnd)
                .padding(12.dp)
                .captureGlass(CaptureRadii.pill)
                .padding(horizontal = 8.dp, vertical = 4.dp),
        )
        if (endedByCap) {
            Text(
                "Recording ended at 30 s",
                style = MaterialTheme.typography.labelSmall,
                color = WarnAmber,
                modifier = Modifier
                    .align(Alignment.TopStart)
                    .padding(12.dp),
            )
        }
        RecordButton(
            recording = recording != null,
            enabled = enabled && videoCapture != null && (recording == null || recordingActive),
            modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 24.dp),
            onClick = {
                val cap = videoCapture
                if (cap != null) {
                    val current = recording
                    if (current == null) {
                        elapsedMs = 0
                        endedByCap = false
                        val file = File.createTempFile("seeker-action-", ".mp4", context.cacheDir)
                        val pendingRecording =
                            cap.output.prepareRecording(
                                context,
                                FileOutputOptions.Builder(file).build(),
                            )
                        recording =
                            pendingRecording.start(
                                ContextCompat.getMainExecutor(context),
                            ) { event ->
                                when (event) {
                                    is VideoRecordEvent.Start -> recordingActive = true
                                    is VideoRecordEvent.Finalize -> {
                                        recordingActive = false
                                        recording = null
                                        if (event.hasError()) {
                                            error = "Recording failed (code ${event.error})"
                                            file.delete()
                                        } else {
                                            try {
                                                if (live.get())
                                                    pending = file.readBytes() to cappedDurationMs(elapsedMs)
                                            } finally {
                                                file.delete()
                                            }
                                        }
                                    }
                                    else -> Unit
                                }
                            }
                    } else {
                        current.stop()
                    }
                }
            },
        )
    }
    error?.let { CaptureErrorCard(it) { error = null } }
}

@Composable
private fun ConfirmationStrip(onRetake: () -> Unit, onUse: () -> Unit) {
    AnimatedVisibility(visible = true, enter = fadeIn() + scaleIn(initialScale = 0.95f)) {
        Card(Modifier.fillMaxWidth(), border = BorderStroke(1.dp, CaptureOutline)) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(
                    "Looks good?",
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = onRetake, modifier = Modifier.weight(1f)) { Text("Retake") }
                    Button(onClick = onUse, modifier = Modifier.weight(1f)) { Text("Use this") }
                }
            }
        }
    }
}

@Composable
private fun LowAngleGuidance(modifier: Modifier = Modifier) {
    GlassCard(modifier = modifier.padding(12.dp), tint = CaptureAccent) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            CaptureIcon(CaptureSymbol.CAMERA, Modifier.size(24.dp), CaptureInk)
            Column {
                Text("6–12 in · 0–45° ↗", style = MaterialTheme.typography.titleMedium, color = CaptureInk)
                Text("FLOOR VISIBLE", style = MaterialTheme.typography.labelSmall, color = MutedGray)
            }
        }
    }
}

@Composable
private fun ViewfinderGrid(modifier: Modifier = Modifier) {
    // Neutral guide: no on-device detector is wired, so never claim a label is present.
    Canvas(modifier = modifier) {
        val w = size.width
        val h = size.height
        drawLine(CaptureAccent.copy(alpha = .25f), Offset(w / 2, 0f), Offset(w / 2, h), 1.dp.toPx())
        drawLine(CaptureAccent.copy(alpha = .25f), Offset(0f, h / 2), Offset(w, h / 2), 1.dp.toPx())
        val arm = 20.dp.toPx()
        val inset = 12.dp.toPx()
        listOf(Offset(inset, inset), Offset(w - inset, inset), Offset(inset, h - inset), Offset(w - inset, h - inset)).forEachIndexed { i, p ->
            drawLine(CaptureAccent, p, p + Offset(if (i % 2 == 0) arm else -arm, 0f), 2.dp.toPx())
            drawLine(CaptureAccent, p, p + Offset(0f, if (i < 2) arm else -arm), 2.dp.toPx())
        }
    }
}

@Composable
private fun ShutterButton(
    enabled: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val haptic = LocalHapticFeedback.current
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    val scale by animateFloatAsState(
        targetValue = if (pressed) 0.92f else 1f,
        animationSpec = spring(dampingRatio = Spring.DampingRatioMediumBouncy, stiffness = Spring.StiffnessMedium),
        label = "shutter-scale",
    )
    Box(
        modifier
            .size(72.dp)
            .scale(scale)
            .clip(CircleShape)
            .background(CaptureAccent)
            .clickable(interactionSource = interaction, indication = null, enabled = enabled) {
                haptic.performHapticFeedback(HapticFeedbackType.LongPress)
                onClick()
            },
        contentAlignment = Alignment.Center,
    ) {
        Box(
            Modifier
                .size(58.dp)
                .clip(CircleShape)
                .background(CaptureAccent),
        )
        Box(
            Modifier
                .size(50.dp)
                .clip(CircleShape)
                .background(CaptureInk),
        )
    }
}

@Composable
private fun RecordButton(
    recording: Boolean,
    enabled: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val haptic = LocalHapticFeedback.current
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    val scale by animateFloatAsState(
        targetValue = if (pressed) 0.92f else 1f,
        animationSpec = spring(dampingRatio = Spring.DampingRatioMediumBouncy, stiffness = Spring.StiffnessMedium),
        label = "record-scale",
    )
    val dotColor by animateColorAsState(
        targetValue = if (recording) CaptureInk else CaptureAccent,
        label = "record-dot",
    )
    Box(
        modifier
            .size(72.dp)
            .scale(scale)
            .clip(CircleShape)
            .captureGlass(CaptureRadii.pill)
            .clickable(interactionSource = interaction, indication = null, enabled = enabled) {
                haptic.performHapticFeedback(HapticFeedbackType.LongPress)
                onClick()
            },
        contentAlignment = Alignment.Center,
    ) {
        if (recording) {
            // Square stop icon while recording.
            Box(
                Modifier
                    .size(26.dp)
                    .clip(RoundedCornerShape(6.dp))
                    .background(CaptureInk),
            )
        } else {
            Box(
                Modifier
                    .size(54.dp)
                    .clip(CircleShape)
                    .background(CaptureGradients.action),
                contentAlignment = Alignment.Center,
            ) {
                Box(Modifier.size(10.dp).clip(CircleShape).background(dotColor))
            }
        }
    }
}

private fun formatClock(ms: Int): String {
    val totalSeconds = (ms / 1000).coerceAtLeast(0)
    return "%d:%02d".format(totalSeconds / 60, totalSeconds % 60)
}

/**
 * Secondary + capture-metadata section shown inside each editable editor.
 * Posture is required in v2; expression, environment, surface, lighting,
 * weather, and ego-motion are optional. Collapsed by default; the whole section
 * is a disclosure the user opens on purpose.
 */
@Composable
private fun SecondaryPicker(
    taxonomy: List<TaxonomyCategory>,
    selection: SecondarySelection,
    enabled: Boolean,
    onChange: (SecondarySelection) -> Unit,
) {
    val expressions = categoriesOfKind(taxonomy, KIND_EXPRESSION)
    val postures = categoriesOfKind(taxonomy, KIND_POSTURE)
    val environments = environmentGroups(taxonomy)
    val surfaces = categoriesOfKind(taxonomy, KIND_SURFACE_TYPE)
    val lightings = categoriesOfKind(taxonomy, KIND_LIGHTING)
    val weathers = categoriesOfKind(taxonomy, KIND_WEATHER)
    if (
        expressions.isEmpty() && postures.isEmpty() && environments.isEmpty() &&
            surfaces.isEmpty() && lightings.isEmpty() && weathers.isEmpty()
    ) return

    var expanded by remember { mutableStateOf(false) }
    val totalSelected =
        selection.expressions.size + selection.postures.size + selection.environment.size +
            listOf(selection.surfaceType, selection.lighting, selection.weather).count { it != null } +
            (if (selection.egoMotion) 1 else 0)

    Card(Modifier.fillMaxWidth(), border = BorderStroke(1.dp, CaptureOutline)) {
        Column(
            Modifier
                .padding(vertical = 4.dp)
                .animateContentSize(),
        ) {
            Row(
                Modifier
                    .fillMaxWidth()
                    .clickable { expanded = !expanded }
                    .padding(horizontal = 12.dp, vertical = 10.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Text(
                        "Context & metadata",
                        style = MaterialTheme.typography.titleMedium,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                    if (!expanded && totalSelected == 0) {
                        Text(
                            "Posture required — the rest is optional",
                            style = MaterialTheme.typography.labelSmall,
                            color = MutedGray,
                        )
                    }
                }
                if (totalSelected > 0) CountBadge("$totalSelected selected")
                Text(
                    if (expanded) "\u25B4" else "\u25BE",
                    color = MutedGray,
                    style = MaterialTheme.typography.labelLarge,
                )
            }
            if (expanded) {
                Column(
                    Modifier.padding(horizontal = 12.dp, vertical = 4.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    if (expressions.isNotEmpty()) {
                        SecondaryGroupHeader("Expression (optional)", selection.expressions.size)
                        LabelChipFlow {
                            expressions.forEach { c ->
                                LabelChip(
                                    c.name,
                                    c.id in selection.expressions,
                                    CaptureAccent,
                                    enabled = enabled,
                                    glyph = ChipGlyph.DISMISS,
                                ) {
                                    onChange(
                                        selection.copy(
                                            expressions =
                                                if (c.id in selection.expressions) selection.expressions - c.id
                                                else selection.expressions + c.id
                                        )
                                    )
                                }
                            }
                        }
                    }

                    if (postures.isNotEmpty()) {
                        SecondaryGroupHeader("Posture (required)", selection.postures.size)
                        LabelChipFlow {
                            postures.forEach { c ->
                                LabelChip(
                                    c.name,
                                    c.id in selection.postures,
                                    CaptureAccent,
                                    enabled = enabled,
                                    glyph = ChipGlyph.DISMISS,
                                ) {
                                    onChange(
                                        selection.copy(
                                            postures =
                                                if (c.id in selection.postures) selection.postures - c.id
                                                else selection.postures + c.id
                                        )
                                    )
                                }
                            }
                        }
                    }

                    if (environments.isNotEmpty()) {
                        SecondaryGroupHeader("Environment", selection.environment.size)
                        Text(
                            "One per group.",
                            style = MaterialTheme.typography.labelSmall,
                            color = MutedGray,
                        )
                        environments.forEach { group ->
                            Row(
                                Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(
                                    group.name,
                                    style = MaterialTheme.typography.labelMedium,
                                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.8f),
                                )
                                Text(
                                    "at most 1",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MutedGray,
                                )
                            }
                            LabelChipFlow {
                                group.categories.forEach { c ->
                                    LabelChip(
                                        c.name,
                                        c.id in selection.environment,
                                        CaptureAccent,
                                        enabled = enabled,
                                        glyph = ChipGlyph.DISMISS,
                                    ) {
                                        onChange(
                                            selection.copy(
                                                environment =
                                                    toggleEnvironmentSelection(
                                                        taxonomy, selection.environment, c.id
                                                    )
                                            )
                                        )
                                    }
                                }
                            }
                        }
                    }
                    if (surfaces.isNotEmpty()) {
                        SingleSelectMetaGroup("Surface", surfaces, selection.surfaceType, enabled) { wire ->
                            onChange(selection.copy(surfaceType = wire))
                        }
                    }
                    if (lightings.isNotEmpty()) {
                        SingleSelectMetaGroup("Lighting", lightings, selection.lighting, enabled) { wire ->
                            onChange(selection.copy(lighting = wire))
                        }
                    }
                    if (weathers.isNotEmpty()) {
                        SingleSelectMetaGroup("Weather", weathers, selection.weather, enabled) { wire ->
                            onChange(selection.copy(weather = wire))
                        }
                    }

                    Row(
                        Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text(
                                "Moving camera",
                                style = MaterialTheme.typography.labelLarge,
                                color = MaterialTheme.colorScheme.onSurface,
                            )
                            Text(
                                "True if this capture was shot while moving (ego motion).",
                                style = MaterialTheme.typography.labelSmall,
                                color = MutedGray,
                            )
                        }
                        Switch(
                            checked = selection.egoMotion,
                            onCheckedChange = { onChange(selection.copy(egoMotion = it)) },
                            enabled = enabled,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun SingleSelectMetaGroup(
    label: String,
    categories: List<TaxonomyCategory>,
    selectedWire: String?,
    enabled: Boolean,
    onSelect: (String?) -> Unit,
) {
    SecondaryGroupHeader(label, if (selectedWire != null) 1 else 0)
    LabelChipFlow {
        categories.forEach { c ->
            val wire = categoryWireId(c)
            LabelChip(
                c.name,
                wire == selectedWire,
                CaptureAccent,
                enabled = enabled,
                glyph = ChipGlyph.CHECK,
            ) {
                onSelect(if (wire == selectedWire) null else wire)
            }
        }
    }
}

@Composable
private fun SecondaryGroupHeader(name: String, count: Int) {
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            name,
            style = MaterialTheme.typography.labelLarge,
            color = MaterialTheme.colorScheme.onSurface,
        )
        if (count > 0) CountBadge("$count selected")
    }
}
