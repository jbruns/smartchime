"""Tests for the luma_patch module."""

import sys
from unittest.mock import MagicMock


class TestLumaPatch:
    """Tests for apply_luma_patch() and the patched refresh function."""

    def test_apply_luma_patch_returns_true(self):
        """apply_luma_patch() returns True when luma module is available (mocked)."""
        from smartchime.luma_patch import apply_luma_patch

        result = apply_luma_patch()

        assert result is True

    def test_apply_luma_patch_replaces_refresh(self):
        """After calling apply_luma_patch(), ImageComposition.refresh is the patched function (not a MagicMock)."""
        from smartchime.luma_patch import apply_luma_patch

        apply_luma_patch()

        # The patch traverses the mock attribute chain from sys.modules["luma"]
        luma_mock = sys.modules["luma"]
        refresh = luma_mock.core.image_composition.ImageComposition.refresh
        assert not isinstance(refresh, MagicMock)
        assert callable(refresh)

    def test_patched_refresh_calls_clear_paste_crop(self):
        """The patched refresh calls _clear(), _background_image.paste(), and _background_image.crop() correctly."""
        from smartchime.luma_patch import apply_luma_patch

        apply_luma_patch()

        # Retrieve the patched function via the mock attribute chain
        luma_mock = sys.modules["luma"]
        patched_refresh = luma_mock.core.image_composition.ImageComposition.refresh

        composed_img = MagicMock()
        composed_img.image = MagicMock(name="image_data")
        composed_img.position = (10, 20)

        mock_self = MagicMock()
        mock_self.composed_images = [composed_img]
        mock_self._device.bounding_box = (0, 0, 128, 32)

        patched_refresh(mock_self)

        mock_self._clear.assert_called_once()
        mock_self._background_image.paste.assert_called_once_with(composed_img.image, (10, 20))
        mock_self._background_image.crop.assert_called_once_with(box=(0, 0, 128, 32))

    def test_apply_luma_patch_returns_false_on_error(self, monkeypatch):
        """apply_luma_patch() returns False when the luma import fails."""
        monkeypatch.delitem(sys.modules, "luma.core.image_composition", raising=False)

        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def failing_import(name, *args, **kwargs):
            if name == "luma.core.image_composition":
                raise ImportError("No module named 'luma.core.image_composition'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", failing_import)

        from smartchime.luma_patch import apply_luma_patch

        result = apply_luma_patch()

        assert result is False
