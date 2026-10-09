package ai.loosh.union

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontVariation
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.TextUnitType
import androidx.compose.ui.unit.sp

/**
 * Capture brand palette (BRAND-v1.md, exact hex) and typography (Sora + Archivo
 * Black). Replaces the old green `UnionColors` scheme; the four vivid hues map
 * to the 2x2 grid — orange / cyan / violet / magenta — and are applied either
 * through this scheme (primary/secondary/tertiary) or explicitly in the
 * composables where a specific accent has a specific meaning (cyan = bounding
 * boxes, violet = primary label chips, magenta = secondary chips / selection).
 */

val CaptureBase = Color(0xFF0A0A10)
val CaptureOnBase = Color(0xFFFFFFFF)
val AccentOrange = Color(0xFFFF6A00)
val AccentCyan = Color(0xFF00D9FF)
val AccentViolet = Color(0xFF6C2BD9)
val AccentMagenta = Color(0xFFFF2D95)
val MutedGray = Color(0xFF9A9AA6)
val ErrorRed = Color(0xFFFF6B6B)
val WarnAmber = Color(0xFFFBBF24)

val CaptureColors = darkColorScheme(
    primary = AccentOrange,
    onPrimary = Color(0xFF2A0E00),
    primaryContainer = AccentOrange,
    onPrimaryContainer = Color(0xFF2A0E00),
    secondary = AccentViolet,
    onSecondary = Color(0xFFFFFFFF),
    secondaryContainer = AccentViolet,
    onSecondaryContainer = Color(0xFFFFFFFF),
    tertiary = AccentMagenta,
    onTertiary = Color(0xFFFFFFFF),
    tertiaryContainer = AccentMagenta,
    onTertiaryContainer = Color(0xFFFFFFFF),
    background = CaptureBase,
    onBackground = Color(0xFFF2F2F7),
    surface = Color(0xFF14121E),
    onSurface = Color(0xFFF2F2F7),
    surfaceVariant = Color(0xFF1E1B2C),
    onSurfaceVariant = MutedGray,
    outline = Color(0xFF2A2736),
    outlineVariant = Color(0xFF1E1B2C),
    error = ErrorRed,
    onError = Color(0xFF2A0505),
)

private val Sora = FontFamily(
    Font(
        resId = R.font.sora,
        weight = FontWeight.W400,
        variationSettings = FontVariation.Settings(FontVariation.weight(400)),
    ),
    Font(
        resId = R.font.sora,
        weight = FontWeight.W500,
        variationSettings = FontVariation.Settings(FontVariation.weight(500)),
    ),
    Font(
        resId = R.font.sora,
        weight = FontWeight.W600,
        variationSettings = FontVariation.Settings(FontVariation.weight(600)),
    ),
)

private val ArchivoBlack = FontFamily(
    Font(resId = R.font.archivo_black, weight = FontWeight.W900)
)

/** All-caps display face with the brand's +8% letter-spacing. */
private fun display(size: Int) =
    TextStyle(
        fontFamily = ArchivoBlack,
        fontWeight = FontWeight.Black,
        fontSize = size.sp,
        letterSpacing = TextUnit(0.08f, TextUnitType.Em),
    )

val CaptureTypography = Typography(
    displayLarge = display(57),
    displayMedium = display(45),
    displaySmall = display(36),
    headlineLarge = display(32),
    headlineMedium = display(28),
    headlineSmall = display(24),
    titleLarge = display(22),
    titleMedium = TextStyle(fontFamily = Sora, fontWeight = FontWeight.SemiBold, fontSize = 16.sp),
    titleSmall = TextStyle(fontFamily = Sora, fontWeight = FontWeight.Medium, fontSize = 14.sp),
    bodyLarge = TextStyle(fontFamily = Sora, fontWeight = FontWeight.Normal, fontSize = 16.sp),
    bodyMedium = TextStyle(fontFamily = Sora, fontWeight = FontWeight.Normal, fontSize = 14.sp),
    bodySmall = TextStyle(fontFamily = Sora, fontWeight = FontWeight.Normal, fontSize = 12.sp),
    labelLarge = TextStyle(fontFamily = Sora, fontWeight = FontWeight.Medium, fontSize = 14.sp),
    labelMedium = TextStyle(fontFamily = Sora, fontWeight = FontWeight.Medium, fontSize = 12.sp),
    labelSmall = TextStyle(fontFamily = Sora, fontWeight = FontWeight.Medium, fontSize = 11.sp),
)

@Composable
fun CaptureTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = CaptureColors,
        typography = CaptureTypography,
        content = content,
    )
}
