package ai.loosh.union.seeker

import kotlin.math.min

/** Hard cap on an action clip's duration, matching the backend's ≤ 30 s bound. */
const val MAX_ACTION_MS = 30_000

/**
 * A valid action trim: integer milliseconds with `startMs < endMs`, both within
 * the recorded clip's duration. The invariant is enforced by [trimRange]; do not
 * hand-construct one from raw user input.
 */
data class TrimRange(val startMs: Int, val endMs: Int)

/**
 * Coerces raw scrubber inputs into a valid trim within a clip of [durationMs].
 * Both endpoints are integer milliseconds clamped to `[0, durationMs]`, and
 * `startMs < endMs` must hold after clamping. Returns null when no nonempty
 * in-range trim exists (nonpositive duration, or a zero-length / inverted span).
 */
fun trimRange(startMs: Int, endMs: Int, durationMs: Int): TrimRange? {
    if (durationMs <= 0) return null
    val a = startMs.coerceIn(0, durationMs)
    val b = endMs.coerceIn(0, durationMs)
    if (a >= b) return null
    return TrimRange(a, b)
}

/** Maps a scrubber track fraction in `[0, 1]` to integer milliseconds within [durationMs]. */
fun scrubToMs(fraction: Float, durationMs: Int): Int =
    (fraction.coerceIn(0f, 1f) * durationMs).toInt()

/** Hard cap so a recorded action clip never exceeds [MAX_ACTION_MS]. */
fun cappedDurationMs(recordedMs: Int): Int =
    if (recordedMs <= 0) 0 else min(recordedMs, MAX_ACTION_MS)
