from __future__ import annotations

from io import BytesIO
import unittest

from PIL import Image

from karpy_platform.core.media.service import MediaValidationError, RvMediaService


class MediaProcessingSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = RvMediaService()
        self.values = {
            "media_image_processing_library": "pillow",
            "media_keep_original_file_size_and_quality": "0",
        }

    @staticmethod
    def png(width: int = 2, height: int = 2) -> bytes:
        output = BytesIO()
        Image.new("RGB", (width, height), "white").save(output, format="PNG")
        return output.getvalue()

    def test_valid_image_is_decoded_and_reencoded(self) -> None:
        content, name, mime = self.service._prepare_upload_content("image.png", "image/png", self.png(), self.values)
        self.assertEqual(name, "image.png")
        self.assertEqual(mime, "image/png")
        with Image.open(BytesIO(content)) as image:
            self.assertEqual(image.size, (2, 2))

    def test_malformed_image_is_rejected_instead_of_stored_raw(self) -> None:
        with self.assertRaises(MediaValidationError):
            self.service._prepare_upload_content("image.png", "image/png", b"not-an-image", self.values)

    def test_pillow_decompression_bomb_limit_is_enforced(self) -> None:
        original_limit = Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = 1
        try:
            with self.assertRaises(MediaValidationError):
                self.service._prepare_upload_content("image.png", "image/png", self.png(), self.values)
        finally:
            Image.MAX_IMAGE_PIXELS = original_limit


if __name__ == "__main__":
    unittest.main()
