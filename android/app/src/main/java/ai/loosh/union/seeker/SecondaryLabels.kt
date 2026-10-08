package ai.loosh.union.seeker

/**
 * The three optional secondary metadata namespaces a label can carry.
 *
 * All ids are drawn verbatim from the `GET /taxonomy` registry — chips render
 * only registry categories, so an unknown id can never be minted client-side.
 * Every field defaults empty; empty arrays are omitted from the wire payload.
 */
data class SecondarySelection(
    val expressions: List<Int> = emptyList(),
    val postures: List<Int> = emptyList(),
    val environment: List<Int> = emptyList(),
)

/**
 * One `environment` sub-group with its categories. The backend constrains
 * environment to one id per group, so the picker renders each group under its
 * own subheading and enforces at-most-one selection within it.
 */
data class EnvironmentGroup(val name: String, val categories: List<TaxonomyCategory>)

/**
 * Filters the registry to a single kind namespace by exact match (server order
 * preserved). Unlike [categoriesForKind], an unknown kind does NOT fall back to
 * object — the secondary namespaces have no default and simply render nothing.
 */
fun categoriesOfKind(taxonomy: List<TaxonomyCategory>, kind: String): List<TaxonomyCategory> =
    taxonomy.filter { it.kind == kind }

/**
 * Groups environment categories by their `group` field, preserving the
 * registry's first-seen order for both the groups and the members within them.
 * Environment entries missing a group are collected under an empty-name group
 * so no chip is silently dropped.
 */
fun environmentGroups(taxonomy: List<TaxonomyCategory>): List<EnvironmentGroup> {
    val env = taxonomy.filter { it.kind == KIND_ENVIRONMENT }
    return env.map { it.group.orEmpty() }.distinct().map { name ->
        EnvironmentGroup(name, env.filter { it.group.orEmpty() == name })
    }
}

/**
 * Toggles an environment id with at-most-one-per-group enforcement:
 * - Tapping a selected id deselects it.
 * - Tapping an unselected id selects it and deselects any currently selected
 *   id in the same group.
 * - An id absent from the registry (or an environment entry without a group)
 *   is a no-op, so an unknown id can never be selected client-side.
 */
fun toggleEnvironmentSelection(
    taxonomy: List<TaxonomyCategory>,
    selected: List<Int>,
    tappedId: Int,
): List<Int> {
    if (tappedId in selected) return selected - tappedId
    val tapped =
        taxonomy.firstOrNull { it.kind == KIND_ENVIRONMENT && it.id == tappedId }
            ?: return selected
    val group = tapped.group ?: return selected
    val sameGroup =
        taxonomy
            .filter { it.kind == KIND_ENVIRONMENT && it.group == group }
            .map { it.id }
            .toSet()
    return selected.filter { it !in sameGroup } + tappedId
}

/**
 * Maps the three optional secondary id lists to wire field names, omitting any
 * that are empty. This is the exact contract the backend expects: `expressions`,
 * `postures`, and `environment` appear only when non-empty.
 */
fun secondaryLabelFields(
    expressions: List<Int>,
    postures: List<Int>,
    environment: List<Int>,
): Map<String, List<Int>> =
    buildMap {
        if (expressions.isNotEmpty()) put("expressions", expressions)
        if (postures.isNotEmpty()) put("postures", postures)
        if (environment.isNotEmpty()) put("environment", environment)
    }
