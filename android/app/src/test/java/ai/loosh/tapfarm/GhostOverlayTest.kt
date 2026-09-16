package ai.loosh.tapfarm

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The overlay's pure maths.
 *
 * These three functions decide what the labeler is scored on, so they are worth
 * checking without a device: a wrong wrap or a bad clamp shows up as a task that
 * feels broken rather than as an obvious crash.
 */
class GhostOverlayTest {

    private val canvas = 512

    // -- roll wrapping ---------------------------------------------------------

    @Test
    fun `roll delta is the short way round`() {
        assertEquals(20f, rollDeltaDeg(350f, 10f), 0.001f)
        assertEquals(20f, rollDeltaDeg(10f, 350f), 0.001f)
    }

    @Test
    fun `roll delta handles negative angles`() {
        assertEquals(20f, rollDeltaDeg(-170f, 170f), 0.001f)
    }

    @Test
    fun `roll delta never exceeds 180`() {
        var angle = -720f
        while (angle <= 720f) {
            val delta = rollDeltaDeg(angle, 33f)
            assertTrue("delta out of range at $angle: $delta", delta in 0f..180f)
            angle += 7f
        }
    }

    @Test
    fun `a full turn is no rotation`() {
        assertEquals(0f, rollDeltaDeg(360f, 0f), 0.001f)
        assertEquals(0f, rollDeltaDeg(735f, 15f), 0.001f)
    }

    // -- snapping --------------------------------------------------------------

    private val truth = GhostPose(x = 250f, y = 250f, roll = 30f, scale = 1f)

    @Test
    fun `an exact match snaps`() {
        assertTrue(isSnapped(truth, truth))
    }

    @Test
    fun `snapping needs both translation and rotation`() {
        // Position perfect, rotation far off.
        assertFalse(isSnapped(truth.copy(roll = 90f), truth))
        // Rotation perfect, position far off.
        assertFalse(isSnapped(truth.copy(x = 400f), truth))
    }

    @Test
    fun `snapping tolerates small error`() {
        assertTrue(isSnapped(truth.copy(x = 258f, roll = 35f), truth))
    }

    @Test
    fun `snapping works across the wrap point`() {
        val nearZero = GhostPose(x = 250f, y = 250f, roll = 2f, scale = 1f)
        val atWrap = nearZero.copy(roll = 357f)
        assertTrue("5 degrees apart across 0 should snap", isSnapped(atWrap, nearZero))
    }

    @Test
    fun `scale does not affect snapping`() {
        // Scale is auxiliary and unscored; it must not gate the glow either.
        assertTrue(isSnapped(truth.copy(scale = 2.4f), truth))
    }

    // -- clamping --------------------------------------------------------------

    @Test
    fun `a pose inside the frame is untouched`() {
        val inside = GhostPose(100f, 200f, 45f, 1.2f)
        assertEquals(inside, clampToCanvas(inside, canvas))
    }

    @Test
    fun `the ghost cannot be dragged off the frame`() {
        val lost = GhostPose(-9000f, 9000f, 0f, 1f)
        val clamped = clampToCanvas(lost, canvas)
        assertEquals(0f, clamped.x, 0.001f)
        assertEquals(canvas.toFloat(), clamped.y, 0.001f)
    }

    @Test
    fun `clamping preserves roll and scale`() {
        val clamped = clampToCanvas(GhostPose(-50f, -50f, 123f, 0.7f), canvas)
        assertEquals(123f, clamped.roll, 0.001f)
        assertEquals(0.7f, clamped.scale, 0.001f)
    }

    @Test
    fun `the frame edges are reachable`() {
        // An object sitting against an edge must still be matchable.
        val edge = GhostPose(0f, canvas.toFloat(), 0f, 1f)
        assertEquals(edge, clampToCanvas(edge, canvas))
    }

    // -- glow sizing -----------------------------------------------------------

    @Test
    fun `glow ring sits near the object edge, not across the frame`() {
        // The sprite canvas is padded so rotation never clips it. Sizing the
        // ring off the raw sprite made it wash over most of the image; the
        // factor divides that padding back out.
        val spriteCanvasPx = 450f          // wrench sprite, scale 1.0
        val objectExtentPx = spriteCanvasPx / SPRITE_CANVAS_RATIO
        val radius = spriteCanvasPx * GLOW_RADIUS_FACTOR

        assertTrue("ring collapsed onto the centre", radius > objectExtentPx * 0.4f)
        assertTrue("ring larger than the object itself", radius < objectExtentPx * 0.75f)
    }
}
