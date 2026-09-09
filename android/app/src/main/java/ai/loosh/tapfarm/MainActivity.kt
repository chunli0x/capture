package ai.loosh.tapfarm

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.collectAsState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.solana.mobilewalletadapter.clientlib.ActivityResultSender

/**
 * Spike surface. Three buttons, one job: prove the claim path works on hardware.
 *
 * Dark theme is set up here rather than deferred to a polish pass - retrofitting
 * theming across finished screens costs far more than starting with it.
 */
class MainActivity : ComponentActivity() {

    // Must be constructed during onCreate: ActivityResultSender registers an
    // activity result launcher, which throws if done after the activity has
    // started.
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
                    SpikeScreen(sender)
                }
            }
        }
    }
}

private val TapFarmColors = darkColorScheme(
    primary = Color(0xFF4ADE80),
    onPrimary = Color(0xFF04120A),
    background = Color(0xFF0B0F14),
    onBackground = Color(0xFFE6EDF3),
    surface = Color(0xFF141A21),
    onSurface = Color(0xFFE6EDF3),
    error = Color(0xFFFF6B6B),
)

@Composable
fun SpikeScreen(sender: ActivityResultSender, vm: SpikeViewModel = viewModel()) {
    val state by vm.state.collectAsState()

    Scaffold { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text(
                "Tap Farm",
                fontSize = 32.sp,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onBackground,
            )
            Text(
                "MWA claim spike · devnet",
                fontSize = 14.sp,
                color = MaterialTheme.colorScheme.primary,
            )

            Spacer(Modifier.height(8.dp))

            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Label("Wallet", state.walletShort ?: "not connected")
                    Label("Earned", "%.4f SKR".format(state.uiEarned))
                }
            }

            if (!state.connected) {
                Button(
                    onClick = { vm.connect(sender) },
                    enabled = state.busy == null,
                    modifier = Modifier.fillMaxWidth(),
                ) { Text("Connect wallet") }
            } else {
                OutlinedButton(
                    onClick = { vm.grantTestTasks() },
                    enabled = state.busy == null,
                    modifier = Modifier.fillMaxWidth(),
                ) { Text("Credit 6 test tasks") }

                Button(
                    onClick = { vm.claim(sender) },
                    enabled = state.busy == null && state.claimable,
                    modifier = Modifier.fillMaxWidth(),
                ) { Text("Claim to wallet") }
            }

            state.busy?.let { label ->
                Column(
                    Modifier.fillMaxWidth(),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    CircularProgressIndicator()
                    Text(label, fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurface)
                }
            }

            state.error?.let { message ->
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(message, color = MaterialTheme.colorScheme.error, fontSize = 14.sp)
                        OutlinedButton(onClick = vm::dismissError) { Text("Dismiss") }
                    }
                }
            }

            state.lastSignature?.let { signature ->
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text(
                            "Confirmed on devnet",
                            color = MaterialTheme.colorScheme.primary,
                            fontWeight = FontWeight.SemiBold,
                        )
                        Text(
                            signature,
                            fontFamily = FontFamily.Monospace,
                            fontSize = 11.sp,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                        Text(
                            "explorer.solana.com/tx/<sig>?cluster=devnet",
                            fontSize = 11.sp,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun Label(key: String, value: String) {
    Column {
        Text(key, fontSize = 12.sp, color = MaterialTheme.colorScheme.primary)
        Text(
            value,
            fontSize = 18.sp,
            fontFamily = FontFamily.Monospace,
            color = MaterialTheme.colorScheme.onSurface,
        )
    }
}
