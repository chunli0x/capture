package ai.loosh.union.seeker

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Verdict/payout parsing decisions, kept pure so null handling is testable. */
class VerdictTest {

    @Test
    fun acceptedVerdictCarriesReasonAndIsPaid() {
        val result = buildSubmissionResult(accepted = true, reason = "ground-level ok", payoutUsdc = 250_000, levelAfter = 1)

        assertEquals(true, result.verdict?.accepted)
        assertEquals("ground-level ok", result.verdict?.reason)
        assertEquals(250_000, result.payoutUsdc)
        assertEquals(1, result.levelAfter)
        assertTrue(result.paid)
        assertFalse(result.rejected)
    }

    @Test
    fun rejectedVerdictCarriesReasonAndNoPayout() {
        val result = buildSubmissionResult(accepted = false, reason = "eye-level shot", payoutUsdc = 0, levelAfter = null)

        assertEquals(false, result.verdict?.accepted)
        assertTrue(result.rejected)
        assertFalse(result.paid)
        assertNull(result.levelAfter)
    }

    @Test
    fun missingVerdictMeansPendingNotRejected() {
        val result = buildSubmissionResult(accepted = null, reason = null, payoutUsdc = 0, levelAfter = null)

        assertNull(result.verdict)
        assertFalse(result.rejected)
        assertFalse(result.paid)
    }

    @Test
    fun nullReasonIsNormalizedToEmpty() {
        val result = buildSubmissionResult(accepted = true, reason = null, payoutUsdc = 100, levelAfter = null)
        assertEquals("", result.verdict?.reason)
    }
}
