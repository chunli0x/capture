package ai.loosh.union.seeker

import org.junit.Assert.*
import org.junit.Test

class BoxGeometryTest {
    @Test
    fun reverseDragUsesTopLeft() {
        val box = dragBox(4, .8f, .7f, .2f, .1f)!!
        assertEquals(4, box.categoryId)
        assertEquals(.2f, box.x, .0001f)
        assertEquals(.1f, box.y, .0001f)
        assertEquals(.6f, box.w, .0001f)
        assertEquals(.6f, box.h, .0001f)
    }

    @Test
    fun clampsOutsideImageAndRejectsEmptyOrNonfinite() {
        assertEquals(LabelBox(1, 0f, 0f, 1f, 1f), dragBox(1, -1f, -1f, 2f, 2f))
        assertNull(dragBox(1, .1f, .1f, .1f, .5f))
        assertNull(dragBox(1, Float.NaN, 0f, 1f, 1f))
        assertNull(dragBox(1, 0f, 0f, Float.POSITIVE_INFINITY, 1f))
    }
}
