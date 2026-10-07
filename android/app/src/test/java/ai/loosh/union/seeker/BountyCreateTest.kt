package ai.loosh.union.seeker

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The create-bounty payload builder turns chosen registry ids plus a kind into
 * a draft that the viewmodel serializes as `category_ids`. Checked as pure
 * functions — no Android, no network, no `org.json`.
 */
class BountyCreateTest {

    @Test
    fun objectIsTheDefaultKind() {
        val draft = buildBountyDraft(null, "Cups", listOf(3, 7), 1_000_000, 5, 1_700_000_000L)

        assertEquals(KIND_OBJECT, draft.kind)
        assertEquals(listOf(3, 7), draft.categoryIds)
    }

    @Test
    fun unknownOrBlankKindFallsBackToObject() {
        assertEquals(KIND_OBJECT, resolveKind("nonsense"))
        assertEquals(KIND_OBJECT, resolveKind(""))
        assertEquals(KIND_OBJECT, resolveKind("  "))
        assertEquals(KIND_OBJECT, resolveKind(null))
    }

    @Test
    fun placeKindThreadsTheSceneCategoryNamespace() {
        val draft = buildBountyDraft(KIND_PLACE, "Beach", listOf(11, 22), 2_000_000, 3, 1_700_000_000L)

        assertEquals(KIND_PLACE, draft.kind)
        assertEquals(listOf(11, 22), draft.categoryIds)
    }

    @Test
    fun actionKindThreadsTheActionCategoryNamespace() {
        val draft = buildBountyDraft(KIND_ACTION, "Wave", listOf(40, 41), 3_000_000, 4, 1_700_000_000L)

        assertEquals(KIND_ACTION, draft.kind)
        assertEquals(listOf(40, 41), draft.categoryIds)
    }

    @Test
    fun chosenIdsAreSentVerbatimAndDeduplicated() {
        val draft = buildBountyDraft(KIND_OBJECT, "T", listOf(5, 5, 9), 1, 1, 1L)

        assertEquals(listOf(5, 9), draft.categoryIds)
    }

    @Test
    fun carriesRewardSlotsTitleAndDeadlineThroughUnchanged() {
        val draft = buildBountyDraft(KIND_OBJECT, "Cups", listOf(3), 7_000_000, 42, 1_700_000_000L)

        assertEquals("Cups", draft.title)
        assertEquals(7_000_000L, draft.rewardUsdcUnits)
        assertEquals(42, draft.slots)
        assertEquals(1_700_000_000L, draft.deadline)
    }

    @Test
    fun categoriesForKindFiltersRegistryToTheSelectedNamespace() {
        val taxonomy =
            listOf(
                TaxonomyCategory(1, "cup", KIND_OBJECT),
                TaxonomyCategory(2, "beach", KIND_PLACE),
                TaxonomyCategory(3, "wave", KIND_ACTION),
                TaxonomyCategory(4, "mug", KIND_OBJECT),
            )

        assertEquals(listOf(1, 4), categoriesForKind(taxonomy, KIND_OBJECT).map { it.id })
        assertEquals(listOf(2), categoriesForKind(taxonomy, KIND_PLACE).map { it.id })
        assertEquals(listOf(3), categoriesForKind(taxonomy, KIND_ACTION).map { it.id })
        // Unknown kind falls back to object, matching resolveKind.
        assertEquals(listOf(1, 4), categoriesForKind(taxonomy, "nonsense").map { it.id })
    }

    @Test
    fun categoriesForKindReturnsEmptyForMissingNamespace() {
        val taxonomy = listOf(TaxonomyCategory(1, "cup", KIND_OBJECT))
        assertTrue(categoriesForKind(taxonomy, KIND_ACTION).isEmpty())
        assertTrue(categoriesForKind(emptyList(), KIND_OBJECT).isEmpty())
    }
}
