package ai.loosh.union.seeker

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Capture-metadata wire mapping and the revised label-schema completeness rule. */
class CaptureMetadataTest {

    @Test
    fun metadataFieldsOmitUnsetStringIdsAndAlwaysIncludeEgoMotion() {
        val fields = captureMetadataFields(SecondarySelection())

        assertEquals(setOf("ego_motion"), fields.keys)
        assertEquals(false, fields["ego_motion"])
    }

    @Test
    fun metadataFieldsIncludeSetStringIds() {
        val selection = SecondarySelection(surfaceType = "hardwood", lighting = "day", weather = "sun", egoMotion = true)
        val fields = captureMetadataFields(selection)

        assertEquals("hardwood", fields["surface_type"])
        assertEquals("day", fields["lighting"])
        assertEquals("sun", fields["weather"])
        assertEquals(true, fields["ego_motion"])
    }

    @Test
    fun categoryWireIdPrefersSlugOverNumericId() {
        assertEquals("hardwood", categoryWireId(TaxonomyCategory(12, "Hardwood", KIND_SURFACE_TYPE, slug = "hardwood")))
        assertEquals("12", categoryWireId(TaxonomyCategory(12, "Hardwood", KIND_SURFACE_TYPE)))
    }

    @Test
    fun labelIsCompleteOnlyWithAPosture() {
        assertFalse(isLabelComplete(SecondarySelection()))
        assertFalse(isLabelComplete(SecondarySelection(expressions = listOf(1), environment = listOf(2))))
        assertTrue(isLabelComplete(SecondarySelection(postures = listOf(3))))
        assertTrue(isLabelComplete(SecondarySelection(postures = listOf(3), surfaceType = "carpet", egoMotion = true)))
    }
}
