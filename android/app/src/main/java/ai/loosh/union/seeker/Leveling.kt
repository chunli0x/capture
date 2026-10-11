package ai.loosh.union.seeker

import kotlin.math.roundToInt

/**
 * The v2 level ladder, pinned by the Capture v2 contract (levels 0..4).
 *
 * Kept free of `org.json` and Android so every leveling decision is unit
 * testable on the JVM. The ViewModel reads `/me` and hands raw primitives to
 * these functions; nothing here reaches the network.
 */

const val MAX_LEVEL = 4

/**
 * One rung of the level ladder. [acceptedThreshold] is the cumulative accepted
 * count at which a worker *becomes* this level; [rateThresholdPercent] is the
 * rolling acceptance-rate gate for that level (null at level 0, where there is
 * no gate). [bondMultiplier] of 0.0 means the bond is waived.
 */
data class LevelTier(
    val level: Int,
    val name: String,
    val acceptedThreshold: Int,
    val rateThresholdPercent: Int?,
    val rateMultiplier: Double,
    val bondMultiplier: Double,
)

/** Contract table, in ascending level order. Do not reorder. */
val LEVEL_TIERS: List<LevelTier> =
    listOf(
        LevelTier(0, "Scout", 0, null, 1.00, 2.0),
        LevelTier(1, "Regular", 25, 90, 1.10, 1.5),
        LevelTier(2, "Veteran", 100, 95, 1.20, 1.0),
        LevelTier(3, "Expert", 500, 97, 1.35, 0.5),
        LevelTier(4, "Pathfinder", 2000, 98, 1.50, 0.0),
    )

/** The tier for a level, clamped into the valid range. */
fun levelTier(level: Int): LevelTier = LEVEL_TIERS[level.coerceIn(0, MAX_LEVEL)]

/**
 * The highest level whose cumulative accepted threshold is met. A worker with
 * 24 accepted captures is still a Scout (level 0); 25 makes them a Regular.
 */
fun levelFrom(acceptedCount: Int): Int =
    LEVEL_TIERS.indexOfLast { acceptedCount >= it.acceptedThreshold }.coerceAtLeast(0)

fun levelName(level: Int): String = levelTier(level).name

/**
 * Progress toward the next level, as a fraction in `[0, 1]`, measured purely on
 * the cumulative accepted count. At the top level the fraction is 1 (full).
 */
data class LevelProgress(
    val current: Int,
    val next: Int?,
    val accepted: Int,
    val currentThreshold: Int,
    val nextThreshold: Int?,
) {
    val fraction: Float
        get() {
            val nextThreshold = nextThreshold ?: return 1f
            val span = nextThreshold - currentThreshold
            if (span <= 0) return 1f
            return ((accepted - currentThreshold).toFloat() / span).coerceIn(0f, 1f)
        }
}

fun levelProgress(acceptedCount: Int): LevelProgress {
    val current = levelFrom(acceptedCount)
    val next = if (current < MAX_LEVEL) current + 1 else null
    return LevelProgress(
        current = current,
        next = next,
        accepted = acceptedCount,
        currentThreshold = levelTier(current).acceptedThreshold,
        nextThreshold = next?.let { levelTier(it).acceptedThreshold },
    )
}

/**
 * Renders an acceptance rate as a whole percent. Accepts both the fraction
 * convention (0.92 -> 92) and an already-percent value (92 -> 92), so a backend
 * that switches representation does not silently produce a nonsense number.
 */
fun acceptancePercent(rate: Double): Int =
    if (rate.isFinite() && rate in 0.0..1.0) {
        (rate * 100).roundToInt().coerceIn(0, 100)
    } else {
        rate.toInt().coerceIn(0, 100)
    }
