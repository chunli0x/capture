package ai.loosh.tapfarm

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import coil3.compose.AsyncImage
import com.solana.mobilewalletadapter.clientlib.ActivityResultSender

class MainActivity : ComponentActivity() {

    // Must be constructed during onCreate: ActivityResultSender registers an
    // activity result launcher, which throws if done after the activity starts.
    private lateinit var sender: ActivityResultSender

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        sender = ActivityResultSender(this)

        setContent {
            MaterialTheme(colorScheme = TapFarmColors) {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background,
                ) {
                    TapFarmApp(sender)
                }
            }
        }
    }
}

private val Accent = Color(0xFF4ADE80)
private val Warn = Color(0xFFFBBF24)

private val TapFarmColors = darkColorScheme(
    primary = Accent,
    onPrimary = Color(0xFF04120A),
    background = Color(0xFF0B0F14),
    onBackground = Color(0xFFE6EDF3),
    surface = Color(0xFF141A21),
    onSurface = Color(0xFFE6EDF3),
    surfaceVariant = Color(0xFF1C242D),
    error = Color(0xFFFF6B6B),
)

@Composable
fun TapFarmApp(sender: ActivityResultSender, vm: TapFarmViewModel = viewModel()) {
    val state by vm.state.collectAsState()

    Scaffold { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(horizontal = 20.dp, vertical = 16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Header(state)

            when (state.screen) {
                Screen.CONNECT -> ConnectScreen(state) { vm.connect(sender) }
                Screen.CAMPAIGNS -> CampaignsScreen(
                    state = state,
                    onOpen = vm::openCampaign,
                    onClaim = { vm.claim(sender) },
                )
                Screen.SOLVING -> SolvingScreen(
                    state = state,
                    onToggle = vm::toggleCell,
                    onSubmit = vm::submit,
                    onNext = vm::loadNextTask,
                    onBack = vm::backToCampaigns,
                )
            }

            state.busy?.let { Busy(it) }
            state.error?.let { ErrorCard(it, vm::dismissError) }
        }
    }
}

@Composable
private fun Header(state: UiState) {
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column {
            Text(
                "Tap Farm",
                fontSize = 24.sp,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onBackground,
            )
            Text(
                state.walletShort ?: "not connected",
                fontSize = 12.sp,
                fontFamily = FontFamily.Monospace,
                color = Accent,
            )
        }
        if (state.wallet != null) {
            Column(horizontalAlignment = Alignment.End) {
                Text(
                    "%.4f TAP".format(state.uiBalance),
                    fontSize = 18.sp,
                    fontWeight = FontWeight.SemiBold,
                    fontFamily = FontFamily.Monospace,
                    color = MaterialTheme.colorScheme.onBackground,
                )
                Text(
                    "${state.solved} solved",
                    fontSize = 12.sp,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                )
            }
        }
    }
}

@Composable
private fun ConnectScreen(state: UiState, onConnect: () -> Unit) {
    Column(
        Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Spacer(Modifier.height(24.dp))
        Text(
            "Label training data. Get paid to the wallet already in your phone.",
            fontSize = 20.sp,
            color = MaterialTheme.colorScheme.onBackground,
        )
        Text(
            "Devnet build. Rewards are test tokens.",
            fontSize = 13.sp,
            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
        )
        Button(
            onClick = onConnect,
            enabled = state.busy == null,
            modifier = Modifier.fillMaxWidth(),
        ) { Text("Connect wallet") }
    }
}

@Composable
private fun CampaignsScreen(
    state: UiState,
    onOpen: (Campaign) -> Unit,
    onClaim: () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        EligibilityCard(state)

        Button(
            onClick = onClaim,
            enabled = state.claimable && state.busy == null,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text(if (state.claimable) "Claim %.4f TAP".format(state.uiBalance) else "Claim")
        }

        state.lastSignature?.let { signature ->
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text("Paid on devnet", color = Accent, fontWeight = FontWeight.SemiBold)
                    Text(
                        signature,
                        fontFamily = FontFamily.Monospace,
                        fontSize = 10.sp,
                        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
                    )
                }
            }
        }

        Text(
            "Campaigns",
            fontSize = 13.sp,
            fontWeight = FontWeight.SemiBold,
            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
        )
        LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            items(state.campaigns) { campaign ->
                CampaignRow(campaign) { onOpen(campaign) }
            }
        }
    }
}

@Composable
private fun CampaignRow(campaign: Campaign, onClick: () -> Unit) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(enabled = campaign.isLive, onClick = onClick),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface,
        ),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(
                    campaign.title,
                    fontWeight = FontWeight.SemiBold,
                    color = if (campaign.isLive) {
                        MaterialTheme.colorScheme.onSurface
                    } else {
                        MaterialTheme.colorScheme.onSurface.copy(alpha = 0.45f)
                    },
                )
                Text(
                    if (campaign.isLive) "LIVE" else "SOON",
                    fontSize = 11.sp,
                    fontWeight = FontWeight.Bold,
                    color = if (campaign.isLive) Accent else Warn,
                )
            }
            Text(
                campaign.description,
                fontSize = 13.sp,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.65f),
            )
            Text(
                "%.4f TAP per task".format(campaign.rewardPerTask / 1_000_000.0),
                fontSize = 12.sp,
                fontFamily = FontFamily.Monospace,
                color = Accent,
            )
        }
    }
}

@Composable
private fun EligibilityCard(state: UiState) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text("Accuracy", fontSize = 12.sp, color = Accent)
                Text(
                    if (state.goldSamples == 0) "—" else "%.0f%%".format(state.accuracy * 100),
                    fontSize = 12.sp,
                    fontFamily = FontFamily.Monospace,
                    color = MaterialTheme.colorScheme.onSurface,
                )
            }
            LinearProgressIndicator(
                progress = { state.accuracy.toFloat().coerceIn(0f, 1f) },
                modifier = Modifier.fillMaxWidth(),
            )
            Text(
                state.eligibilityReason.ifBlank { "Solve tasks to build a verified record." },
                fontSize = 12.sp,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.65f),
            )
        }
    }
}

@Composable
private fun SolvingScreen(
    state: UiState,
    onToggle: (Int) -> Unit,
    onSubmit: () -> Unit,
    onNext: () -> Unit,
    onBack: () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
        TextButton(onClick = onBack) { Text("← Campaigns") }

        val task = state.task
        if (task == null) {
            Text(
                "Loading task…",
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
            )
            return@Column
        }

        Text(
            task.prompt,
            fontSize = 19.sp,
            fontWeight = FontWeight.SemiBold,
            color = MaterialTheme.colorScheme.onBackground,
        )

        TapGrid(
            imageUrl = task.imageUrl,
            grid = task.grid,
            selected = state.selected,
            locked = state.feedback != null,
            onToggle = onToggle,
        )

        state.feedback?.let { FeedbackCard(it) }

        if (state.feedback == null) {
            Button(
                onClick = onSubmit,
                enabled = state.canSubmit,
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Submit") }
        } else {
            Button(
                onClick = onNext,
                enabled = state.busy == null,
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Next task") }
        }
    }
}

/**
 * The task image with a tap grid over it.
 *
 * The grid is an overlay rather than sliced tiles so the image loads once and
 * cells line up exactly with the generator's geometry, which places every
 * object wholly inside one cell.
 */
@Composable
private fun TapGrid(
    imageUrl: String,
    grid: Int,
    selected: Set<Int>,
    locked: Boolean,
    onToggle: (Int) -> Unit,
) {
    Box(
        Modifier
            .fillMaxWidth()
            .aspectRatio(1f)
            .clip(RoundedCornerShape(14.dp))
            .background(MaterialTheme.colorScheme.surface),
    ) {
        AsyncImage(
            model = imageUrl,
            contentDescription = "Labeling task",
            modifier = Modifier.fillMaxSize(),
            contentScale = ContentScale.Fit,
        )
        Column(Modifier.fillMaxSize()) {
            repeat(grid) { row ->
                Row(Modifier.fillMaxWidth().weight(1f)) {
                    repeat(grid) { col ->
                        val cell = row * grid + col
                        val isSelected = cell in selected
                        val overlay by animateColorAsState(
                            targetValue = if (isSelected) {
                                Accent.copy(alpha = 0.28f)
                            } else {
                                Color.Transparent
                            },
                            label = "cell-$cell",
                        )
                        Box(
                            Modifier
                                .weight(1f)
                                .fillMaxSize()
                                .background(overlay)
                                .border(
                                    width = if (isSelected) 3.dp else 0.dp,
                                    color = if (isSelected) Accent else Color.Transparent,
                                )
                                .clickable(enabled = !locked) { onToggle(cell) }
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun FeedbackCard(feedback: Feedback) {
    val tint = when {
        !feedback.verified -> MaterialTheme.colorScheme.onSurface
        feedback.correct == true -> Accent
        else -> MaterialTheme.colorScheme.error
    }
    Card(Modifier.fillMaxWidth()) {
        Row(
            Modifier.fillMaxWidth().padding(16.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column {
                Text(feedback.headline, fontWeight = FontWeight.SemiBold, color = tint)
                if (feedback.verified) {
                    Text(
                        "verification task",
                        fontSize = 11.sp,
                        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.55f),
                    )
                }
            }
            Text(
                if (feedback.reward > 0) "+%.4f".format(feedback.reward / 1_000_000.0) else "+0",
                fontFamily = FontFamily.Monospace,
                fontWeight = FontWeight.SemiBold,
                color = tint,
            )
        }
    }
}

@Composable
private fun Busy(label: String) {
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
        Spacer(Modifier.size(10.dp))
        Text(label, fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurface)
    }
}

@Composable
private fun ErrorCard(message: String, onDismiss: () -> Unit) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(message, color = MaterialTheme.colorScheme.error, fontSize = 13.sp)
            OutlinedButton(onClick = onDismiss) { Text("Dismiss") }
        }
    }
}
