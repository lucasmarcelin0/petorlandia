import unittest
from io import BytesIO
from unittest.mock import patch

from PIL import Image

from logo_processing import prepare_logo


class LogoProcessingTests(unittest.TestCase):
    def process(self, image, clean=False, format='PNG'):
        stream = BytesIO()
        image.save(stream, format=format)
        stream.seek(0)
        return Image.open(prepare_logo(stream, clean)).convert('RGB')

    def test_transparency_becomes_white_and_colors_survive(self):
        image = Image.new('RGBA', (3, 1), (0, 0, 0, 0))
        image.putpixel((1, 0), (200, 0, 0, 255))
        image.putpixel((2, 0), (0, 0, 0, 128))
        result = self.process(image)
        self.assertEqual(result.getpixel((0, 0)), (255, 255, 255))
        self.assertEqual(result.getpixel((1, 0)), (200, 0, 0))
        self.assertEqual(result.getpixel((2, 0)), (127, 127, 127))

    def test_cleanup_is_optional_and_preserves_enclosed_gray_and_colors(self):
        image = Image.new('RGB', (9, 9), 'white')
        for y in range(9):
            for x in range(9):
                image.putpixel((x, y), (190, 190, 190) if (x + y) % 2 else (245, 245, 245))
        for x in range(2, 7):
            image.putpixel((x, 2), (0, 0, 0))
            image.putpixel((x, 6), (0, 0, 0))
        for y in range(2, 7):
            image.putpixel((2, y), (0, 0, 0))
            image.putpixel((6, y), (0, 0, 0))
        image.putpixel((0, 4), (20, 180, 30))
        self.assertEqual(self.process(image).getpixel((0, 1)), (190, 190, 190))
        result = self.process(image, True)
        self.assertEqual(result.getpixel((0, 1)), (255, 255, 255))
        self.assertEqual(result.getpixel((0, 4)), (20, 180, 30))
        self.assertEqual(result.getpixel((3, 4)), (190, 190, 190))
        self.assertEqual(result.getpixel((2, 4)), (0, 0, 0))

    def test_palette_transparency(self):
        image = Image.new('P', (2, 1), 0)
        image.putpalette([0, 0, 0, 255, 0, 0] + [0] * 762)
        image.info['transparency'] = 0
        image.putpixel((1, 0), 1)
        result = self.process(image)
        self.assertEqual(list(result.getdata()), [(255, 255, 255), (255, 0, 0)])

    def test_jpeg_and_size_limit(self):
        result = self.process(Image.new('RGB', (2000, 1000), 'red'), format='JPEG')
        self.assertEqual(result.size, (1600, 800))
        with patch('logo_processing.MAX_LOGO_PIXELS', 10):
            with self.assertRaises(ValueError):
                self.process(Image.new('RGB', (4, 4)))

    def test_invalid_image_has_actionable_error(self):
        with self.assertRaisesRegex(ValueError, 'imagem válida'):
            prepare_logo(BytesIO(b'invalid'))


if __name__ == '__main__':
    unittest.main()
