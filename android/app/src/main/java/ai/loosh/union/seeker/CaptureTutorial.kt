package ai.loosh.union.seeker

import ai.loosh.union.*
import ai.loosh.union.R
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch

@Composable
fun IntroConstellationScreen(onDone: () -> Unit) {
    NavyBackground(Modifier.fillMaxSize().captureScreenMotion()) {
        ConstellationBackground(Modifier.matchParentSize())
        Column(Modifier.fillMaxSize().safeDrawingPadding().padding(20.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            TextButton(onClick = onDone, modifier = Modifier.align(Alignment.End)) { Text("Skip", color = MutedGray) }
            Column(Modifier.weight(1f).fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
                CaptureMark(Modifier.size(88.dp))
                Spacer(Modifier.height(24.dp))
                Text("Capture", style = MaterialTheme.typography.displayMedium)
                Spacer(Modifier.height(12.dp))
                Text("Ground truth, from the ground up.", style = MaterialTheme.typography.bodySmall, color = MutedGray, textAlign = TextAlign.Center)
            }
            ActionButton("Start capturing", onDone)
            Spacer(Modifier.height(16.dp))
        }
    }
}

@Composable
fun CaptureTutorialScreen(onDone: () -> Unit) {
    val pager = rememberPagerState(pageCount = { 4 })
    val scope = rememberCoroutineScope()
    NavyBackground(Modifier.fillMaxSize().captureScreenMotion()) {
        Column(Modifier.fillMaxSize().safeDrawingPadding().padding(vertical = 16.dp)) {
            Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                CaptureMark(Modifier.size(28.dp))
                TextButton(onClick = onDone) { Text("Skip", color = MutedGray) }
            }
            HorizontalPager(state = pager, modifier = Modifier.weight(1f).fillMaxWidth()) { page ->
                Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp), verticalArrangement = Arrangement.spacedBy(20.dp)) {
                    when (page) {
                        0 -> TutorialGroundLevelScreen()
                        1 -> TutorialWhatToCaptureScreen()
                        2 -> TutorialLabelingScreen()
                        else -> TutorialEarnLevelScreen()
                    }
                }
            }
            Column(Modifier.padding(horizontal = 20.dp), verticalArrangement = Arrangement.spacedBy(20.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    repeat(4) { i ->
                        Box(Modifier.size(if (i == pager.currentPage) 24.dp else 8.dp, 8.dp)
                            .background(if (i == pager.currentPage) CaptureAccent else CaptureOutline, CaptureRadii.pill))
                    }
                }
                ActionButton(if (pager.currentPage == 3) "Start capturing" else "Continue", {
                    if (pager.currentPage == 3) onDone() else scope.launch { pager.animateScrollToPage(pager.currentPage + 1) }
                })
            }
        }
    }
}

@Composable
private fun TutorialGroundLevelScreen() {
    Text("Get low", style = MaterialTheme.typography.displaySmall)
    CapturePanel(Modifier.fillMaxWidth()) {
        GroundLevelDiagram(Modifier.fillMaxWidth().height(220.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text("6–12 in", style = CaptureNumeric, color = CaptureInk)
            Text("0–45° ↗", style = CaptureNumeric, color = CaptureAccentBright)
        }
    }
    Text("Hold your phone low, tilt it up.", style = MaterialTheme.typography.bodySmall, color = MutedGray)
    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        listOf(R.drawable.gallery_bad_01_eyelevel, R.drawable.gallery_bad_02_topdown).forEach { image ->
            Box(Modifier.weight(1f).aspectRatio(1.3f).clip(CaptureRadii.lg)) {
                Image(painterResource(image), if (image == R.drawable.gallery_bad_01_eyelevel) "Incorrect eye-level view" else "Incorrect top-down view", Modifier.matchParentSize(), contentScale = ContentScale.Crop)
                Text("×", color = ErrorRed, style = CaptureNumeric,
                    modifier = Modifier.align(Alignment.TopEnd).padding(8.dp).background(CaptureBase.copy(alpha = .8f), CaptureRadii.pill).padding(horizontal = 8.dp))
            }
        }
    }
}

@Composable
private fun GroundLevelDiagram(modifier: Modifier) {
    Canvas(modifier) {
        val w = size.width
        val h = size.height
        drawRect(CaptureSurface2, Offset(0f, h / 3), Size(w, h * 2 / 3))
        drawLine(MutedGray.copy(alpha = .5f), Offset(0f, h / 3), Offset(w, h / 3), 1.dp.toPx())
        val vanish = Offset(w * .7f, h / 3)
        repeat(5) { drawLine(CaptureAccent.copy(alpha = .12f), vanish, Offset(w * it / 4, h), 1.dp.toPx()) }
        val phone = Offset(w * .3f, h * .58f)
        drawRoundRect(CaptureBase, phone, Size(w * .13f, h * .3f), CornerRadius(8.dp.toPx()))
        drawRoundRect(CaptureAccent, phone, Size(w * .13f, h * .3f), CornerRadius(8.dp.toPx()), style = Stroke(2.dp.toPx()))
        val lens = Offset(w * .365f, h * .62f)
        drawCircle(CaptureAccent, 3.dp.toPx(), lens)
        val end = Offset(w * .8f, h * .16f)
        val cone = Path().apply { moveTo(lens.x, lens.y); lineTo(w * .88f, h * .1f); lineTo(w * .88f, h * .6f); close() }
        drawPath(cone, CaptureAccent.copy(alpha = .08f))
        drawLine(CaptureAccent, lens, end, 2.dp.toPx(), StrokeCap.Round)
        val x = w * .18f
        drawLine(CaptureAccent, Offset(x, lens.y), Offset(x, h), 2.dp.toPx())
        listOf(lens.y, h - 2.dp.toPx()).forEach { y -> drawLine(CaptureAccent, Offset(x - 8.dp.toPx(), y), Offset(x + 8.dp.toPx(), y), 2.dp.toPx()) }
    }
}

@Composable
private fun TutorialWhatToCaptureScreen() {
    Text("What to capture", style = MaterialTheme.typography.displaySmall)
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        listOf(Triple(R.drawable.gallery_good_03_livingroom, "OBJECTS", CaptureSymbol.OBJECT),
            Triple(R.drawable.gallery_good_01_doorway, "PLACES", CaptureSymbol.PLACE),
            Triple(R.drawable.gallery_good_02_stairs, "ACTIONS", CaptureSymbol.MOTION)).forEach { (image, label, icon) ->
            Box(Modifier.weight(1f).aspectRatio(.42f).clip(CaptureRadii.lg)) {
                Image(painterResource(image), label, Modifier.matchParentSize(), contentScale = ContentScale.Crop)
                Box(Modifier.matchParentSize().background(Brush.verticalGradient(listOf(Color.Transparent, CaptureBase.copy(alpha = .9f)))))
                Column(Modifier.align(Alignment.BottomStart).padding(10.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    CaptureIcon(icon, Modifier.size(22.dp), CaptureInk)
                    Text(label, style = MaterialTheme.typography.labelSmall, color = MutedGray)
                }
            }
        }
    }
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
        listOf(CaptureSymbol.SURFACE to "Surface", CaptureSymbol.LIGHT to "Lighting", CaptureSymbol.WEATHER to "Weather", CaptureSymbol.MOTION to "Motion").forEach { (icon, label) ->
            Box(Modifier.size(48.dp).background(CaptureSurface2, CaptureRadii.pill), contentAlignment = Alignment.Center) {
                CaptureIcon(icon, Modifier.size(22.dp), description = label)
            }
        }
    }
}

@Composable
private fun TutorialLabelingScreen() {
    Text("Labeling", style = MaterialTheme.typography.displaySmall)
    Box(Modifier.fillMaxWidth().aspectRatio(.85f).clip(CaptureRadii.xl)) {
        Image(painterResource(R.drawable.gallery_good_01_doorway), "Doorway capture with labels", Modifier.matchParentSize(), contentScale = ContentScale.Crop)
        Box(Modifier.fillMaxWidth(.65f).fillMaxHeight(.6f).align(Alignment.Center).border(1.dp, CaptureAccentBright, CaptureRadii.sm))
        Column(Modifier.align(Alignment.BottomStart).padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf("PRIMARY · PLACE", "POSTURE · REQUIRED", "SECONDARY · OPTIONAL").forEach { label ->
                Text(label, style = MaterialTheme.typography.labelSmall, color = CaptureInk,
                    modifier = Modifier.background(CaptureBase.copy(alpha = .85f), CaptureRadii.pill).border(1.dp, CaptureAccentBorder, CaptureRadii.pill).padding(horizontal = 12.dp, vertical = 8.dp))
            }
        }
    }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        listOf("PHOTO" to "$0.10", "5–15 SEC" to "$0.25", "15–30 SEC" to "$0.40").forEach { (label, amount) ->
            Column(Modifier.weight(1f).background(CaptureSurface2, CaptureRadii.md).padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(amount, style = CaptureNumeric.copy(fontSize = 20.sp), color = CaptureInk)
                Text(label, style = MaterialTheme.typography.labelSmall, color = MutedGray)
            }
        }
    }
}

@Composable
private fun TutorialEarnLevelScreen() {
    EditorialHeading("EARN & LEVEL.")
    EditorialTierLadder(Modifier.fillMaxWidth())
    Text(
        "Meet both requirements to level up. Approval rate: last 50 judged submissions.",
        style = MaterialTheme.typography.bodySmall,
        color = MutedGray,
    )
}
