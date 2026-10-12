package ai.loosh.union.seeker

import ai.loosh.union.*
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.math.cos
import kotlin.math.sin

/** Blue speed-line chevrons pointing right, per the "POP EDITORIAL" heroes. */
@Composable
fun SpeedLines(modifier: Modifier = Modifier, tint: Color = CaptureAccent) {
    Canvas(modifier) {
        val u = size.minDimension / 24f
        fun chevron(x: Float, y: Float) {
            val p = Path().apply {
                moveTo(x, y); lineTo(x + 5f * u, y + 3f * u); lineTo(x, y + 6f * u)
            }
            drawPath(p, tint, style = Stroke(1.8f * u, cap = StrokeCap.Round))
        }
        chevron(2f * u, 4f * u)
        chevron(8f * u, 2f * u)
        chevron(14f * u, 8f * u)
    }
}

/** A big editorial headline: black all-caps text + speed lines on the right. */
@Composable
fun EditorialHeading(text: String, modifier: Modifier = Modifier) {
    Row(modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(
            text,
            style = MaterialTheme.typography.displayMedium,
            color = CaptureInk,
            modifier = Modifier.weight(1f),
        )
        SpeedLines(Modifier.size(96.dp, 28.dp))
    }
}

/** The tier icon for a level rung, drawn as a white glyph inside a blue circle. */
@Composable
fun TierIcon(level: Int, modifier: Modifier = Modifier) {
    Canvas(modifier) {
        val u = size.minDimension / 24f
        val cx = size.width / 2f
        val cy = size.height / 2f
        drawCircle(CaptureAccent, size.minDimension / 2f, Offset(cx, cy))
        val glyph = Color.White
        fun stroke(p: Path) = drawPath(p, glyph, style = Stroke(1.7f * u, cap = StrokeCap.Round, join = androidx.compose.ui.graphics.StrokeJoin.Round))
        when (level) {
            0 -> { // compass
                drawCircle(glyph, 6f * u, Offset(cx, cy), style = Stroke(1.7f * u))
                stroke(Path().apply { moveTo(cx, cy - 4f * u); lineTo(cx + 3f * u, cy - 1f * u); lineTo(cx, cy + 4f * u); lineTo(cx - 3f * u, cy - 1f * u); close() })
            }
            1 -> { // refresh arrows
                val p = Path().apply {
                    moveTo(8f * u, 7f * u); lineTo(16f * u, 7f * u)
                    moveTo(13f * u, 4f * u); lineTo(16f * u, 7f * u); lineTo(13f * u, 10f * u)
                    moveTo(16f * u, 17f * u); lineTo(8f * u, 17f * u)
                    moveTo(11f * u, 14f * u); lineTo(8f * u, 17f * u); lineTo(11f * u, 20f * u)
                }
                stroke(p)
            }
            2 -> { // shield with check
                val p = Path().apply {
                    moveTo(cx, 5f * u)
                    lineTo(17f * u, 8f * u)
                    lineTo(17f * u, 13f * u)
                    quadraticTo(17f * u, 18f * u, cx, 20f * u)
                    quadraticTo(7f * u, 18f * u, 7f * u, 13f * u)
                    lineTo(7f * u, 8f * u)
                    close()
                }
                stroke(p)
                stroke(Path().apply { moveTo(9f * u, 13f * u); lineTo(12f * u, 16f * u); lineTo(16f * u, 10f * u) })
            }
            3 -> { // star ribbon
                val p = Path()
                for (i in 0 until 5) {
                    val a = -kotlin.math.PI / 2 + i * 2 * kotlin.math.PI / 5
                    val x = cx + 6f * u * cos(a).toFloat()
                    val y = cy + 6f * u * sin(a).toFloat()
                    if (i == 0) p.moveTo(x, y) else p.lineTo(x, y)
                }
                p.close()
                stroke(p)
            }
            else -> { // winding path arrow
                val p = Path().apply {
                    moveTo(5f * u, 15f * u)
                    cubicTo(9f * u, 15f * u, 9f * u, 7f * u, 13f * u, 7f * u)
                    cubicTo(16f * u, 7f * u, 16f * u, 11f * u, 19f * u, 11f * u)
                }
                stroke(p)
                stroke(Path().apply { moveTo(19f * u, 8f * u); lineTo(19f * u, 11f * u); lineTo(22f * u, 11f * u) })
            }
        }
    }
}

/** One rung of the judge-accuracy ladder (incentive spec §4), editorial-styled. */
@Composable
fun JudgeTierRow(tier: JudgeTier, active: Boolean, modifier: Modifier = Modifier) {
    val requirement = tier.rateThreshold?.let { "≥${agreementPercent(it)}% agreement" } ?: "No gate"
    Row(
        modifier.fillMaxWidth().padding(vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        TierIcon(tier.level, Modifier.size(40.dp))
        Column(Modifier.weight(1f).padding(start = 12.dp)) {
            Text(
                tier.name,
                style = MaterialTheme.typography.titleSmall,
                color = if (active) CaptureAccentBright else CaptureInk,
            )
            Text(requirement, style = MaterialTheme.typography.bodySmall, color = MutedGray)
        }
        Text("×${"%.2f".format(tier.rateMultiplier)}", style = MaterialTheme.typography.titleSmall, color = CaptureAccentBright)
    }
}

/** The judge level ladder: agreement rate drives status and payout rate (§4). */
@Composable
fun JudgeTierLadder(currentLevel: Int, modifier: Modifier = Modifier) {
    CapturePanel(modifier.fillMaxWidth()) {
        Text("LEVEL LADDER", style = MaterialTheme.typography.labelMedium, color = CaptureAccentBright)
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text("LEVEL", style = MaterialTheme.typography.labelMedium, color = MutedGray, modifier = Modifier.weight(1f))
            Text("AGREEMENT · RATE", style = MaterialTheme.typography.labelMedium, color = MutedGray)
        }
        JUDGE_TIERS.forEach { tier ->
            JudgeTierRow(tier, active = tier.level == currentLevel)
        }
        Text(
            "Agreement rate: rolling last 100 judged pairs. Status is free; only the rate multiplier costs money.",
            style = MaterialTheme.typography.bodySmall,
            color = MutedGray,
        )
    }
}


