import io
import unittest
from unittest.mock import patch

from pypdf import PdfReader

import app as note_printer


class NotePrinterTests(unittest.TestCase):
    def setUp(self):
        self.client = note_printer.app.test_client()

    def test_preview_has_exact_label_size(self):
        response = self.client.post('/api/preview', json={
            'title': 'Boodschappen', 'body': 'Brood\nMelk', 'copies': 1, 'date': True,
        })
        self.assertEqual(response.status_code, 200)
        page = PdfReader(io.BytesIO(response.data)).pages[0]
        self.assertEqual((float(page.mediabox.width), float(page.mediabox.height)), (154, 286))

    def test_overflow_does_not_submit_a_print_job(self):
        with patch.object(note_printer, 'configure_printer') as setup:
            response = self.client.post('/api/print', json={'body': 'x' * 2500})
        self.assertEqual(response.status_code, 400)
        setup.assert_not_called()

    def test_decodes_usb_printer_uri(self):
        with patch.object(note_printer, 'command') as command:
            command.return_value.stdout = 'direct usb://DYMO/LabelWriter%20450?serial=abc\n'
            self.assertEqual(note_printer.find_printer(), ('usb://DYMO/LabelWriter%20450?serial=abc', '450'))


if __name__ == '__main__':
    unittest.main()
