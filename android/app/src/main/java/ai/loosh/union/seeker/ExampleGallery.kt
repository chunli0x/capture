package ai.loosh.union.seeker

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp
import ai.loosh.union.AccentCyan
import ai.loosh.union.ErrorRed
import ai.loosh.union.MutedGray

/**
 * Good-vs-bad capture examples, shown as a gallery. Illustrates the ground-level
 * rule (camera angle) and the quality bar (light, focus) with simple side-view
 * diagrams and short explanations — no animal, pet, or robot imagery or copy.
 */
@Composable
fun ExampleGalleryScreen(onBack: () -> Unit) {
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = onBack) { Text("← Back") }
            Text(
                "Capture examples",
                style = MaterialTheme.typography.titleLarge,
                color = MaterialTheme.colorScheme.onBackground,
            )
        }

        Column(
            Modifier
                .fillMaxWidth()
                .weight(1f)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            ExampleCard(
                good = true,
                title = "Low camera, floor in the bottom",
                body = "Hold the lens 6–12 in off the ground and tilt it slightly up. The horizon rides high in the frame.",
                mode = AngleMode.LOW,
            )
            ExampleCard(
                good = true,
                title = "Even lighting, sharp subject",
                body = "Natural or indoor light, subject in focus, no motion blur, natural color.",
                mode = null,
            )
            ExampleCard(
                good = false,
                title = "Eye-level shot",
                body = "Camera at chest height, with the horizon at mid-frame. Rejected — this is not the ground-level view.",
                mode = AngleMode.EYE,
            )
            ExampleCard(
                good = false,
                title = "Pointed straight down",
                body = "Looking straight at the floor. Rejected — Capture needs the forward, low view, not a top-down one.",
                mode = AngleMode.DOWN,
            )
            ExampleCard(
                good = false,
                title = "Dark or blown out",
                body = "Underexposed or clipped highlights erase the detail the model learns from.",
                mode = null,
            )
            ExampleCard(
                good = false,
                title = "Blurry",
                body = "Motion blur or soft focus across the whole frame. Keep the subject sharp.",
                mode = null,
            )
            Spacer(Modifier.height(12.dp))
        }
    }
}

private enum class AngleMode(val good: Boolean) {
    LOW(true),
    EYE(false),
    DOWN(false),
}

@Composable
private fun ExampleCard(good: Boolean, title: String, body: String, mode: AngleMode?) {
    val tint = if (good) AccentCyan else ErrorRed
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Text(title, style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.onSurface)
                Text(
                    if (good) "GOOD" else "BAD",
                    style = MaterialTheme.typography.labelSmall,
                    color = tint,
                )
            }
            if (mode != null) {
                AngleDiagram(mode, Modifier.fillMaxWidth().height(90.dp))
            }
            Text(body, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.75f))
        }
    }
}

/**
 * Side-view diagram: a ground line, a camera box at the appropriate height, and
 * a view-direction arrow. LOW shows the camera near the ground pitched slightly
 * up; EYE shows it at mid-height level; DOWN shows a steep downward pitch.
 */
@Composable
private fun AngleDiagram(mode: AngleMode, modifier: Modifier = Modifier) {
    val color = if (mode.good) AccentCyan else ErrorRed
    Canvas(modifier) {
        val w = size.width
        val h = size.height
        val groundY = h * 0.85f
        drawLine(
            MutedGray.copy(alpha = 0.5f),
            Offset(0f, groundY),
            Offset(w, groundY),
            2.dp.toPx(),
        )
        val camY =
            when (mode) {
                AngleMode.LOW -> groundY - h * 0.20f
                AngleMode.EYE -> groundY - h * 0.45f
                AngleMode.DOWN -> groundY - h * 0.45f
            }
        val camX = w * 0.15f
        drawRoundRect(
            color = color,
            topLeft = Offset(camX, camY - h * 0.07f),
            size = Size(w * 0.16f, h * 0.14f),
            cornerRadius = CornerRadius(6f, 6f),
        )
        val pitch =
            when (mode) {
                AngleMode.LOW -> -0.45f
                AngleMode.EYE -> 0f
                AngleMode.DOWN -> 0.95f
            }
        val start = Offset(camX + w * 0.16f, camY)
        val end = Offset(camX + w * 0.62f, camY + pitch * h * 0.45f)
        drawLine(color.copy(alpha = 0.75f), start, end, 3.dp.toPx(), StrokeCap.Round)
        drawCircle(color.copy(alpha = 0.75f), radius = 3.dp.toPx(), center = end, style = Stroke(1.5.dp.toPx()))
    }
}
