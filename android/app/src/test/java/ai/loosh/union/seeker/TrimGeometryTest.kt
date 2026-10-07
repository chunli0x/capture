package ai.loosh.union.seeker

import org.junit.Assert.*
import org.junit.Test

class TrimGeometryTest {
    @Test
    fun clampsBothEndpointsToClipDuration() {
        assertEquals(TrimRange(0, 5000), trimRange(-100, 5000, 10_000))
        assertEquals(TrimRange(5000, 10_000), trimRange(5000, 99_999, 10_000))
        assertEquals(TrimRange(0, 10_000), trimRange(-5, 99_999, 10_000))
        assertEquals(TrimRange(1234, 5678), trimRange(1234, 5678, 10_000))
    }

    @Test
    fun rejectsZeroLengthAndInvertedTrims() {
        assertNull(trimRange(5000, 5000, 10_000))
        assertNull(trimRange(7000, 3000, 10_000))
        assertNull(trimRange(10_000, 10_000, 10_000))
    }

    @Test
    fun rejectsNonpositiveDuration() {
        assertNull(trimRange(0, 1000, 0))
        assertNull(trimRange(0, 1000, -1))
    }

    @Test
    fun scrubberFractionMapsToIntegerMilliseconds() {
        assertEquals(0, scrubToMs(0f, 10_000))
        assertEquals(10_000, scrubToMs(1f, 10_000))
        assertEquals(5000, scrubToMs(0.5f, 10_000))
        assertEquals(10_000, scrubToMs(2f, 10_000)) // clamped to 1
        assertEquals(0, scrubToMs(-0.5f, 10_000)) // clamped to 0
    }

    @Test
    fun durationCapHoldsAtThirtySeconds() {
        assertEquals(30_000, cappedDurationMs(99_000))
        assertEquals(15_000, cappedDurationMs(15_000))
        assertEquals(0, cappedDurationMs(0))
        assertEquals(0, cappedDurationMs(-5))
        assertEquals(30_000, cappedDurationMs(MAX_ACTION_MS))
    }
}
