"""Monkey patch for luma.oled to work with modern Pillow versions."""

import logging

logger = logging.getLogger(__name__)


def apply_luma_patch():
    """Apply monkey patch to fix 'Image' object is not callable error."""
    try:
        import luma.core.image_composition

        def patched_refresh(self):
            self._clear()
            for img in self.composed_images:
                self._background_image.paste(img.image, (img.position[0], img.position[1]))
            self._background_image.crop(box=self._device.bounding_box)

        luma.core.image_composition.ImageComposition.refresh = patched_refresh

        logger.info("Successfully applied luma.core patch for Pillow compatibility")
        return True

    except Exception as e:
        logger.error(f"Failed to apply luma.core patch: {e}", exc_info=True)
        return False


# Apply patch immediately when module is imported
success = apply_luma_patch()
