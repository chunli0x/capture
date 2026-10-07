package ai.loosh.union.seeker

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * The create-bounty payload builder threads the bounty `kind` into every
 * category's `kind` field, matching the server's per-kind taxonomy namespaces.
 * Checked as a pure function — no Android, no network, no `org.json`.
 */
class BountyCreateTest {

    @Test
    fun objectIsTheDefaultKind() {
        val draft = buildBountyDraft(null, "Cups", "cup, mug", 1_000_000, 5, 1_700_000_000L)

        assertEquals(KIND_OBJECT, draft.kind)
        assertEquals(listOf("cup", "mug"), draft.categories.map { it.name })
        assertEquals(listOf(1, 2), draft.categories.map { it.id })
        draft.categories.forEach { assertEquals(KIND_OBJECT, it.kind) }
    }

    @Test
    fun unknownOrBlankKindFallsBackToObject() {
        assertEquals(KIND_OBJECT, buildBountyDraft("nonsense", "T", "a", 1, 1, 1L).kind)
        assertEquals(KIND_OBJECT, buildBountyDraft("", "T", "a", 1, 1, 1L).kind)
        val blank = buildBountyDraft("  ", "T", "a", 1, 1, 1L)
        assertEquals(KIND_OBJECT, blank.kind)
        assertEquals(KIND_OBJECT, blank.categories.single().kind)
    }

    @Test
    fun placeKindThreadsTheSceneCategoryNamespace() {
        val draft = buildBountyDraft(KIND_PLACE, "Beach", "beach, park", 2_000_000, 3, 1_700_000_000L)

        assertEquals(KIND_PLACE, draft.kind)
        assertEquals(2, draft.categories.size)
        draft.categories.forEach { assertEquals(KIND_PLACE, it.kind) }
        assertEquals(listOf("beach", "park"), draft.categories.map { it.name })
    }

    @Test
    fun actionKindThreadsTheActionCategoryNamespace() {
        val draft = buildBountyDraft(KIND_ACTION, "Wave", "wave, jump", 3_000_000, 4, 1_700_000_000L)

        assertEquals(KIND_ACTION, draft.kind)
        assertEquals(2, draft.categories.size)
        draft.categories.forEach { assertEquals(KIND_ACTION, it.kind) }
    }

    @Test
    fun blankCategoryEntriesAreSkipped() {
        val draft = buildBountyDraft(KIND_OBJECT, "T", "cup, , mug, ", 1, 1, 1L)

        assertEquals(listOf("cup", "mug"), draft.categories.map { it.name })
        assertEquals(listOf(1, 2), draft.categories.map { it.id })
    }

    @Test
    fun carriesRewardSlotsTitleAndDeadlineThroughUnchanged() {
        val draft = buildBountyDraft(KIND_OBJECT, "Cups", "cup", 7_000_000, 42, 1_700_000_000L)

        assertEquals("Cups", draft.title)
        assertEquals(7_000_000L, draft.rewardUsdcUnits)
        assertEquals(42, draft.slots)
        assertEquals(1_700_000_000L, draft.deadline)
    }
}
