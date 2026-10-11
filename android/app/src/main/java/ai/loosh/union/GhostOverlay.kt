package ai.loosh.union

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.dp
import coil3.compose.AsyncImage
import kotlin.math.abs
import kotlin.math.hypot

/** How close counts as "snapped", for the practice-only glow. */
const val SNAP_PX = 15f
const val SNAP_DEG = 10f

/**
 * Ghost sprite canvas edge, as a multiple of the object's own extent.
 *
 * Must match `render_sprite` in the backend - the sprite is padded so rotation
 * never clips it, and anything sizing UI from the sprite has to divide that
 * padding back out.
 */
const val SPRITE_CANVAS_RATIO = 1.8f

/** Glow ring radius as a fraction of the sprite canvas: hugs the object. */
const val GLOW_RADIUS_FACTOR = 0.55f / SPRITE_CANVAS_RATIO

private val GhostGreen = SuccessGreen

/**
 * Smallest angular difference between two rolls, in [0, 180].
 *
 * Wrapped for the same reason the server wraps it: 350 and 10 degrees are 20
 * apart, not 340. Without this the snap glow would refuse to fire near the
 * wrap point even when the labeler is perfectly aligned.
 */
fun rollDeltaDeg(a: Float, b: Float): Float {
    val delta = abs(a - b) % 360f
    return if (delta > 180f) 360f - delta else delta
}

/**
 * Keeps the ghost reachable.
 *
 * Without this a drag can carry the outline entirely outside the frame, where
 * there is nothing left to grab and the task becomes unrecoverable. Clamping to
 * the canvas bounds means the ghost always has part of itself on screen, and
 * still allows the object to sit right against an edge.
 */
fun clampToCanvas(pose: GhostPose, canvasPx: Int): GhostPose = pose.copy(
    x = pose.x.coerceIn(0f, canvasPx.toFloat()),
    y = pose.y.coerceIn(0f, canvasPx.toFloat()),
)

/** Whether the ghost is within snapping distance of the true pose. */
fun isSnapped(pose: GhostPose, truth: GhostPose): Boolean =
    hypot(pose.x - truth.x, pose.y - truth.y) <= SNAP_PX &&
        rollDeltaDeg(pose.roll, truth.roll) <= SNAP_DEG

/**
 * The ghost-overlay canvas.
 *
 * ## Coordinate space
 *
 * Pose is held in **image pixels** - the same space the server renders and
 * scores in - and converted to display pixels only when drawing. Holding it in
 * display space instead would make the submitted numbers depend on screen
 * size, so the same drag would score differently on different phones.
 *
 * ## Gestures
 *
 * `detectTransformGestures` reports pan, zoom and rotation together, which maps
 * exactly onto the three controls: one-finger drag translates, pinch scales,
 * two-finger twist rolls.
 *
 * ## Snap glow
 *
 * Rendered only when [allowSnap] is true *and* [truth] is non-null. The server
 * sends neither outside practice, so this cannot light up during a blind
 * qualification run even if the client asked it to.
 */
@Composable
fun GhostOverlay(
    imageUrl: String,
    spriteUrl: String,
    canvasPx: Int,
    spritePxAtScale1: Float,
    pose: GhostPose,
    allowSnap: Boolean,
    truth: GhostPose?,
    enabled: Boolean,
    onPoseChange: (GhostPose) -> Unit,
    modifier: Modifier = Modifier,
) {
    var boxSize by remember { mutableStateOf(Size.Zero) }
    val density = LocalDensity.current

    val snapped = allowSnap && truth != null && isSnapped(pose, truth)
    val glow by animateFloatAsState(
        targetValue = if (snapped) 1f else 0f,
        animationSpec = tween(140),
        label = "snap-glow",
    )

    Box(
        modifier = modifier
            .fillMaxWidth()
            .aspectRatio(1f)
            .clip(RoundedCornerShape(14.dp))
            .background(CaptureSurface)
            .onSizeChanged { boxSize = Size(it.width.toFloat(), it.height.toFloat()) }
            .pointerInput(enabled, canvasPx, boxSize) {
                if (!enabled || boxSize.width <= 0f) return@pointerInput
                // Display pixels per image pixel. Gesture deltas arrive in
                // display space and are converted back before being stored.
                val perImagePx = boxSize.width / canvasPx
                detectTransformGestures { _, pan, zoom, rotation ->
                    onPoseChange(
                        pose.copy(
                            x = pose.x + pan.x / perImagePx,
                            y = pose.y + pan.y / perImagePx,
                            roll = pose.roll + rotation,
                            scale = (pose.scale * zoom).coerceIn(0.4f, 2.5f),
                        )
                    )
                }
            },
    ) {
        AsyncImage(
            model = imageUrl,
            contentDescription = "Camera frame to label",
            modifier = Modifier.fillMaxSize(),
            contentScale = ContentScale.Fit,
        )

        if (boxSize.width > 0f) {
            val perImagePx = boxSize.width / canvasPx
            val spriteDisplayPx = spritePxAtScale1 * perImagePx
            val spriteDp = with(density) { spriteDisplayPx.toDp() }

            // The sprite is drawn centred on the box, then moved so its centre
            // lands on the pose. Rotation and scale are applied about that same
            // centre, matching the renderer's scale-rotate-translate order.
            AsyncImage(
                model = spriteUrl,
                contentDescription = "Ghost outline",
                modifier = Modifier
                    .align(Alignment.TopStart)
                    .size(spriteDp)
                    .graphicsLayer {
                        translationX = pose.x * perImagePx - spriteDisplayPx / 2f
                        translationY = pose.y * perImagePx - spriteDisplayPx / 2f
                        rotationZ = pose.roll
                        scaleX = pose.scale
                        scaleY = pose.scale
                        alpha = if (enabled) 0.92f else 0.7f
                    },
            )

            if (glow > 0f) {
                SnapGlow(
                    centre = Offset(pose.x * perImagePx, pose.y * perImagePx),
                    // Sized from the true scale, not the user's pinch, so the
                    // ring is a fixed target rather than something that grows
                    // as they zoom.
                    //
                    // The sprite canvas is SPRITE_CANVAS_RATIO times the
                    // object's own extent, so the factor divides that back out;
                    // using the raw sprite size put the ring most of the way
                    // across the frame and read as a full-screen wash rather
                    // than a confirmation on the object.
                    radiusPx = spriteDisplayPx * (truth?.scale ?: 1f) * GLOW_RADIUS_FACTOR,
                    strength = glow,
                )
            }
        }
    }
}

/** Practice-only confirmation that the ghost is on target. */
@Composable
private fun SnapGlow(centre: Offset, radiusPx: Float, strength: Float) {
    Canvas(Modifier.fillMaxSize()) {
        drawCircle(
            color = GhostGreen.copy(alpha = 0.30f * strength),
            radius = radiusPx,
            center = centre,
        )
        drawCircle(
            color = GhostGreen.copy(alpha = 0.85f * strength),
            radius = radiusPx,
            center = centre,
            style = Stroke(width = 4f),
        )
    }
}
