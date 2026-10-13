package ai.loosh.union.seeker

import ai.loosh.union.*
import android.content.Context
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.solana.mobilewalletadapter.clientlib.ActivityResultSender

/**
 * The judgment product app: sign in, stake, judge, and earn test USDC for
 * consensus-aligned preferences (slashable bond in test $SKR).
 */
@Composable
fun SeekerApp(sender: ActivityResultSender, vm: SeekerViewModel = viewModel()) {
    val s by vm.state.collectAsState()
    var showBond by remember { mutableStateOf(false) }
    var showBalances by remember { mutableStateOf(false) }
    var showCalibration by remember { mutableStateOf(false) }
    val context = LocalContext.current
    val prefs = remember { context.getSharedPreferences("seeker.api", Context.MODE_PRIVATE) }
    var onboarded by remember { mutableStateOf(prefs.getBoolean("onboarded", false)) }

    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(s.transient, s.status) {
        if (s.status == AsyncStatus.Success && s.transient != null) {
            snackbar.showSnackbar(s.transient!!, duration = SnackbarDuration.Short)
            vm.dismissTransient()
        }
    }

    Scaffold(
        modifier = Modifier.fillMaxSize(),
        containerColor = Color.Transparent,
        snackbarHost = { SnackbarHost(snackbar) },
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            when {
                !onboarded -> OnboardingScreen(onDone = {
                    prefs.edit().putBoolean("onboarded", true).apply()
                    onboarded = true
                })
                s.wallet.isEmpty() -> SignInScreen(s, vm, sender)
                showBond -> BondScreen(s, vm, sender, onBack = { showBond = false })
                showBalances -> BalanceScreen(s, vm, onBack = { showBalances = false })
                showCalibration -> CalibrationScreen(s, vm, onBack = { showCalibration = false })
                else -> {
                    JudgmentScreen(s, vm, onBond = { showBond = true })
                    Column(
                        Modifier.align(Alignment.TopStart).safeDrawingPadding().padding(12.dp),
                    ) {
                        TextButton(
                            onClick = { showCalibration = true },
                            enabled = !s.busy,
                        ) { Text("Calibrate", color = MutedGray) }
                        TextButton(
                            onClick = { showBalances = true },
                            enabled = !s.busy,
                        ) { Text("Balances", color = MutedGray) }
                    }
                    TextButton(
                        onClick = { vm.logout() },
                        enabled = !s.busy,
                        modifier = Modifier.align(Alignment.TopEnd).safeDrawingPadding().padding(12.dp),
                    ) { Text("Sign out", color = MutedGray) }
                }
            }
        }
    }
}

@Composable
private fun SignInScreen(s: PilotState, vm: SeekerViewModel, sender: ActivityResultSender) {
    var over18 by remember { mutableStateOf(false) }
    NavyBackground(Modifier.fillMaxSize().captureScreenMotion()) {
        Column(
            Modifier
                .fillMaxSize()
                .safeDrawingPadding()
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            CaptureWordmark()
            EditorialHeading("SIGN IN.")
            Text(
                "Compare two model outputs and pick the better one. Consensus-aligned judges " +
                    "earn test USDC on devnet.",
                style = MaterialTheme.typography.bodyMedium,
                color = CaptureInk,
            )
            if (s.error != null) {
                Row(
                    Modifier
                        .fillMaxWidth()
                        .background(ErrorRedBg, CaptureRadii.md)
                        .border(1.dp, ErrorRed, CaptureRadii.md)
                        .padding(horizontal = 14.dp, vertical = 10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        "!",
                        style = MaterialTheme.typography.titleMedium,
                        color = ErrorRed,
                        modifier = Modifier.padding(end = 10.dp),
                    )
                    Text(
                        s.error,
                        style = MaterialTheme.typography.bodyMedium,
                        color = ErrorRed,
                        modifier = Modifier.weight(1f),
                    )
                    TextButton(onClick = vm::dismissError) { Text("Dismiss", color = ErrorRed) }
                }
            }
            Row(
                Modifier
                    .fillMaxWidth()
                    .background(CaptureSurface2, CaptureRadii.md)
                    .border(1.dp, CaptureOutline, CaptureRadii.md)
                    .padding(horizontal = 14.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Checkbox(checked = over18, onCheckedChange = { over18 = it }, enabled = !s.busy)
                Text(
                    "I confirm I am 18 or older",
                    style = MaterialTheme.typography.bodyMedium,
                    color = CaptureInk,
                )
            }
            Text(
                "Designed for Android",
                style = MaterialTheme.typography.bodyMedium,
                color = CaptureInk,
            )
            Button(
                onClick = { vm.connect(sender, over18) },
                enabled = !s.busy && over18,
                modifier = Modifier.fillMaxWidth().height(56.dp),
                colors = ButtonDefaults.buttonColors(
                    containerColor = CaptureAction,
                    contentColor = Color.White,
                    disabledContainerColor = ButtonGrey,
                    disabledContentColor = ButtonGreyInk,
                ),
                shape = CaptureRadii.pill,
            ) {
                Text("Sign in with wallet", style = MaterialTheme.typography.titleMedium)
            }
        }
    }
}
