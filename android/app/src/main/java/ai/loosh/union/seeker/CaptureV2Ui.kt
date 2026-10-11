package ai.loosh.union.seeker

import ai.loosh.union.*
import androidx.compose.animation.core.*
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.runtime.saveable.rememberSaveable
import android.graphics.Bitmap
import androidx.compose.foundation.Image
import androidx.compose.ui.layout.ContentScale
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.clickable
import androidx.compose.ui.draw.alpha
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.blur
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.*
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import kotlinx.coroutines.delay
import java.util.Locale

private fun decimal(value: Double, digits: Int = 2) = String.format(Locale.US, "%.${digits}f", value)

@Composable
fun LevelBadge(level: Int, modifier: Modifier = Modifier, cascade: Int? = null, halo: Dp = 14.dp, unlocked: Boolean = true) {
    val rank = level.coerceIn(0, MAX_LEVEL)
    Box(modifier.semantics { contentDescription = "Level $rank, ${levelName(rank)}" }, contentAlignment = Alignment.Center) {
        if (rank >= 3 && unlocked) Box(Modifier.matchParentSize().blur(halo).background(CaptureAccentTint, CaptureRadii.pill))
        Canvas(Modifier.matchParentSize()) {
            val u = size.minDimension
            val inset = u * .08f
            val bounds = Size(u - inset * 2, u - inset * 2)
            drawCircle(CaptureSurface, u * .44f)
            repeat(4) { i ->
                val lit = unlocked && i < (cascade ?: rank)
                drawArc(if (lit) CaptureGradients.ring else Brush.sweepGradient(listOf(CaptureOutline.copy(alpha = .6f), CaptureOutline.copy(alpha = .6f))),
                    -87f + i * 90f, 84f, false, Offset(inset, inset), bounds, style = Stroke(u * .045f, cap = StrokeCap.Round))
            }
            if (rank >= 2) drawCircle(if (unlocked) CaptureAccentBorder else CaptureOutline, u * .32f,
                style = Stroke(u * .012f, pathEffect = PathEffect.dashPathEffect(floatArrayOf(u * .04f, u * .04f))))
            if (rank == 4 && unlocked) {
                val bracket = Path().apply { moveTo(u*.03f,u*.24f); lineTo(u*.03f,u*.03f); lineTo(u*.24f,u*.03f) }
                drawPath(bracket, CaptureInk, style = Stroke(u*.025f, cap = StrokeCap.Round))
            }
        }
        val icon = listOf(CaptureSymbol.EXPLORE, CaptureSymbol.ROUTE, CaptureSymbol.VERIFIED, CaptureSymbol.TARGET, CaptureSymbol.BRANCH)[rank]
        CaptureIcon(icon, Modifier.fillMaxSize(.36f), if (unlocked) CaptureInk else CaptureInkFaint)
    }
}

@Composable
private fun ProgressArc(fraction: Float, modifier: Modifier = Modifier, thin: Boolean = false) {
    var entered by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { entered = true }
    val progress by animateFloatAsState(if (entered) fraction.coerceIn(0f, 1f) else 0f,
        tween(CaptureMotion.slow, easing = CaptureMotion.progressEasing), label = "rank progress")
    Canvas(modifier) {
        val width = (if (thin) 2 else 10).dp.toPx()
        val inset = width / 2
        val bounds = Size(size.width - width, size.height - width)
        drawArc(CaptureOutline, -90f, 360f, false, Offset(inset, inset), bounds, style = Stroke(width))
        drawArc(CaptureGradients.ring, -90f, progress * 360f, false, Offset(inset, inset), bounds, style = Stroke(width, cap = StrokeCap.Round))
    }
}

@Composable
fun LevelRingBadge(level: Int, fraction: Float, modifier: Modifier = Modifier) {
    Box(modifier.semantics { contentDescription = "Level $level" }, contentAlignment = Alignment.Center) {
        ProgressArc(fraction, Modifier.matchParentSize(), thin = true)
        Text("$level", style = MaterialTheme.typography.titleLarge, color = CaptureInk)
    }
}

@Composable
fun LevelBadgeRing(s: PilotState, onClick: () -> Unit) {
    val next = LEVEL_TIERS.getOrNull(s.level + 1)
    Box(Modifier.size(48.dp).clickable(onClick = onClick).semantics { contentDescription = "View level progress" }, contentAlignment = Alignment.Center) {
        LevelRingBadge(s.level, next?.let { s.acceptedCount.toFloat() / it.acceptedThreshold } ?: 1f, Modifier.size(40.dp))
    }
}

@Composable
fun ProgressRingCard(s: PilotState, onClick: () -> Unit) {
    val next = LEVEL_TIERS.getOrNull(s.level + 1)
    Column(Modifier.fillMaxWidth().clip(CaptureRadii.xl).clickable(onClick = onClick).padding(12.dp),
        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Box(Modifier.size(40.dp), contentAlignment = Alignment.Center) {
            ProgressArc(next?.let { s.acceptedCount.toFloat() / it.acceptedThreshold } ?: 1f, Modifier.fillMaxSize(), thin = true)
        }
        Text(next?.let { "${s.acceptedCount} / ${it.acceptedThreshold}" } ?: "${s.acceptedCount}", style = CaptureNumeric)
        Text(if (next == null) "TOP RANK" else "NEXT", style = MaterialTheme.typography.labelMedium, color = MutedGray)
        if (next != null && s.acceptedCount >= next.acceptedThreshold && acceptancePercent(s.acceptanceRate) < (next.rateThresholdPercent ?: 0)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                CaptureIcon(CaptureSymbol.LOCK, Modifier.size(16.dp))
                Text("RATE ${acceptancePercent(s.acceptanceRate)}% · NEED ${next.rateThresholdPercent}%", style = MaterialTheme.typography.labelSmall, color = MutedGray)
            }
        }
    }
}

@Composable
fun LevelCard(s: PilotState, modifier: Modifier = Modifier) {
    // The backend rank includes the accuracy gate; count-only levelProgress is
    // intentionally left unchanged for existing callers and model tests.
    val next = LEVEL_TIERS.getOrNull(s.level + 1)
    var entered by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { entered = true }
    val count by animateIntAsState(if (entered) s.acceptedCount else 0, tween(CaptureMotion.slow), label = "accepted count")
    CapturePanel(modifier.fillMaxWidth()) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Column {
                Text("LEVEL ${s.level}", style = MaterialTheme.typography.labelMedium, color = MutedGray)
                Text(s.levelName, style = MaterialTheme.typography.headlineSmall)
            }
            LevelBadge(s.level, Modifier.size(64.dp))
        }
        Box(Modifier.align(Alignment.CenterHorizontally).size(216.dp), contentAlignment = Alignment.Center) {
            ProgressArc(next?.let { s.acceptedCount.toFloat() / it.acceptedThreshold } ?: 1f, Modifier.fillMaxSize())
            Column(Modifier.padding(20.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(if (next == null) "$count" else "$count / ${next.acceptedThreshold}", style = CaptureNumeric.copy(fontSize = 24.sp))
                Text("ACCEPTED", style = MaterialTheme.typography.labelMedium, color = MutedGray)
                Text(next?.let { "NEXT: ${it.name.uppercase(Locale.ROOT)}" } ?: "TOP RANK", style = MaterialTheme.typography.labelMedium, color = MutedGray, textAlign = TextAlign.Center)
            }
        }
        if (next != null) {
            val rate = acceptancePercent(s.acceptanceRate)
            val needsRate = rate < (next.rateThresholdPercent ?: 0)
            Text(if (s.acceptedCount >= next.acceptedThreshold && needsRate) "RATE $rate% · NEED ${next.rateThresholdPercent}%"
                else "${(next.acceptedThreshold - s.acceptedCount).coerceAtLeast(0)} TO GO · NEED ${next.rateThresholdPercent}% RATE",
                style = MaterialTheme.typography.labelMedium, color = MutedGray)
        }
    }
}

@Composable
fun MetricTiles(s: PilotState) {
    // Two rows keep labels and values legible on compact devices and large fonts.
    val values = listOf("ACCEPTED" to "${s.acceptedCount}", "ACCURACY" to "${acceptancePercent(s.acceptanceRate)}%",
        "BOND ×" to if (s.bondMultiplier <= 0) "WAIVED" else decimal(s.bondMultiplier, 1),
        "NEXT" to (LEVEL_TIERS.getOrNull(s.level + 1)?.acceptedThreshold?.toString() ?: "MAX"))
    val colors = listOf(CaptureInk, SuccessGreen, CaptureInk, CaptureInk)
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        values.chunked(2).forEachIndexed { row, items ->
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                items.forEachIndexed { col, (label, value) ->
                    CapturePanel(Modifier.weight(1f), elevated = true) {
                        Text(value, style = CaptureNumeric.copy(fontSize = 22.sp), color = colors[row * 2 + col])
                        Text(label, style = MaterialTheme.typography.labelMedium, color = MutedGray)
                    }
                }
            }
        }
    }
}

@Composable
fun RateTicker(s: PilotState, modifier: Modifier = Modifier) {
    CapturePanel(modifier.fillMaxWidth()) {
        Text("CURRENT BASE RATE", style = MaterialTheme.typography.labelMedium, color = MutedGray)
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            listOf("$0.10" to "PHOTO", "$0.25" to "5–15 SEC", "$0.40" to "15–30 SEC").forEach { (rate, label) ->
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(rate, style = CaptureNumeric.copy(fontSize = 22.sp), color = CaptureAccentBright)
                    Text(label, style = MaterialTheme.typography.labelSmall, color = MutedGray)
                }
            }
        }
        Text("×${decimal(s.rateMultiplier)} RATE MULTIPLIER", style = MaterialTheme.typography.labelMedium, color = CaptureAccentBright,
            modifier = Modifier.background(CaptureAccent.copy(alpha = .1f), CaptureRadii.pill).padding(horizontal = 12.dp, vertical = 8.dp))
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun CaptureButton(enabled: Boolean, onCapture: () -> Unit, onGallery: () -> Unit) {
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    val scale by animateFloatAsState(if (pressed) .94f else 1f, spring(.45f, 380f), label = "capture press")
    val pulse = rememberInfiniteTransition(label = "capture halo")
    val halo by pulse.animateFloat(1f, 1.06f, infiniteRepeatable(tween(1600, easing = FastOutSlowInEasing), RepeatMode.Reverse), label = "halo scale")
    val haptic = LocalHapticFeedback.current
    Column(Modifier.fillMaxWidth().padding(vertical = 12.dp), horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Box(Modifier.size(250.dp), contentAlignment = Alignment.Center) {
            Box(Modifier.size(250.dp).scale(if (enabled) halo else 1f).blur(28.dp).background(CaptureGradients.actionGlow, CaptureRadii.pill))
            Box(Modifier.size(200.dp).scale(scale).clip(CaptureRadii.pill).background(CaptureGradients.action, alpha = if (enabled) 1f else .35f)
                .combinedClickable(interactionSource = interaction, indication = null, enabled = enabled,
                    onClickLabel = "View capture examples", onLongClickLabel = "Start capture",
                    onClick = onGallery, onLongClick = { haptic.performHapticFeedback(HapticFeedbackType.LongPress); onCapture() })
                .semantics { contentDescription = "Capture. Tap for examples, hold to begin." }, contentAlignment = Alignment.Center) {
                if (pressed) {
                    Box(Modifier.matchParentSize().background(CaptureGradients.actionGlow))
                    Canvas(Modifier.matchParentSize().padding(5.dp)) { drawCircle(CaptureInk.copy(alpha = .8f), style = Stroke(1.dp.toPx())) }
                }
                CaptureIcon(CaptureSymbol.CAMERA, Modifier.size(44.dp), CaptureInk)
            }
        }
        Text("TAP TO CAPTURE", style = MaterialTheme.typography.labelMedium, color = MutedGray)
    }
}

@Composable
fun ConstellationLadder(currentLevel: Int? = null, compact: Boolean = false) {
    val pulse = rememberInfiniteTransition(label = "current level")
    val glow by pulse.animateFloat(.12f, .35f, infiniteRepeatable(tween(2400), RepeatMode.Reverse), label = "level glow")
    val nodeSize = if (compact) 42.dp else 64.dp
    val rowHeight = if (compact) 70.dp else 112.dp
    Box(Modifier.fillMaxWidth()) {
        Canvas(Modifier.matchParentSize()) {
            val x = size.width / 2
            val start = nodeSize.toPx() / 2
            drawLine(CaptureOutline.copy(alpha = .6f), Offset(x, start), Offset(x, rowHeight.toPx() * 4 + start), 1.dp.toPx())
            if (currentLevel != null && currentLevel > 0) drawLine(CaptureAccent, Offset(x, start), Offset(x, rowHeight.toPx() * currentLevel + start), 2.dp.toPx())
        }
        Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
            LEVEL_TIERS.forEach { tier ->
                Column(Modifier.height(rowHeight).fillMaxWidth().semantics {
                    contentDescription = "${tier.name}, ${tier.acceptedThreshold} accepted, rate ${tier.rateMultiplier}" +
                        (tier.rateThresholdPercent?.let { ", accuracy at least $it percent" } ?: "")
                }, horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Box(contentAlignment = Alignment.Center) {
                        if (tier.level == currentLevel) Box(Modifier.size(nodeSize).blur(14.dp).background(CaptureAccentBright.copy(alpha = glow), CaptureRadii.pill))
                        LevelBadge(tier.level, Modifier.size(nodeSize), unlocked = currentLevel == null || tier.level <= currentLevel)
                    }
                    Text("${tier.acceptedThreshold} · ×${decimal(tier.rateMultiplier)}", style = MaterialTheme.typography.labelSmall,
                        color = MutedGray, modifier = Modifier.background(CaptureBase, CaptureRadii.pill).padding(horizontal = 8.dp))
                }
            }
        }
    }
}

@Composable
fun LevelScreen(s: PilotState, onBack: () -> Unit) {
    androidx.activity.compose.BackHandler(onBack = onBack)
    NavyBackground(Modifier.fillMaxSize().captureScreenMotion()) {
        Column(Modifier.fillMaxSize().safeDrawingPadding().verticalScroll(rememberScrollState()).padding(20.dp),
            horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(16.dp)) {
            TextButton(onClick = onBack, modifier = Modifier.align(Alignment.Start)) { Text("← Back") }
            Text(s.levelName, style = MaterialTheme.typography.displaySmall)
            LevelRingBadge(s.level, LEVEL_TIERS.getOrNull(s.level + 1)?.let { s.acceptedCount.toFloat() / it.acceptedThreshold } ?: 1f, Modifier.size(72.dp))
            Text("RATE ×${decimal(s.rateMultiplier)} · BOND ${if (s.bondMultiplier == 0.0) "WAIVED" else "×${decimal(s.bondMultiplier, 1)}"}",
                style = MaterialTheme.typography.titleMedium, color = MutedGray)
            ConstellationLadder(s.level)
            LevelCard(s)
        }
    }
}

@Composable
fun JudgePendingScreen(image: Bitmap? = null) {
    val transition = rememberInfiniteTransition(label = "judging ring")
    val rotation by transition.animateFloat(0f, 360f, infiniteRepeatable(tween(1200, easing = LinearEasing)), label = "judging sweep")
    Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Box(Modifier.fillMaxWidth().height(240.dp).clip(CaptureRadii.xl).background(CaptureSurface), contentAlignment = Alignment.Center) {
            if (image != null) Image(image.asImageBitmap(), "Submitted capture", Modifier.matchParentSize().alpha(.6f).blur(3.dp), contentScale = ContentScale.Crop)
            else ConstellationBackground(Modifier.matchParentSize())
            Canvas(Modifier.size(64.dp).graphicsLayer { rotationZ = rotation }) {
                drawArc(CaptureGradients.ring, -90f, 270f, false, Offset(4.dp.toPx(), 4.dp.toPx()),
                    Size(size.width - 8.dp.toPx(), size.height - 8.dp.toPx()), style = Stroke(3.dp.toPx(), cap = StrokeCap.Round))
            }
            CaptureIcon(CaptureSymbol.LIGHT, Modifier.size(24.dp), CaptureInk)
        }
        Text("Judging…", style = MaterialTheme.typography.titleMedium, color = MutedGray)
    }
}

@Composable
fun VerdictCard(result: SubmissionResult, onDismiss: () -> Unit, onGallery: () -> Unit = {}, s: PilotState? = null, onCaptureAgain: () -> Unit = onDismiss) {
    if (result.verdict == null) {
        JudgePendingScreen(s?.image)
        TextButton(onClick = onDismiss) { Text("DISMISS") }
        return
    }
    val accepted = result.verdict.accepted
    val tint = if (accepted) SuccessGreen else ErrorRed
    val haptic = LocalHapticFeedback.current
    var announced by rememberSaveable(result) { mutableStateOf(false) }
    LaunchedEffect(result) {
        if (!announced) { haptic.performHapticFeedback(HapticFeedbackType.LongPress); announced = true }
    }
    Box(Modifier.fillMaxWidth()) {
        if (accepted) ConfettiCanvas(Modifier.matchParentSize())
        val body: @Composable ColumnScope.() -> Unit = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Box(Modifier.size(48.dp).border(2.dp, tint, CaptureRadii.pill), contentAlignment = Alignment.Center) {
                    Text(if (accepted) "✓" else "×", style = CaptureNumeric, color = tint)
                }
                Text(if (accepted) "ACCEPTED" else "REJECTED", style = MaterialTheme.typography.displayMedium, color = tint)
            }
            if (accepted) {
                Text(if (result.paid) "PAID TO YOU" else "PAYOUT PENDING", style = MaterialTheme.typography.labelMedium, color = MutedGray)
                Text("+$${decimal(result.payoutUsdc / 1_000_000.0)}", style = CaptureNumeric.copy(fontSize = 40.sp, lineHeight = 44.sp), color = CaptureAccent)
                Text("TEST-USDC", style = MaterialTheme.typography.labelMedium, color = CaptureAccentBright)
                s?.let {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        listOf("+1" to "ACCEPTED", "—" to "STREAK", "${acceptancePercent(it.acceptanceRate)}%" to "RATE").forEach { (value, label) ->
                            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                Text(value, style = MaterialTheme.typography.titleMedium, color = CaptureAccentBright)
                                Text(label, style = MaterialTheme.typography.labelMedium, color = MutedGray)
                            }
                        }
                    }
                }
                ActionButton("CAPTURE AGAIN", onCaptureAgain, enabled = s?.busy != true)
                OutlinedButton(onClick = onGallery, modifier = Modifier.fillMaxWidth().captureGlass(CaptureRadii.pill)) { Text("VIEW GALLERY", color = CaptureAccentBright) }
            } else {
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Box(Modifier.width(3.dp).height(56.dp).captureCardMotion(0).background(ErrorRed, CaptureRadii.pill))
                    Text(result.verdict.reason.ifBlank { "This capture did not meet the quality bar. Check the examples and try again." }, style = MaterialTheme.typography.bodySmall, color = MutedGray)
                }
                Text("BOND SLASHED · FIX & RESHOOT", style = MaterialTheme.typography.labelMedium, color = MutedGray)
                Button(onClick = onGallery, colors = ButtonDefaults.buttonColors(containerColor = CaptureAccent, contentColor = CaptureInk), modifier = Modifier.fillMaxWidth()) { Text("SEE EXAMPLE") }
                OutlinedButton(onClick = onCaptureAgain, enabled = s?.busy != true, modifier = Modifier.fillMaxWidth()) { Text("RESHOOT") }
            }
        }
        GlassCard(Modifier.fillMaxWidth(), if (accepted) CaptureAccent else ErrorRed, body)
    }
}

@Composable
fun LevelUpOverlay(level: Int, onDismiss: () -> Unit) {
    val pop = remember { Animatable(.3f) }
    val flash = remember { Animatable(.2f) }
    var cascade by remember { mutableIntStateOf(0) }
    var showCopy by remember { mutableStateOf(false) }
    val halo by animateDpAsState(if (showCopy) 14.dp else 40.dp, tween(260), label = "rank halo")
    LaunchedEffect(Unit) { delay(260); showCopy = true }
    val haptic = LocalHapticFeedback.current
    LaunchedEffect(Unit) { pop.animateTo(1f, spring(.45f, 380f)) }
    LaunchedEffect(Unit) { flash.animateTo(0f, tween(CaptureMotion.fast)) }
    LaunchedEffect(Unit) {
        haptic.performHapticFeedback(HapticFeedbackType.LongPress)
        delay(120)
        repeat(4) { cascade = it + 1; delay(60) }
        delay(160)
        cascade = level
    }
    Dialog(onDismissRequest = onDismiss, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Box(Modifier.fillMaxSize().background(CaptureBase.copy(alpha = .9f)).clickable(onClick = onDismiss), contentAlignment = Alignment.Center) {
            ConfettiCanvas(Modifier.fillMaxSize(), startDelay = 160)
            CapturePanel(Modifier.fillMaxWidth().safeDrawingPadding().padding(20.dp).verticalScroll(rememberScrollState()), elevated = true) {
                LevelBadge(level, Modifier.size(180.dp).scale(pop.value).align(Alignment.CenterHorizontally), cascade, halo)
                AnimatedVisibility(showCopy, enter = fadeIn(tween(CaptureMotion.base))) {
                    Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
                        Text("NEW RANK", style = MaterialTheme.typography.labelMedium, color = MutedGray)
                        Text(levelName(level), style = MaterialTheme.typography.displaySmall.copy(fontSize = if (level == 4) 30.sp else 40.sp))
                        val tier = levelTier(level)
                        Text("RATE ×${decimal(tier.rateMultiplier)} · BOND ${if (tier.bondMultiplier == 0.0) "WAIVED" else "×${decimal(tier.bondMultiplier, 1)}"}", color = CaptureAccent, style = MaterialTheme.typography.labelMedium)
                        ActionButton("KEEP CAPTURING", onDismiss)
                    }
                }
            }
            Box(Modifier.matchParentSize().background(CaptureOnBase.copy(alpha = flash.value)))
        }
    }
}
