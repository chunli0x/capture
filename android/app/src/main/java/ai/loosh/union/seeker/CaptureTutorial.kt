package ai.loosh.union.seeker

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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import ai.loosh.union.AccentCyan
import ai.loosh.union.AccentMagenta
import ai.loosh.union.AccentOrange
import ai.loosh.union.MutedGray
import kotlinx.coroutines.launch

/**
 * First-run ground-level capture tutorial, shown once after onboarding and
 * before the main UI (persisted via `tutorial_done`). It teaches the two skills
 * the judge grades on — *how* to hold the camera and *how* to label — without
 * any animal, pet, or robot imagery or copy.
 */
@Composable
fun CaptureTutorialScreen(onDone: () -> Unit) {
    val pages =
        listOf(
            Triple("CAPTURE", "Ground truth, from the ground up.", "Hold your phone 6–12 inches off the ground, angled slightly forward and up. That low, forward view is the whole point."),
            Triple("THE RIGHT HEIGHT", "Lens low, floor in the bottom.", "The floor should fill the bottom of the frame and the horizon sit high. If you can read the walls at eye level, you are too high."),
            Triple("THE WRONG ANGLES", "No eye-level, no straight-down.", "An eye-level shot or one pointed straight at the floor is rejected. Neither is the ground-level view Capture pays for."),
            Triple("LIGHT AND FOCUS", "Sharp subject, even light.", "Keep the subject in focus, avoid motion blur, and avoid near-black or blown-out frames. Natural or indoor light both work."),
            Triple("LABELING", "Object, place, or action — plus posture.", "Pick one primary label, add a posture (required), then optional expression, surface, lighting, weather, and motion."),
            Triple("READY", "You're all set.", "Capture now to take a ground-level photo or short clip, label it, and submit."),
        )

    val pagerState = rememberPagerState(pageCount = { pages.size })
    val scope = rememberCoroutineScope()
    val lastPage = pagerState.currentPage == pages.size - 1

    Column(
        modifier = Modifier.fillMaxSize().padding(horizontal = 24.dp, vertical = 32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Spacer(Modifier.weight(1f))

        HorizontalPager(state = pagerState, modifier = Modifier.fillMaxWidth().weight(6f)) { page ->
            val (title, headline, body) = pages[page]
            Column(
                modifier = Modifier.fillMaxSize(),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center,
            ) {
                if (page == 0) {
                    BrandLogo(Modifier.size(96.dp))
                    Spacer(Modifier.height(20.dp))
                }
                Text(
                    title,
                    style = MaterialTheme.typography.headlineSmall,
                    color = if (page == 0) AccentOrange else MaterialTheme.colorScheme.onBackground,
                    textAlign = TextAlign.Center,
                )
                Spacer(Modifier.height(12.dp))
                Text(
                    headline,
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurface,
                    textAlign = TextAlign.Center,
                )
                Spacer(Modifier.height(8.dp))
                Text(
                    body,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.65f),
                    textAlign = TextAlign.Center,
                )
            }
        }

        Spacer(Modifier.height(24.dp))

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            repeat(pages.size) { index ->
                val active = pagerState.currentPage == index
                Box(
                    Modifier
                        .size(if (active) 22.dp else 8.dp, 8.dp)
                        .background(
                            color = if (active) AccentMagenta else MutedGray.copy(alpha = 0.4f),
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
            Text(if (lastPage) "Start capturing" else "Continue")
        }

        Spacer(Modifier.weight(1f))
    }
}
