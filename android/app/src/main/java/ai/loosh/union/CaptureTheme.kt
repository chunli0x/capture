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

val CaptureBaseDeep = Color(0xFF0A0B10)
val CaptureBase = Color(0xFF0F1219)
val CaptureSurface = Color(0xFF141824)
val CaptureSurface2 = Color(0xFF1B2030)
val CaptureSurface3 = Color(0xFF232A3D)
val CaptureOutline = Color(0xFF262C3D)
val CaptureOutlineVariant = CaptureSurface2
val CaptureInk = Color(0xFFFFFFFF)
val CaptureOnBase = CaptureInk
val MutedGray = Color(0xFF9CA3AF)
val CaptureInkFaint = Color(0xFF6B7280)
val CaptureAccent = Color(0xFF3B82F6)
val CaptureAccentBright = Color(0xFF60A5FA)
val CaptureAccentDeep = Color(0xFF2563EB)
val CaptureAccentTint = CaptureAccent.copy(alpha = .12f)
val CaptureAccentBorder = CaptureAccent.copy(alpha = .35f)
val SuccessGreen = Color(0xFF34D399)
val ErrorRed = Color(0xFFF87171)
val WarnAmber = Color(0xFFF59E0B)

object CaptureGradients {
    val navy = Brush.verticalGradient(listOf(CaptureBaseDeep, CaptureBase))
    val action = Brush.verticalGradient(listOf(CaptureAccent, CaptureAccentDeep))
    val actionGlow = Brush.radialGradient(listOf(CaptureAccentBright.copy(alpha = .22f), CaptureAccent.copy(alpha = .02f)))
    val ring = Brush.sweepGradient(listOf(CaptureAccentBright, CaptureAccent, CaptureAccentDeep, CaptureAccentBright))
    val glass = Brush.verticalGradient(listOf(CaptureInk.copy(alpha = .10f), CaptureInk.copy(alpha = .04f)))
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
val CaptureColors = darkColorScheme(
    primary = CaptureAccent, onPrimary = CaptureInk,
    primaryContainer = CaptureAccentTint, onPrimaryContainer = CaptureInk,
    secondary = CaptureAccentBright, onSecondary = CaptureBase,
    secondaryContainer = CaptureSurface2, onSecondaryContainer = CaptureInk,
    tertiary = CaptureAccent, onTertiary = CaptureInk,
    tertiaryContainer = CaptureSurface3, onTertiaryContainer = CaptureInk,
    background = CaptureBase, onBackground = CaptureInk,
    surface = CaptureSurface, onSurface = CaptureInk,
    surfaceVariant = CaptureSurface2, onSurfaceVariant = MutedGray,
    surfaceDim = CaptureBaseDeep, surfaceBright = CaptureSurface3,
    surfaceContainerLowest = CaptureBaseDeep, surfaceContainerLow = CaptureSurface,
    surfaceContainer = CaptureSurface, surfaceContainerHigh = CaptureSurface2,
    surfaceContainerHighest = CaptureSurface3,
    outline = CaptureOutline, outlineVariant = CaptureOutlineVariant,
    error = ErrorRed, onError = CaptureBase,
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
