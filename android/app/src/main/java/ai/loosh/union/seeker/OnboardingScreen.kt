package ai.loosh.union.seeker

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier

/** Keep the existing first-run preference gate; the intro precedes the four tutorial steps. */
@Composable
fun OnboardingScreen(onDone: () -> Unit) = IntroConstellationScreen(onDone)

@Composable
fun BrandLogo(modifier: Modifier = Modifier) = CaptureMark(modifier)
