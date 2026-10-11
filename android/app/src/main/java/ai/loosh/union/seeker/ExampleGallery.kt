package ai.loosh.union.seeker

import ai.loosh.union.*
import ai.loosh.union.R
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.grid.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties

private data class CaptureExample(val image: Int, val good: Boolean, val title: String, val reason: String)
private val examples = listOf(
    CaptureExample(R.drawable.gallery_good_01_doorway, true, "Doorway", "Floor visible · horizon upper third."),
    CaptureExample(R.drawable.gallery_good_02_stairs, true, "Stairs", "Safety-critical · continuous motion."),
    CaptureExample(R.drawable.gallery_good_03_livingroom, true, "Living room", "Legs-only is the normal view."),
    CaptureExample(R.drawable.gallery_bad_01_eyelevel, false, "Eye-level", "Eye-level → get lower."),
    CaptureExample(R.drawable.gallery_bad_02_topdown, false, "Top-down", "Top-down → aim 0–45° up."),
    CaptureExample(R.drawable.gallery_bad_03_dark, false, "Dark / blurry", "Too dark / blurry."),
)

@Composable
fun ExampleGalleryScreen(onBack: () -> Unit, reason: String? = null) {
    var selected by rememberSaveable { mutableStateOf<Int?>(null) }
    BackHandler(onBack = onBack)
    val grid = rememberLazyGridState()
    LaunchedEffect(reason) {
        val index = when {
            reason?.contains("eye", ignoreCase = true) == true -> 3
            reason?.contains("top", ignoreCase = true) == true || reason?.contains("pitch", ignoreCase = true) == true -> 4
            reason?.contains("dark", ignoreCase = true) == true || reason?.contains("blur", ignoreCase = true) == true || reason?.contains("exposure", ignoreCase = true) == true -> 5
            else -> null
        }
        index?.let { grid.animateScrollToItem(it + 1); selected = it }
    }
    NavyBackground(Modifier.fillMaxSize().captureScreenMotion()) {
        Column(Modifier.fillMaxSize().safeDrawingPadding()) {
            Row(Modifier.fillMaxWidth().captureGlass().padding(horizontal = 20.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween) {
                TextButton(onClick = onBack) { Text("← Back") }
                CaptureMark(Modifier.size(28.dp))
            }
            LazyVerticalGrid(columns = GridCells.Fixed(2), state = grid, contentPadding = PaddingValues(20.dp),
                horizontalArrangement = Arrangement.spacedBy(12.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                item(span = { GridItemSpan(maxLineSpan) }) {
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("Find your frame", style = MaterialTheme.typography.displaySmall)
                        Text("Ground-level egocentric capture", style = MaterialTheme.typography.labelSmall, color = MutedGray)
                    }
                }
                itemsIndexed(examples, key = { _, example -> example.image }) { index, example ->
                    GalleryCard(example, Modifier.clickable { selected = index })
                }
            }
        }
    }
    selected?.let { index ->
        val example = examples[index]
        Dialog(onDismissRequest = { selected = null }, properties = DialogProperties(usePlatformDefaultWidth = false)) {
            NavyBackground(Modifier.fillMaxSize()) {
                // Fit preserves the horizon and low-angle framing of the teaching image.
                Image(painterResource(example.image), example.title, Modifier.fillMaxSize(), contentScale = ContentScale.Fit)
                Column(Modifier.align(Alignment.BottomCenter).fillMaxWidth()
                    .background(Brush.verticalGradient(listOf(Color.Transparent, CaptureBase)))
                    .safeDrawingPadding().padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    VerdictBadge(example.good)
                    Text(example.reason, style = MaterialTheme.typography.bodySmall, color = MutedGray)
                }
                TextButton(onClick = { selected = null }, modifier = Modifier.align(Alignment.TopStart).safeDrawingPadding().padding(12.dp)
                    .background(CaptureBase.copy(alpha = .8f), CaptureRadii.pill)) { Text("← Gallery", color = CaptureInk) }
            }
        }
    }
}

@Composable
private fun GalleryCard(example: CaptureExample, modifier: Modifier = Modifier) {
    val tint = if (example.good) SuccessGreen else ErrorRed
    Box(modifier.fillMaxWidth().aspectRatio(9f / 16f).clip(CaptureRadii.lg)
        .border(1.dp, tint.copy(alpha = .6f), CaptureRadii.lg)) {
        Image(painterResource(example.image), example.title, Modifier.matchParentSize(), contentScale = ContentScale.Crop)
        Box(Modifier.align(Alignment.BottomCenter).fillMaxWidth().fillMaxHeight(.4f)
            .background(Brush.verticalGradient(listOf(Color.Transparent, CaptureBase.copy(alpha = .95f)))))
        Box(Modifier.align(Alignment.TopStart).padding(8.dp)) { VerdictBadge(example.good) }
        Text(example.reason, modifier = Modifier.align(Alignment.BottomStart).padding(12.dp),
            style = MaterialTheme.typography.labelSmall, color = MutedGray)
    }
}
