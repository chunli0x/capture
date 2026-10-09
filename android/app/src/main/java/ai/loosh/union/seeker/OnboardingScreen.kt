package ai.loosh.union.seeker

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ai.loosh.union.AccentCyan
import ai.loosh.union.AccentMagenta
import ai.loosh.union.AccentOrange
import ai.loosh.union.AccentViolet
import ai.loosh.union.MutedGray
import kotlinx.coroutines.launch

/**
 * First-run onboarding: a swipe pager shown *before* the wallet gate. Establishes
 * what Capture is and what a pilot worker does, then a single CTA drops into the
 * existing wallet-connect form. A returning user never sees it again (the
 * "onboarded" preference gate lives in [SeekerApp]).
 */
@Composable
fun OnboardingScreen(onDone: () -> Unit) {
    val pagerState = rememberPagerState(pageCount = { 4 })
    val scope = rememberCoroutineScope()
    val lastPage = pagerState.currentPage == 3

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 24.dp, vertical = 32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Spacer(Modifier.weight(1f))

        HorizontalPager(
            state = pagerState,
            modifier = Modifier.fillMaxWidth().weight(6f),
        ) { page ->
            when (page) {
                0 -> OnboardingPage(
                    title = "CAPTURE",
                    headline = "Ground truth, from the ground up.",
                    body = "Capture the world at ground level, label it, and get paid.",
                    showLogo = true,
                )
                1 -> OnboardingPage(
                    title = "HOW IT WORKS",
                    headline = "Three steps, start to finish.",
                    body = "",
                    steps = listOf(
                        "1" to "Capture — a photo or a ≤30s clip, camera held low.",
                        "2" to "Label — pick the object, place, or action; add optional context.",
                        "3" to "Get paid — USDC to your wallet, secured by a slashable SKR bond.",
                    ),
                )
                2 -> OnboardingPage(
                    title = "YOUR WALLET IS THE ACCOUNT",
                    headline = "No email. No password.",
                    body = "Signing in uses the wallet already on your Solana Seeker Mobile. Rewards for this pilot are devnet TEST-USDC.",
                )
                else -> OnboardingPage(
                    title = "READY",
                    headline = "You're all set.",
                    body = "Sign in with your wallet to start capturing.",
                )
            }
        }

        Spacer(Modifier.height(24.dp))

        // Page indicator dots in the primary accent.
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            repeat(4) { index ->
                val active = pagerState.currentPage == index
                Box(
                    Modifier
                        .size(if (active) 22.dp else 8.dp, 8.dp)
                        .background(
                            color = if (active) AccentOrange else MutedGray.copy(alpha = 0.4f),
                            shape = CircleShape,
                        ),
                )
            }
        }

        Spacer(Modifier.height(24.dp))

        Button(
            onClick = {
                if (lastPage) onDone()
                else scope.launch { pagerState.animateScrollToPage(pagerState.currentPage + 1) }
            },
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text(
                when {
                    lastPage -> "Sign in with wallet"
                    pagerState.currentPage == 0 -> "Get started"
                    else -> "Continue"
                },
                style = MaterialTheme.typography.labelLarge,
            )
        }

        Spacer(Modifier.weight(1f))
    }
}

@Composable
private fun OnboardingPage(
    title: String,
    headline: String,
    body: String,
    showLogo: Boolean = false,
    steps: List<Pair<String, String>> = emptyList(),
) {
    Column(
        modifier = Modifier.fillMaxSize(),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        if (showLogo) {
            BrandLogo(Modifier.size(96.dp))
            Spacer(Modifier.height(20.dp))
        }
        Text(
            title,
            style = MaterialTheme.typography.headlineSmall,
            color = MaterialTheme.colorScheme.onBackground,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(12.dp))
        Text(
            headline,
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.onSurface,
            textAlign = TextAlign.Center,
        )
        if (body.isNotBlank()) {
            Spacer(Modifier.height(8.dp))
            Text(
                body,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.65f),
                textAlign = TextAlign.Center,
            )
        }
        if (steps.isNotEmpty()) {
            Spacer(Modifier.height(20.dp))
            Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
                steps.forEach { (step, text) ->
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        Text(
                            step,
                            color = AccentOrange,
                            fontWeight = FontWeight.Bold,
                            fontSize = 18.sp,
                        )
                        Text(
                            text,
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                    }
                }
            }
        }
    }
}

/** The 2x2 brand grid: four hues, rounded outer corners, white corner-bracket + diagonal stride. */
@Composable
fun BrandLogo(modifier: Modifier = Modifier) {
    val quadrants = listOf(AccentOrange, AccentCyan, AccentViolet, AccentMagenta)
    Canvas(modifier = modifier) {
        val side = size.minDimension
        val cell = side / 2f
        val gap = side * 0.03f
        val corner = CornerRadius(side * 0.16f, side * 0.16f)
        // Four quadrant cells (orange/cyan top, violet/magenta bottom).
        quadrants.forEachIndexed { i, color ->
            val left = if (i % 2 == 0) 0f else cell + gap
            val top = if (i < 2) 0f else cell + gap
            drawRoundRect(
                color = color,
                topLeft = Offset(left, top),
                size = Size(cell - gap, cell - gap),
                cornerRadius = corner,
            )
        }
        // White corner bracket pinning the top-left cell.
        val bracket = side * 0.28f
        val stroke = side * 0.035f
        drawLine(
            color = Color.White,
            start = Offset(side * 0.08f, side * 0.08f + bracket),
            end = Offset(side * 0.08f, side * 0.08f),
            strokeWidth = stroke,
            cap = StrokeCap.Round,
        )
        drawLine(
            color = Color.White,
            start = Offset(side * 0.08f, side * 0.08f),
            end = Offset(side * 0.08f + bracket, side * 0.08f),
            strokeWidth = stroke,
            cap = StrokeCap.Round,
        )
        // Single white diagonal stride line across the quadrants.
        drawLine(
            color = Color.White,
            start = Offset(0f, side),
            end = Offset(side, 0f),
            strokeWidth = stroke * 0.9f,
            cap = StrokeCap.Round,
        )
    }
}
