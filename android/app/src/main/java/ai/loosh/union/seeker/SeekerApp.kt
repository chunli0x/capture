package ai.loosh.union.seeker

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.Preview
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.camera.video.FallbackStrategy
import androidx.camera.video.FileOutputOptions
import androidx.camera.video.Quality
import androidx.camera.video.QualitySelector
import androidx.camera.video.Recorder
import androidx.camera.video.Recording
import androidx.camera.video.VideoCapture
import androidx.camera.video.VideoRecordEvent
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.media3.common.MediaItem
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.PlayerView
import com.solana.mobilewalletadapter.clientlib.ActivityResultSender
import java.io.File
import kotlinx.coroutines.delay
import org.json.JSONObject

@Composable
fun SeekerApp(sender: ActivityResultSender, vm: SeekerViewModel = viewModel()) {
    val s by vm.state.collectAsState()
    var server by remember(s.server) { mutableStateOf(s.server) }
    var creating by remember { mutableStateOf(false) }
    Column(
        Modifier.fillMaxSize()
            .systemBarsPadding()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Seeker", style = MaterialTheme.typography.headlineSmall)
        Text(
            "Devnet only • TEST-USDC rewards • TEST-SKR bond",
            style = MaterialTheme.typography.labelLarge,
        )
        if (s.busy) {
            LinearProgressIndicator(Modifier.fillMaxWidth())
            Text(s.message)
        }
        s.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        if (s.wallet.isEmpty()) {
            Text(
                "Capture objects, scenes, or actions, label them by hand, and review each submission independently. Payment needs the requester's explicit acceptance."
            )
            OutlinedTextField(
                server,
                { server = it },
                label = { Text("Pilot server address") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )
            Button(onClick = { vm.server(server) }, enabled = !s.busy) { Text("Use server") }
            var over18 by remember { mutableStateOf(false) }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(
                    checked = over18,
                    onCheckedChange = { over18 = it },
                    enabled = !s.busy,
                )
                Text("I confirm I am 18 or older")
            }
            Button(onClick = { vm.connect(sender, over18) }, enabled = !s.busy && over18) {
                Text("Sign in with wallet")
            }
            Text(
                "Workers and reviewers need operator enrollment. This pilot does not verify unique humanity."
            )
            return@Column
        }
        Text("Wallet ${s.wallet.take(6)}…${s.wallet.takeLast(6)}")
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = { vm.refresh() }, enabled = !s.busy) { Text("Refresh") }
            TextButton(onClick = { vm.logout() }, enabled = !s.busy) { Text("Sign out") }
        }
        if (s.selected != null) {
            val selected = s.selected!!
            val kind = bountyKind(selected)
            TextButton(onClick = { vm.close() }, enabled = !s.busy) { Text("Back to bounties") }
            Text(
                selected.getJSONObject("bounty").getString("title"),
                style = MaterialTheme.typography.titleLarge,
            )
            Text(
                when {
                    s.reviewing ->
                        "Independent review: label this capture without seeing other labels."
                    kind == "action" ->
                        "Record one action clip (≤ 30 s), then choose a tag and trim. Avoid people and private information."
                    else ->
                        "Capture only objects or scenes you have permission to share. Avoid people and private information."
                }
            )
            val editable =
                s.reviewing ||
                    (selected.getString("worker") == s.wallet &&
                        selected.getString("status") == "claimed")
            val canCapture =
                s.image == null &&
                    s.videoDurationMs == null &&
                    selected.isNull("media_hash") &&
                    selected.getString("worker") == s.wallet
            when (kind) {
                "action" ->
                    if (canCapture) {
                        CaptureVideo(!s.busy) { data, durationMs ->
                            vm.capture(selected.getString("id"), data, durationMs)
                        }
                    } else if (s.videoDurationMs != null) {
                        ActionEditor(s, editable, !s.busy, vm::submitAction)
                    } else {
                        Text("Action clip already captured.")
                    }
                "place" ->
                    if (canCapture) {
                        CapturePhoto(!s.busy) { data -> vm.capture(selected.getString("id"), data) }
                    } else if (s.image != null) {
                        PlaceEditor(s, editable, !s.busy, vm::submitPlace)
                    }
                else ->
                    if (canCapture) {
                        CapturePhoto(!s.busy) { data -> vm.capture(selected.getString("id"), data) }
                    } else if (s.image != null) {
                        PhotoEditor(s, editable, !s.busy, vm::submit)
                    }
            }
            return@Column
        }
        if (s.worker) {
            Text(
                "Worker bond: ${s.bond} TEST-SKR base units. Locked while any fulfillment is pending; 24-hour cooldown after a deposit."
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(
                    onClick = { vm.transact("/bond/deposit", sender) },
                    enabled = !s.busy,
                ) {
                    Text("Deposit bond")
                }
                OutlinedButton(
                    onClick = { vm.transact("/bond/withdraw", sender) },
                    enabled = !s.busy,
                ) {
                    Text("Withdraw")
                }
            }
        } else Text("Ask the operator to enroll this wallet before capturing or reviewing.")
        Button(onClick = { creating = !creating }, enabled = !s.busy) {
            Text(if (creating) "Close new bounty" else "Create bounty")
        }
        if (creating) CreateBountyForm(s.taxonomy, s.busy, vm::create)
        Text("Bounties", style = MaterialTheme.typography.titleLarge)
        s.bounties.forEach { b ->
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(b.getString("title"), style = MaterialTheme.typography.titleMedium)
                    Text(
                        "${b.getLong("reward_usdc_units")/1_000_000.0} TEST-USDC per accepted ${rewardNoun(b.optString("kind", KIND_OBJECT))} · ${b.getInt("slots")} slots · ${b.getString("status")}"
                    )
                    Text(
                        "Funding total: ${b.getLong("reward_usdc_units")*b.getInt("slots")/1_000_000.0} TEST-USDC. Pilot fee: 0."
                    )
                    val mine = b.getString("requester") == s.wallet
                    val id = b.getString("id")
                    if (mine && b.getString("status") == "draft")
                        Button(
                            onClick = { vm.transact("/bounties/$id/fund", sender) },
                            enabled = !s.busy,
                        ) {
                            Text("Fund escrow")
                        }
                    if (
                        !mine &&
                            s.worker &&
                            b.getString("status") == "open" &&
                            b.getLong("deadline") > System.currentTimeMillis() / 1000
                    )
                        Button(onClick = { vm.claim(id) }, enabled = !s.busy) {
                            Text("Claim a slot")
                        }
                    if (
                        mine &&
                            b.getString("status") != "draft" &&
                            b.getLong("deadline") <= System.currentTimeMillis() / 1000
                    )
                        OutlinedButton(
                            onClick = { vm.transact("/bounties/$id/refund", sender) },
                            enabled = !s.busy,
                        ) {
                            Text("Refund available escrow")
                        }
                }
            }
        }
        Text("Your submissions and requests", style = MaterialTheme.typography.titleLarge)
        s.submissions.forEach { sub ->
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(sub.getJSONObject("bounty").getString("title"))
                    val status = sub.getString("status")
                    val id = sub.getString("id")
                    Text("Status: $status")
                    OutlinedButton(onClick = { vm.open(sub, false) }, enabled = !s.busy) {
                        Text(
                            if (sub.isNull("media_hash")) "Capture"
                            else "Open submission and labels"
                        )
                    }
                    if (status == "eligible" && sub.getString("worker") == s.wallet)
                        Button(
                            onClick = { vm.transact("/submissions/$id/fulfill", sender) },
                            enabled = !s.busy,
                        ) {
                            Text("Register eligible work")
                        }
                    if (
                        status == "registered" &&
                            sub.getJSONObject("bounty").getString("requester") == s.wallet
                    ) {
                        Button(
                            onClick = { vm.transact("/submissions/$id/accept", sender) },
                            enabled = !s.busy,
                        ) {
                            Text("Accept and pay")
                        }
                        OutlinedButton(
                            onClick = { vm.transact("/submissions/$id/reject", sender) },
                            enabled = !s.busy,
                        ) {
                            Text("Reject without payment")
                        }
                    }
                    if (
                        status == "registered" &&
                            sub.getJSONObject("bounty").getLong("deadline") <=
                                System.currentTimeMillis() / 1000
                    )
                        OutlinedButton(
                            onClick = { vm.transact("/submissions/$id/expire", sender) },
                            enabled = !s.busy,
                        ) {
                            Text("Expire and unlock bond")
                        }
                }
            }
        }
        if (s.reviewer) {
            Text("Independent reviews", style = MaterialTheme.typography.titleLarge)
            Text(
                "Pilot reviews are unpaid. Two distinct agreeing reviews establish eligibility; they do not release money."
            )
            s.reviews.forEach { sub ->
                OutlinedButton(onClick = { vm.open(sub, true) }, enabled = !s.busy) {
                    Text("Review: ${sub.getJSONObject("bounty").getString("title")}")
                }
            }
        }
        val pending = s.transactions.filter { !it.getBoolean("confirmed") }
        if (pending.isNotEmpty()) {
            Text("Transaction recovery", style = MaterialTheme.typography.titleLarge)
            Text(
                "If your wallet sent a transaction but the app did not record confirmation, recover it here. An unsigned or canceled transaction has no payment effect."
            )
            pending.take(10).forEach { tx ->
                OutlinedButton(onClick = { vm.recover(tx.getString("id")) }, enabled = !s.busy) {
                    Text("Recover ${tx.getString("action")} · ${tx.getString("id").take(6)}")
                }
            }
        }
    }
}

@Composable
private fun CreateBountyForm(
    taxonomy: List<TaxonomyCategory>,
    busy: Boolean,
    create: (String, List<Int>, String, String, String, String) -> Unit,
) {
    var title by remember { mutableStateOf("") }
    var reward by remember { mutableStateOf("1") }
    var slots by remember { mutableStateOf("1") }
    var hours by remember { mutableStateOf("24") }
    var kind by remember { mutableStateOf(KIND_OBJECT) }
    var selectedIds by remember { mutableStateOf(setOf<Int>()) }
    OutlinedTextField(title, { title = it }, label = { Text("Bounty title") })
    Text("Kind", style = MaterialTheme.typography.labelLarge)
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        FilterChip(
            selected = kind == KIND_OBJECT,
            onClick = {
                kind = KIND_OBJECT
                selectedIds = emptySet()
            },
            label = { Text("Object") },
        )
        FilterChip(
            selected = kind == KIND_PLACE,
            onClick = {
                kind = KIND_PLACE
                selectedIds = emptySet()
            },
            label = { Text("Place") },
        )
        FilterChip(
            selected = kind == KIND_ACTION,
            onClick = {
                kind = KIND_ACTION
                selectedIds = emptySet()
            },
            label = { Text("Action") },
        )
    }
    Text("Categories", style = MaterialTheme.typography.labelLarge)
    val available = categoriesForKind(taxonomy, kind)
    if (available.isEmpty()) {
        Text(
            "No $kind categories in the registry yet.",
            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
        )
    } else {
        available.forEach { c ->
            FilterChip(
                selected = c.id in selectedIds,
                onClick = {
                    selectedIds =
                        if (c.id in selectedIds) selectedIds - c.id else selectedIds + c.id
                },
                label = { Text(c.name) },
                enabled = !busy,
            )
        }
    }
    OutlinedTextField(reward, { reward = it }, label = { Text("TEST-USDC per accepted submission") })
    OutlinedTextField(slots, { slots = it }, label = { Text("Payable slots (1–100)") })
    OutlinedTextField(hours, { hours = it }, label = { Text("Deadline in hours (1–720)") })
    Button(
        onClick = { create(title, selectedIds.toList(), reward, slots, hours, kind) },
        enabled = !busy && title.isNotBlank() && selectedIds.isNotEmpty(),
    ) {
        Text("Save draft")
    }
}

@Composable
private fun PhotoEditor(
    s: PilotState,
    editable: Boolean,
    enabled: Boolean,
    submit: (List<LabelBox>) -> Unit,
) {
    val bitmap = s.image ?: return
    val selected = s.selected ?: return
    val categories = selected.getJSONObject("bounty").getJSONArray("categories")
    var category by
        remember(selected, s.reviewing) {
            mutableIntStateOf(categories.getJSONObject(0).getInt("id"))
        }
    var boxes by
        remember(selected, s.reviewing) {
            mutableStateOf(
                if (s.reviewing || selected.isNull("boxes")) emptyList()
                else
                    selected.getJSONArray("boxes").let { array ->
                        (0 until array.length()).map {
                            val b = array.getJSONObject(it)
                            LabelBox(
                                b.getInt("category_id"),
                                b.getDouble("x").toFloat(),
                                b.getDouble("y").toFloat(),
                                b.getDouble("w").toFloat(),
                                b.getDouble("h").toFloat(),
                            )
                        }
                    }
            )
        }
    var start by remember { mutableStateOf<Offset?>(null) }
    var end by remember { mutableStateOf<Offset?>(null) }
    if (editable) {
        Text(
            "Choose a category, then drag a box over each object. You can also add a box using normalized coordinates below."
        )
        for (i in 0 until categories.length()) {
            val c = categories.getJSONObject(i)
            FilterChip(
                selected = category == c.getInt("id"),
                onClick = { category = c.getInt("id") },
                label = { Text(c.getString("name")) },
                enabled = enabled,
            )
        }
    }
    Box(Modifier.fillMaxWidth().aspectRatio(bitmap.width.toFloat() / bitmap.height)) {
        Image(bitmap.asImageBitmap(), "Approved object photo", Modifier.fillMaxSize())
        Canvas(
            Modifier.fillMaxSize().pointerInput(editable, enabled, category) {
                if (editable && enabled)
                    detectDragGestures(
                        onDragStart = {
                            start = Offset(it.x / size.width, it.y / size.height)
                            end = start
                        },
                        onDragEnd = {
                            val a = start
                            val b = end
                            if (a != null && b != null && boxes.size < 100)
                                dragBox(category, a.x, a.y, b.x, b.y)?.let { boxes = boxes + it }
                            start = null
                            end = null
                        },
                        onDragCancel = {
                            start = null
                            end = null
                        },
                        onDrag = { change, _ ->
                            change.consume()
                            end =
                                Offset(
                                    change.position.x / size.width,
                                    change.position.y / size.height,
                                )
                        },
                    )
            }
        ) {
            val preview =
                if (start != null && end != null)
                    dragBox(category, start!!.x, start!!.y, end!!.x, end!!.y)
                else null
            (boxes + listOfNotNull(preview)).forEach {
                drawRect(
                    Color.Green,
                    Offset(it.x * size.width, it.y * size.height),
                    Size(it.w * size.width, it.h * size.height),
                    style = Stroke(3.dp.toPx()),
                )
            }
        }
    }
    Text("${boxes.size} boxes")
    boxes.forEachIndexed { index, b ->
        Text(
            "${index+1}: category ${b.categoryId}, x=${"%.2f".format(b.x)}, y=${"%.2f".format(b.y)}, width=${"%.2f".format(b.w)}, height=${"%.2f".format(b.h)}"
        )
    }
    if (editable) {
        var coordinates by remember { mutableStateOf("0.1, 0.1, 0.5, 0.5") }
        var inputError by remember { mutableStateOf<String?>(null) }
        OutlinedTextField(
            coordinates,
            { coordinates = it },
            label = { Text("x, y, width, height (0–1)") },
        )
        inputError?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        OutlinedButton(
            onClick = {
                val v = coordinates.split(',').mapNotNull { it.trim().toFloatOrNull() }
                val box =
                    if (
                        v.size == 4 &&
                            v.all { it.isFinite() && it in 0f..1f } &&
                            v[0] + v[2] <= 1 &&
                            v[1] + v[3] <= 1
                    )
                        dragBox(category, v[0], v[1], v[0] + v[2], v[1] + v[3])
                    else null
                if (box != null && boxes.size < 100) {
                    boxes = boxes + box
                    inputError = null
                } else inputError = "Enter a nonempty box within the image."
            },
            enabled = enabled,
        ) {
            Text("Add coordinate box")
        }
        OutlinedButton(
            onClick = { boxes = boxes.dropLast(1) },
            enabled = enabled && boxes.isNotEmpty(),
        ) {
            Text("Undo last box")
        }
        Button(onClick = { submit(boxes) }, enabled = enabled && boxes.isNotEmpty()) {
            Text(if (s.reviewing) "Submit independent review" else "Submit immutable labels")
        }
    }
}

@Composable
private fun CapturePhoto(enabled: Boolean, onPhoto: (ByteArray) -> Unit) {
    val context = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current
    var permission by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
                PackageManager.PERMISSION_GRANTED
        )
    }
    val request =
        rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
            permission = it
        }
    var capture by remember { mutableStateOf<ImageCapture?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var capturing by remember { mutableStateOf(false) }
    val previewView = remember { PreviewView(context) }
    val live = remember { java.util.concurrent.atomic.AtomicBoolean(true) }
    DisposableEffect(Unit) {
        live.set(true)
        onDispose { live.set(false) }
    }
    if (!permission) {
        Button(onClick = { request.launch(Manifest.permission.CAMERA) }, enabled = enabled) {
            Text("Allow camera for object capture")
        }
        return
    }
    DisposableEffect(lifecycle, previewView) {
        val future = ProcessCameraProvider.getInstance(context)
        var provider: ProcessCameraProvider? = null
        var disposed = false
        val executor = ContextCompat.getMainExecutor(context)
        future.addListener(
            {
                if (!disposed)
                    try {
                        provider = future.get()
                        val preview =
                            Preview.Builder().build().also {
                                it.surfaceProvider = previewView.surfaceProvider
                            }
                        val camera =
                            ImageCapture.Builder()
                                .setResolutionSelector(
                                    ResolutionSelector.Builder()
                                        .setResolutionStrategy(
                                            ResolutionStrategy(
                                                android.util.Size(1600, 1200),
                                                ResolutionStrategy
                                                    .FALLBACK_RULE_CLOSEST_LOWER_THEN_HIGHER,
                                            )
                                        )
                                        .build()
                                )
                                .build()
                        provider?.bindToLifecycle(
                            lifecycle,
                            CameraSelector.DEFAULT_BACK_CAMERA,
                            preview,
                            camera,
                        )
                        capture = camera
                    } catch (e: Exception) {
                        error = e.message ?: "Camera unavailable"
                    }
            },
            executor,
        )
        onDispose {
            disposed = true
            provider?.unbindAll()
            capture = null
        }
    }
    AndroidView(factory = { previewView }, modifier = Modifier.fillMaxWidth().height(320.dp))
    error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
    Button(
        onClick = {
            val camera = capture ?: return@Button
            capturing = true
            val file = File.createTempFile("seeker-capture-", ".jpg", context.cacheDir)
            camera.takePicture(
                ImageCapture.OutputFileOptions.Builder(file).build(),
                ContextCompat.getMainExecutor(context),
                object : ImageCapture.OnImageSavedCallback {
                    override fun onImageSaved(output: ImageCapture.OutputFileResults) {
                        try {
                            if (live.get()) onPhoto(file.readBytes())
                        } finally {
                            file.delete()
                            capturing = false
                        }
                    }

                    override fun onError(exc: ImageCaptureException) {
                        file.delete()
                        capturing = false
                        error = exc.message
                    }
                },
            )
        },
        enabled = enabled && capture != null && !capturing,
    ) {
        Text("Capture and check photo")
    }
}

/** The bounty kind governing a submission's media + label shape (`object|place|action`). */
private fun bountyKind(selected: JSONObject): String =
    selected.optJSONObject("bounty")?.optString("kind", "object") ?: "object"

/** Kind-aware noun for reward copy; object keeps the phase-1 "photo", others go neutral. */
private fun rewardNoun(kind: String): String =
    if (kind == KIND_OBJECT) "photo" else "submission"

@Composable
private fun PlaceEditor(
    s: PilotState,
    editable: Boolean,
    enabled: Boolean,
    submit: (Int) -> Unit,
) {
    val bitmap = s.image ?: return
    val selected = s.selected ?: return
    val categories = selected.getJSONObject("bounty").getJSONArray("categories")
    val existing = selected.optJSONObject("scene")
    var category by
        remember(selected, s.reviewing) {
            mutableIntStateOf(
                existing?.optInt("category_id", -1)?.takeIf { it >= 0 }
                    ?: categories.getJSONObject(0).getInt("id")
            )
        }
    Image(
        bitmap.asImageBitmap(),
        "Approved place photo",
        Modifier.fillMaxWidth().aspectRatio(bitmap.width.toFloat() / bitmap.height),
    )
    Text("Choose the single scene class")
    for (i in 0 until categories.length()) {
        val c = categories.getJSONObject(i)
        FilterChip(
            selected = category == c.getInt("id"),
            onClick = { category = c.getInt("id") },
            label = { Text(c.getString("name")) },
            enabled = enabled && editable,
        )
    }
    if (editable) {
        Button(onClick = { submit(category) }, enabled = enabled) {
            Text(if (s.reviewing) "Submit independent review" else "Submit immutable label")
        }
    }
}

@Composable
private fun ActionEditor(
    s: PilotState,
    editable: Boolean,
    enabled: Boolean,
    submit: (Int, TrimRange) -> Unit,
) {
    val selected = s.selected ?: return
    val durationMs = s.videoDurationMs ?: return
    val categories = selected.getJSONObject("bounty").getJSONArray("categories")
    val existing = actionLabelOf(selected)
    var category by
        remember(selected, s.reviewing) {
            mutableIntStateOf(
                existing?.categoryId?.takeIf { it >= 0 }
                    ?: categories.getJSONObject(0).getInt("id")
            )
        }
    var startMs by
        remember(selected, s.reviewing) {
            mutableIntStateOf(existing?.startMs ?: 0)
        }
    var endMs by
        remember(selected, s.reviewing, durationMs) {
            mutableIntStateOf(existing?.endMs ?: durationMs)
        }
    if (durationMs < 2) {
        Text("Clip is too short to trim.", color = MaterialTheme.colorScheme.error)
        return
    }
    val videoUri = s.videoUri
    if (videoUri == null) {
        Text("Loading approved video…")
        return
    }
    val context = LocalContext.current
    val player =
        remember(videoUri) {
            ExoPlayer.Builder(context).build().apply {
                setMediaItem(MediaItem.fromUri(videoUri))
                prepare()
                playWhenReady = false
            }
        }
    DisposableEffect(player) { onDispose { player.release() } }
    // Pin the preview to the trim start on first show, then follow the sliders.
    LaunchedEffect(player) { player.seekTo(startMs.toLong()) }
    AndroidView(
        factory = { ctx -> PlayerView(ctx).apply { this.player = player; useController = true } },
        modifier = Modifier.fillMaxWidth().height(240.dp),
    )
    Text("Clip length $durationMs ms. Choose one action tag, then set the trim.")
    for (i in 0 until categories.length()) {
        val c = categories.getJSONObject(i)
        FilterChip(
            selected = category == c.getInt("id"),
            onClick = { category = c.getInt("id") },
            label = { Text(c.getString("name")) },
            enabled = enabled && editable,
        )
    }
    Text("Start: $startMs ms")
    Slider(
        value = startMs.toFloat(),
        onValueChange = {
            startMs = it.toInt().coerceIn(0, endMs - 1)
            player.seekTo(startMs.toLong())
        },
        valueRange = 0f..durationMs.toFloat(),
        enabled = enabled && editable,
    )
    Text("End: $endMs ms")
    Slider(
        value = endMs.toFloat(),
        onValueChange = {
            endMs = it.toInt().coerceIn(startMs + 1, durationMs)
            player.seekTo(endMs.toLong())
        },
        valueRange = 0f..durationMs.toFloat(),
        enabled = enabled && editable,
    )
    val trim = trimRange(startMs, endMs, durationMs)
    if (trim != null) Text("Trim ${trim.startMs}–${trim.endMs} ms")
    else Text("Trim must be start < end", color = MaterialTheme.colorScheme.error)
    if (editable) {
        Button(
            onClick = { trim?.let { submit(category, it) } },
            enabled = enabled && trim != null,
        ) {
            Text(if (s.reviewing) "Submit independent review" else "Submit immutable labels")
        }
    }
}

/** Reads a previously submitted action label from the submission payload, if the server sent one. */
private fun actionLabelOf(selected: JSONObject): ActionLabel? {
    val raw =
        selected.optJSONObject("action")
            ?: selected.optJSONObject("boxes")?.optJSONObject("action")
            ?: return null
    val categoryId = raw.optInt("category_id", -1)
    val startMs = raw.optInt("start_ms", -1)
    val endMs = raw.optInt("end_ms", -1)
    return if (categoryId >= 0 && startMs >= 0 && endMs > startMs) {
        ActionLabel(categoryId, startMs, endMs)
    } else null
}

@Composable
private fun CaptureVideo(enabled: Boolean, onVideo: (ByteArray, Int) -> Unit) {
    val context = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current
    var permission by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
                PackageManager.PERMISSION_GRANTED
        )
    }
    val request =
        rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
            permission = it
        }
    var videoCapture by remember { mutableStateOf<VideoCapture<Recorder>?>(null) }
    var recording by remember { mutableStateOf<Recording?>(null) }
    var recordingActive by remember { mutableStateOf(false) }
    var elapsedMs by remember { mutableIntStateOf(0) }
    var error by remember { mutableStateOf<String?>(null) }
    val previewView = remember { PreviewView(context) }
    val live = remember { java.util.concurrent.atomic.AtomicBoolean(true) }
    DisposableEffect(Unit) {
        live.set(true)
        onDispose { live.set(false) }
    }
    if (!permission) {
        Button(onClick = { request.launch(Manifest.permission.CAMERA) }, enabled = enabled) {
            Text("Allow camera for action capture")
        }
        return
    }
    DisposableEffect(lifecycle, previewView) {
        val future = ProcessCameraProvider.getInstance(context)
        var provider: ProcessCameraProvider? = null
        var disposed = false
        val executor = ContextCompat.getMainExecutor(context)
        future.addListener(
            {
                if (!disposed)
                    try {
                        provider = future.get()
                        val preview =
                            Preview.Builder().build().also {
                                it.surfaceProvider = previewView.surfaceProvider
                            }
                        val recorder =
                            Recorder.Builder()
                                .setQualitySelector(
                                    QualitySelector.from(
                                        Quality.SD,
                                        FallbackStrategy.lowerQualityOrHigherThan(Quality.SD),
                                    )
                                )
                                .build()
                        val capture = VideoCapture.withOutput(recorder)
                        provider?.bindToLifecycle(
                            lifecycle,
                            CameraSelector.DEFAULT_BACK_CAMERA,
                            preview,
                            capture,
                        )
                        videoCapture = capture
                    } catch (e: Exception) {
                        error = e.message ?: "Camera unavailable"
                    }
            },
            executor,
        )
        onDispose {
            disposed = true
            recording?.stop()
            provider?.unbindAll()
            videoCapture = null
            recording = null
        }
    }
    // Hard duration cap: stop automatically once MAX_ACTION_MS elapses.
    LaunchedEffect(recordingActive) {
        if (recordingActive) {
            val startedAt = android.os.SystemClock.elapsedRealtime()
            while (recordingActive) {
                val e = (android.os.SystemClock.elapsedRealtime() - startedAt).toInt()
                elapsedMs = e
                if (e >= MAX_ACTION_MS) {
                    recording?.stop()
                    break
                }
                delay(100)
            }
        }
    }
    AndroidView(factory = { previewView }, modifier = Modifier.fillMaxWidth().height(320.dp))
    error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
    Text("Recorded ${cappedDurationMs(elapsedMs)} ms · hard cap $MAX_ACTION_MS ms")
    Button(
        onClick = {
            val capture = videoCapture ?: return@Button
            val current = recording
            if (current == null) {
                elapsedMs = 0
                val file = File.createTempFile("seeker-action-", ".mp4", context.cacheDir)
                val pending =
                    capture.output.prepareRecording(
                        context,
                        FileOutputOptions.Builder(file).build(),
                    )
                recording =
                    pending.start(
                        ContextCompat.getMainExecutor(context),
                    ) { event ->
                        when (event) {
                            is VideoRecordEvent.Start -> recordingActive = true
                            is VideoRecordEvent.Finalize -> {
                                recordingActive = false
                                recording = null
                                if (event.hasError()) {
                                    error = "Recording failed (code ${event.error})"
                                    file.delete()
                                } else {
                                    try {
                                        if (live.get())
                                            onVideo(file.readBytes(), cappedDurationMs(elapsedMs))
                                    } finally {
                                        file.delete()
                                    }
                                }
                            }
                            else -> Unit
                        }
                    }
            } else {
                current.stop()
            }
        },
        enabled = enabled && videoCapture != null && (recording == null || recordingActive),
    ) {
        Text(if (recording == null) "Start recording" else "Stop recording")
    }
}
