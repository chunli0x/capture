package ai.loosh.union.seeker

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.spring
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import ai.loosh.union.CaptureAccent
import ai.loosh.union.CaptureAccentBright
import ai.loosh.union.CaptureRadii
import ai.loosh.union.ErrorRed
import ai.loosh.union.MutedGray

/**
 * Shared chip primitives for every picker in the label editor. All three
 * primary pickers (object/place/action) render the *same* component so the
 * empty / selected / error vocabulary is identical across the app; secondary
 * pickers reuse the same blue accent and a dismiss glyph.
 *
 * States:
 *  - Empty      : muted outline, gray label (chip not in the selection set)
 *  - Selected   : filled with [accent], white label, trailing glyph
 *  - Error      : red outline + a short inline message rendered by the caller
 *                 next to the field
 */

enum class ChipGlyph { NONE, CHECK, DISMISS }

/** A single-select/stateful chip with spring settle on the fill + scale. */
@Composable
fun LabelChip(
    label: String,
    selected: Boolean,
    accent: Color,
    enabled: Boolean = true,
    glyph: ChipGlyph = ChipGlyph.NONE,
    isError: Boolean = false,
    onClick: () -> Unit,
) {
    val shape = CaptureRadii.pill
    val fill by animateColorAsState(
        targetValue = if (selected) accent else Color.Transparent,
        animationSpec = spring(dampingRatio = Spring.DampingRatioMediumBouncy, stiffness = Spring.StiffnessMedium),
        label = "chip-fill",
    )
    val border by animateColorAsState(
        targetValue =
            when {
                isError -> ErrorRed
                selected -> accent
                else -> MutedGray.copy(alpha = 0.45f)
            },
        animationSpec = spring(dampingRatio = Spring.DampingRatioMediumBouncy, stiffness = Spring.StiffnessMedium),
        label = "chip-border",
    )
    val scale by animateFloatAsState(
        targetValue = if (selected) 1.04f else 1f,
        animationSpec = spring(dampingRatio = Spring.DampingRatioMediumBouncy, stiffness = Spring.StiffnessLow),
        label = "chip-scale",
    )
    val labelColor =
        when {
            isError -> ErrorRed
            selected -> Color.White
            else -> MaterialTheme.colorScheme.onSurface
        }
    Surface(
        modifier = Modifier.scale(scale),
        shape = shape,
        color = fill,
        border = BorderStroke(1.dp, border),
    ) {
        Row(
            modifier = Modifier
                .clickable(enabled = enabled) { onClick() }
                .padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            if (glyph == ChipGlyph.CHECK && selected) {
                Text("\u2713", color = Color.White, fontWeight = FontWeight.Bold)
            }
            Text(
                label,
                color = labelColor,
                style = MaterialTheme.typography.labelMedium,
                fontWeight = FontWeight.Medium,
            )
            if (glyph == ChipGlyph.DISMISS && selected) {
                Text("\u2715", color = Color.White, fontWeight = FontWeight.Bold)
            }
        }
    }
}

/** Wrapping flow of chips; 8dp rhythm both axes so many categories never force a long scroll. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun LabelChipFlow(content: @Composable () -> Unit) {
    FlowRow(
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) { content() }
}

/** The persistent "choose one … to continue" helper shown above a primary picker. */
@Composable
fun PickerHelper(text: String, required: Boolean = false) {
    Text(
        buildString {
            append(text)
            if (required) append(" — Required")
        },
        style = MaterialTheme.typography.bodySmall,
        color =
            if (required) ErrorRed
            else MaterialTheme.colorScheme.onSurface.copy(alpha = 0.62f),
    )
}

/** Small count/selected badge next to a group header (e.g. "2 selected"). */
@Composable
fun CountBadge(text: String) {
    Surface(
        shape = CaptureRadii.pill,
        color = CaptureAccent.copy(alpha = 0.18f),
    ) {
        Text(
            text,
            style = MaterialTheme.typography.labelSmall,
            color = CaptureAccentBright,
            modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp),
        )
    }
}
