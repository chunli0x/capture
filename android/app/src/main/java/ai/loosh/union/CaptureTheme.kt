package ai.loosh.union

import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp

// Capture "POP EDITORIAL" identity — the progression + access screen system.
// Palette from the design: cream #FDFBF7 ground, royal blue #2563EB accent,
// black #111111 editorial ink, grey #6B7280 secondary, and red/yellow as
// SEMANTIC colors (error bg #FECDD3 / text #BE123C; warning bg #FDE047 /
// text #854D0E). No decorative red/yellow in the chrome.

val CaptureBaseDeep = Color(0xFFF4EDDD)
val CaptureBase = Color(0xFFFDFBF7)
val CaptureSurface = Color(0xFFFFFFFF)
val CaptureSurface2 = Color(0xFFF4EDDD)
val CaptureSurface3 = Color(0xFFEAE0C8)
val CaptureInk = Color(0xFF111111)
val CaptureOnBase = CaptureInk
val MutedGray = Color(0xFF6B7280)
val CaptureInkFaint = Color(0xFF9CA3AF)
val CaptureOutline = Color(0xFFE5E7EB)
val CaptureOutlineVariant = Color(0xFFD1D5DB)
val CaptureAccent = Color(0xFF2563EB)
val CaptureAccentBright = Color(0xFF3B82F6)
val CaptureAccentDeep = Color(0xFF1D4ED8)
val CaptureAccentTint = CaptureAccent.copy(alpha = .12f)
val CaptureAccentBorder = CaptureAccent.copy(alpha = .35f)
// Semantic: red = error, yellow = warning.
val CaptureRed = Color(0xFFBE123C)
val CaptureRedBg = Color(0xFFFECDD3)
val CaptureYellow = Color(0xFFFDE047)
val CaptureYellowInk = Color(0xFF854D0E)
val SuccessGreen = Color(0xFF16A34A)
val ErrorRed = Color(0xFFBE123C)
val ErrorRedBg = Color(0xFFFECDD3)
val WarnAmber = Color(0xFF854D0E)
val WarnAmberBg = Color(0xFFFDE047)
// Button grey (secondary / disabled CTA).
val ButtonGrey = Color(0xFFE5E7EB)
val ButtonGreyInk = Color(0xFF374151)

object CaptureGradients {
    val navy = Brush.verticalGradient(listOf(CaptureBaseDeep, CaptureBase))
    val action = Brush.verticalGradient(listOf(CaptureAccent, CaptureAccentDeep))
    val actionGlow = Brush.radialGradient(listOf(CaptureAccentBright.copy(alpha = .18f), CaptureAccent.copy(alpha = .02f)))
    val ring = Brush.sweepGradient(listOf(CaptureAccentBright, CaptureAccent, CaptureAccentDeep, CaptureAccentBright))
    val glass = Brush.verticalGradient(listOf(CaptureInk.copy(alpha = .05f), CaptureInk.copy(alpha = .02f)))
}
object CaptureMotion {
    const val fast = 120
    const val base = 220
    const val slow = 360
    const val celebrate = 700
    val easing = FastOutSlowInEasing
    val progressEasing = CubicBezierEasing(0.2f, 0f, 1f, 1f)
}
object CaptureRadii {
    val sm = RoundedCornerShape(12.dp)
    val md = RoundedCornerShape(16.dp)
    val lg = RoundedCornerShape(20.dp)
    val xl = RoundedCornerShape(24.dp)
    val pill = RoundedCornerShape(50)
}
val CaptureColors = lightColorScheme(
    primary = CaptureAccent, onPrimary = Color.White,
    primaryContainer = CaptureAccentTint, onPrimaryContainer = CaptureInk,
    secondary = CaptureAccentDeep, onSecondary = Color.White,
    secondaryContainer = CaptureSurface2, onSecondaryContainer = CaptureInk,
    tertiary = CaptureAccent, onTertiary = Color.White,
    tertiaryContainer = CaptureSurface3, onTertiaryContainer = CaptureInk,
    background = CaptureBase, onBackground = CaptureInk,
    surface = CaptureSurface, onSurface = CaptureInk,
    surfaceVariant = CaptureSurface2, onSurfaceVariant = MutedGray,
    surfaceDim = CaptureBaseDeep, surfaceBright = CaptureSurface,
    surfaceContainerLowest = CaptureBaseDeep, surfaceContainerLow = CaptureSurface,
    surfaceContainer = CaptureSurface, surfaceContainerHigh = CaptureSurface2,
    surfaceContainerHighest = CaptureSurface3,
    outline = CaptureOutline, outlineVariant = CaptureOutlineVariant,
    error = ErrorRed, onError = Color.White,
)
val Inter = FontFamily(
    Font(R.font.inter_400, FontWeight.Normal),
    Font(R.font.inter_500, FontWeight.Medium),
    Font(R.font.inter_600, FontWeight.SemiBold),
    Font(R.font.inter_700, FontWeight.Bold),
    Font(R.font.inter_800, FontWeight.ExtraBold),
)
private fun inter(size: Int, line: Float, weight: FontWeight = FontWeight.Normal, tracking: Float = 0f) = TextStyle(
    fontFamily = Inter, fontWeight = weight, fontSize = size.sp,
    lineHeight = (size * line).sp, letterSpacing = tracking.em,
)
val CaptureNumeric = inter(28, 1f, FontWeight.Bold).copy(fontFeatureSettings = "tnum")
val CaptureTypography = Typography(
    displayLarge = inter(40, 1f, FontWeight.ExtraBold, -.01f),
    displayMedium = inter(34, 1.05f, FontWeight.ExtraBold, -.01f),
    displaySmall = inter(28, 1.1f, FontWeight.ExtraBold, -.005f),
    headlineLarge = inter(28, 1.1f, FontWeight.ExtraBold, -.005f),
    headlineMedium = inter(22, 1.15f, FontWeight.Bold),
    headlineSmall = inter(17, 1.25f, FontWeight.Bold),
    titleLarge = inter(16, 1.3f, FontWeight.SemiBold),
    titleMedium = inter(15, 1.35f, FontWeight.SemiBold),
    titleSmall = inter(15, 1.35f, FontWeight.SemiBold),
    bodyLarge = inter(15, 1.5f), bodyMedium = inter(13, 1.5f), bodySmall = inter(13, 1.5f),
    labelLarge = inter(11, 1.2f, FontWeight.SemiBold, .08f),
    labelMedium = inter(11, 1.2f, FontWeight.SemiBold, .08f),
    labelSmall = inter(11, 1.3f, FontWeight.Medium, .02f),
)
@Composable
fun CaptureTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = CaptureColors, typography = CaptureTypography,
        shapes = Shapes(CaptureRadii.sm, CaptureRadii.md, CaptureRadii.lg, CaptureRadii.xl, CaptureRadii.xl), content = content)
}
