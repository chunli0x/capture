package ai.loosh.union.seeker

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Pure-logic tests for the six-dimension secondary labels, mirroring the three
 * backend rules: (1) unknown ids can never be selected client-side because
 * chips come from the server registry, (2) at most one environment id per
 * group, and (3) empty secondary arrays are omitted from the payload.
 */
class SecondaryLabelsTest {

    private val taxonomy =
        listOf(
            TaxonomyCategory(1, "cup", KIND_OBJECT),
            TaxonomyCategory(10, "happy", KIND_EXPRESSION),
            TaxonomyCategory(11, "neutral", KIND_EXPRESSION),
            TaxonomyCategory(20, "sitting", KIND_POSTURE),
            TaxonomyCategory(30, "indoor", KIND_ENVIRONMENT, "indoor_outdoor"),
            TaxonomyCategory(31, "outdoor", KIND_ENVIRONMENT, "indoor_outdoor"),
            TaxonomyCategory(40, "day", KIND_ENVIRONMENT, "time"),
            TaxonomyCategory(41, "night", KIND_ENVIRONMENT, "time"),
        )

    @Test
    fun categoriesOfKindFiltersEachNamespaceExactly() {
        assertEquals(listOf(10, 11), categoriesOfKind(taxonomy, KIND_EXPRESSION).map { it.id })
        assertEquals(listOf(20), categoriesOfKind(taxonomy, KIND_POSTURE).map { it.id })
        assertEquals(
            listOf(30, 31, 40, 41),
            categoriesOfKind(taxonomy, KIND_ENVIRONMENT).map { it.id },
        )
        assertEquals(listOf(1), categoriesOfKind(taxonomy, KIND_OBJECT).map { it.id })
    }

    @Test
    fun categoriesOfKindDoesNotFallBackToObject() {
        // Secondary namespaces have no default kind — an unknown kind yields nothing.
        assertTrue(categoriesOfKind(taxonomy, "expression_typo").isEmpty())
        assertTrue(categoriesOfKind(emptyList(), KIND_EXPRESSION).isEmpty())
    }

    @Test
    fun environmentGroupsPartitionsByGroupInRegistryOrder() {
        val groups = environmentGroups(taxonomy)

        assertEquals(listOf("indoor_outdoor", "time"), groups.map { it.name })
        assertEquals(listOf(30, 31), groups[0].categories.map { it.id })
        assertEquals(listOf(40, 41), groups[1].categories.map { it.id })
    }

    @Test
    fun environmentSelectionAllowsAtMostOnePerGroup() {
        // Select "indoor" (group indoor_outdoor), then "outdoor" (same group) replaces it.
        val afterIndoor = toggleEnvironmentSelection(taxonomy, emptyList(), 30)
        assertEquals(listOf(30), afterIndoor)

        val afterOutdoor = toggleEnvironmentSelection(taxonomy, afterIndoor, 31)
        assertEquals(listOf(31), afterOutdoor)
    }

    @Test
    fun environmentSelectionKeepsDistinctGroupsIndependent() {
        // indoor (indoor_outdoor) + day (time) coexist; switching time to night
        // only affects the time group.
        val selected = listOf(30, 40)
        val afterNight = toggleEnvironmentSelection(taxonomy, selected, 41)

        assertEquals(setOf(30, 41), afterNight.toSet())
    }

    @Test
    fun environmentSelectionTogglesOffWhenTappedAgain() {
        val selected = listOf(30, 40)
        assertEquals(listOf(40), toggleEnvironmentSelection(taxonomy, selected, 30))
    }

    @Test
    fun unknownIdCannotBeSelectedClientSide() {
        // Id 999 is not in the registry; a tap on it is a no-op.
        assertEquals(emptyList<Int>(), toggleEnvironmentSelection(taxonomy, emptyList(), 999))
        assertEquals(listOf(30), toggleEnvironmentSelection(taxonomy, listOf(30), 999))
    }

    @Test
    fun environmentEntryWithoutGroupCannotBeSelected() {
        val taxonomyWithGroupless =
            listOf(TaxonomyCategory(50, "unknown", KIND_ENVIRONMENT, null))
        assertEquals(
            emptyList<Int>(),
            toggleEnvironmentSelection(taxonomyWithGroupless, emptyList(), 50),
        )
    }

    @Test
    fun emptySecondaryArraysAreOmittedFromPayload() {
        val fields = secondaryLabelFields(emptyList(), emptyList(), emptyList())
        assertTrue(fields.isEmpty())
    }

    @Test
    fun onlyNonEmptySecondaryArraysAppearInPayload() {
        val fields = secondaryLabelFields(listOf(10, 11), emptyList(), listOf(30))

        assertEquals(setOf("expressions", "environment"), fields.keys)
        assertEquals(listOf(10, 11), fields["expressions"])
        assertEquals(listOf(30), fields["environment"])
        assertFalse("postures" in fields)
    }
}
