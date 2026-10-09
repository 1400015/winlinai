"""The bytes sent must be the bytes the preview showed.

_add_attachment loads a QPixmap from the path, and the send re-reads
that path with prepare_image: replacing the file between the attach
and the send makes the preview and the payload diverge. The attachment
is now prepared and validated once, at attach time, and the send uses
that frozen snapshot; the preview renders attachment.data.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.image_attachments import prepare_image
from src.qt_chat import QT_AVAILABLE, QtChatWidget

if QT_AVAILABLE:
    from PySide6 import QtGui, QtWidgets


def _png_bytes(color, size=(16, 16)):
    from PIL import Image
    import io
    image = Image.new("RGB", size, color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _client():
    client = Mock()
    client.chat.return_value = "unused"
    return client


def _config():
    config = Mock()
    config.get.side_effect = lambda key, default=None: default
    config.get_api_key = Mock(return_value=None)
    return config


@unittest.skipUnless(QT_AVAILABLE, "PySide6 required for attachment tests")
class TestQtAttachmentBytes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        self.image = self.dir / "picture.png"
        self.image.write_bytes(_png_bytes("red"))
        self.chat = QtChatWidget(_config(), Mock(distro=None, system_context=None),
                                 ai_client=_client())
        self.addCleanup(self.chat.close)

    def _attach(self):
        with patch("src.qt_chat.should_use_provider", return_value=True):
            self.chat._add_attachment(str(self.image))
        self.assertEqual(len(self.chat._attachments), 1)

    def _sent_payload(self):
        captured = {}

        def spy_chat(messages, images=None, cancel_event=None, **kwargs):
            captured["images"] = images
            return "answer"
        client = Mock()
        client.chat.side_effect = spy_chat
        self.chat.ai_client = client
        with patch("src.qt_chat.should_use_provider", return_value=True):
            self.chat.input.setText("describe this")
            self.chat._on_send()
        self.chat._cancel_event.set()
        thread = self.chat._worker_thread
        if thread is not None:
            thread.join(timeout=5)
        self.app.processEvents()
        return captured.get("images")

    def test_replaced_file_diverges_preview_from_payload(self):
        """Reproduction: attach red, replace the file with blue, send.

        The preview rendered the red bytes; the payload the provider
        receives must be the same red snapshot, not the blue file that
        replaced the path after the attach.
        """
        self._attach()
        previewed = self.chat._attachments[0].get("attachment")
        self.assertIsNotNone(previewed)
        # Replace the file at the same path with different pixels.
        self.image.write_bytes(_png_bytes("blue"))
        images = self._sent_payload()
        self.assertIsNotNone(images)
        self.assertEqual(len(images), 1)
        sent = images[0].data
        self.assertEqual(sent, previewed.data)
        self.assertNotEqual(sent, prepare_image(str(self.image)).data)

    def test_deleted_file_keeps_the_frozen_payload(self):
        self._attach()
        previewed = self.chat._attachments[0]["attachment"]
        self.image.unlink()
        images = self._sent_payload()
        self.assertIsNotNone(images)
        self.assertEqual(images[0].data, previewed.data)

    def test_attach_failure_refuses_link_before_reading(self):
        """A link is refused at attach time, before any file read."""
        target = self.dir / "target.png"
        target.write_bytes(_png_bytes("green"))
        link = self.dir / "link.png"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable on this host")
        with patch("src.qt_chat.should_use_provider", return_value=True):
            self.chat._add_attachment(str(link))
        self.assertEqual(self.chat._attachments, [])
        self.assertIn("link", self.chat.log.toPlainText().lower())

    def test_attach_failure_of_regular_file_is_visible(self):
        self.image.write_bytes(b"not an image at all")
        with patch("src.qt_chat.should_use_provider", return_value=True):
            self.chat._add_attachment(str(self.image))
        self.assertEqual(self.chat._attachments, [])
        self.assertNotEqual(self.chat.log.toPlainText(), "")

    def test_preview_renders_from_attachment_data(self):
        self._attach()
        entry = self.chat._attachments[0]
        preview = entry["widget"]
        labels = preview.findChildren(QtWidgets.QLabel)
        pixmaps = [label.pixmap() for label in labels]
        self.assertTrue(any(pixmap is not None and not pixmap.isNull()
                            for pixmap in pixmaps))
        pixmap = next(p for p in pixmaps if p is not None and not p.isNull())
        rendered = QtGui.QImage.fromData(entry["attachment"].data)
        self.assertFalse(rendered.isNull())
        # The scaled preview keeps the attachment's square aspect ratio.
        self.assertEqual(pixmap.width(), pixmap.height())


if __name__ == "__main__":
    unittest.main()
