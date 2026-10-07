package ai.loosh.union.seeker

import org.junit.Assert.*
import org.junit.Test

class ScenePickerTest {
    private val taxonomy = setOf(11, 22, 33)

    @Test
    fun selectsExactlyOneKnownScene() {
        assertEquals(SceneLabel(22), sceneLabel(22, taxonomy))
        assertEquals(11, sceneLabel(11, taxonomy)!!.categoryId)
    }

    @Test
    fun rejectsUnknownCategories() {
        assertNull(sceneLabel(99, taxonomy))
    }

    @Test
    fun rejectsNoSelection() {
        assertNull(sceneLabel(null, taxonomy))
    }

    @Test
    fun actionLabelRequiresKnownTagAndValidTrim() {
        assertEquals(
            ActionLabel(11, 1000, 5000),
            actionLabel(11, taxonomy, TrimRange(1000, 5000)),
        )
        assertNull(actionLabel(99, taxonomy, TrimRange(1000, 5000)))
        assertNull(actionLabel(null, taxonomy, TrimRange(1000, 5000)))
        assertNull(actionLabel(11, taxonomy, null))
    }
}
