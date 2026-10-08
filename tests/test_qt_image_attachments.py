"""An attached image must reach the provider as a prepared ImageAttachment."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from src.image_attachments import ImageAttachment, ImageAttachmentError, prepare_image


def _minimal_png_bytes():
    """A real 1x1 PNG, built with Pillow, written by the caller to disk."""
    import io
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (10, 120, 200)).save(buffer, format="PNG")
    return buffer.getvalue()


class TestProviderReplyWithImages(unittest.TestCase):
    """provider_reply_text must hand ImageAttachment objects to the client."""

    def _png_file(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(lambda: None)
        path = Path(directory) / "capture.png"
        path.write_bytes(_minimal_png_bytes())
        return path

    def test_png_reaches_the_client_as_attachment(self):
        from src.qt_chat import provider_reply_text
        path = self._png_file()
        prepared = prepare_image(path)
        client = Mock()
        client.chat.return_value = "the answer"
        text, error = provider_reply_text(
            client, [{"role": "user", "content": "what is this?"}],
            image_paths=[prepared])
        self.assertIsNone(error)
        self.assertEqual(text, "the answer")
        images = client.chat.call_args.kwargs.get("images")
        self.assertIsNotNone(images)
        self.assertEqual(len(images), 1)
        attachment = images[0]
        self.assertIsInstance(attachment, ImageAttachment)
        self.assertTrue(attachment.data)
        # The client received the prepared snapshot, never the file path.
        self.assertNotIn(str(path), repr(client.chat.call_args))

    def test_paths_are_not_accepted_as_images(self):
        from src.qt_chat import provider_reply_text
        client = Mock()
        text, error = provider_reply_text(
            client, [{"role": "user", "content": "hi"}],
            image_paths=[str(self._png_file())])
        # A bare path is not a prepared snapshot: the request is refused,
        # never silently sent without the image.
        self.assertIsNone(text)
        self.assertTrue(error and error.startswith("image:"), error)
        client.chat.assert_not_called()

    def test_invalid_snapshot_refuses_without_chat(self):
        from src.qt_chat import provider_reply_text
        client = Mock()
        text, error = provider_reply_text(
            client, [{"role": "user", "content": "hi"}],
            image_paths=["not-an-attachment"])
        self.assertIsNone(text)
        self.assertTrue(error and error.startswith("image:"), error)
        client.chat.assert_not_called()


class TestPrepareAttachmentRefusesLinks(unittest.TestCase):
    """The UI-thread preparation refuses symlinks before reading."""

    def test_symlink_never_reaches_the_client(self):
        from src.qt_chat import QtChatWidget
        real = Path(tempfile.mkdtemp()) / "real.png"
        real.write_bytes(_minimal_png_bytes())
        link = real.with_name("link.png")
        try:
            os.symlink(real, link)
        except (OSError, NotImplementedError) as error:
            self.skipTest("The OS refused to create the symlink: " + str(error))
        # The UI-thread helper must raise before any read.
        with self.assertRaises(ImageAttachmentError) as raised:
            QtChatWidget._prepare_attachment(str(link))
        self.assertIn("link", str(raised.exception).lower())

    def test_regular_png_prepares(self):
        from src.qt_chat import QtChatWidget
        path = Path(tempfile.mkdtemp()) / "regular.png"
        path.write_bytes(_minimal_png_bytes())
        attachment = QtChatWidget._prepare_attachment(str(path))
        self.assertIsInstance(attachment, ImageAttachment)
        self.assertTrue(attachment.data)


if __name__ == "__main__":
    unittest.main()
