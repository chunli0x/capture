package ai.loosh.union.seeker

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** The level ladder (0..4) is pure and pinned to the Capture v2 contract table. */
class LevelingTest {

    @Test
    fun levelZeroIsScoutUntilTwentyFiveAccepted() {
        assertEquals("Scout", levelName(0))
        assertEquals(0, levelFrom(0))
        assertEquals(0, levelFrom(24))
        assertEquals(1, levelFrom(25))
    }

    @Test
    fun cumulativeThresholdsStepThroughTheLadder() {
        assertEquals(1, levelFrom(99))
        assertEquals(2, levelFrom(100))
        assertEquals(3, levelFrom(500))
        assertEquals(4, levelFrom(2000))
        assertEquals(4, levelFrom(999_999))
    }

    @Test
    fun tierTableMatchesTheContract() {
        assertEquals(listOf("Scout", "Regular", "Veteran", "Expert", "Pathfinder"), LEVEL_TIERS.map { it.name })
        assertEquals(listOf(1.00, 1.10, 1.20, 1.35, 1.50), LEVEL_TIERS.map { it.rateMultiplier })
        assertEquals(listOf(2.0, 1.5, 1.0, 0.5, 0.0), LEVEL_TIERS.map { it.bondMultiplier })
        assertEquals(listOf(null, 90, 95, 97, 98), LEVEL_TIERS.map { it.rateThresholdPercent })
        assertEquals(listOf(0, 25, 100, 500, 2000), LEVEL_TIERS.map { it.acceptedThreshold })
    }

    @Test
    fun bondWaivedIsRepresentedAsZeroMultiplier() {
        assertEquals(0.0, levelTier(4).bondMultiplier, 0.0)
    }

    @Test
    fun progressFractionSpansCurrentToNextThreshold() {
        val mid = levelProgress(50) // Regular: 25..100
        assertEquals(1, mid.current)
        assertEquals(2, mid.next)
        assertEquals(25, mid.currentThreshold)
        assertEquals(100, mid.nextThreshold)
        assertEquals((50 - 25).toFloat() / (100 - 25).toFloat(), mid.fraction, 0.0001f)
    }

    @Test
    fun progressAtTopLevelIsFullAndHasNoNext() {
        val top = levelProgress(5000)
        assertEquals(4, top.current)
        assertNull(top.next)
        assertEquals(1f, top.fraction, 0f)
    }

    @Test
    fun acceptanceRateAcceptsFractionAndPercent() {
        assertEquals(92, acceptancePercent(0.92))
        assertEquals(90, acceptancePercent(90.0))
        assertEquals(0, acceptancePercent(0.0))
        assertEquals(100, acceptancePercent(1.0))
    }

    @Test
    fun levelTierClampsOutOfRange() {
        assertEquals("Scout", levelTier(-1).name)
        assertEquals("Pathfinder", levelTier(9).name)
    }
}
