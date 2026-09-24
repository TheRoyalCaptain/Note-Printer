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

    def test_multilabel_checklist_with_qr_and_numbering(self):
        payload = {
            'title': 'Taken', 'body': 'Een taak met een lange omschrijving\n' * 35,
            'checklist': True, 'paginate': True, 'qr': 'https://example.org/taken',
            'copies': 2, 'date': True,
        }
        layout = self.client.post('/api/layout', json=payload)
        self.assertEqual(layout.status_code, 200)
        self.assertGreater(layout.json['pages'], 1)
        self.assertTrue(layout.json['first_page'][0]['checkbox'])
        pdf = self.client.post('/api/preview', json=payload)
        pages = PdfReader(io.BytesIO(pdf.data)).pages
        self.assertEqual(len(pages), layout.json['pages'])
        self.assertIn(f"{len(pages)}/{len(pages)}", pages[-1].extract_text())
        self.assertTrue(all(float(p.mediabox.width) == 154 for p in pages))

    def test_qr_on_its_own_last_label_if_title_uses_available_space(self):
        payload = {
            'title': 'Een zeer lange titel die op meerdere regels overloopt',
            'body': 'Een notitie\n' * 16,
            'qr': 'Een langere tekst als QR-code', 'paginate': True,
        }
        layout = self.client.post('/api/layout', json=payload)
        pdf = self.client.post('/api/preview', json=payload)
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(len(PdfReader(io.BytesIO(pdf.data)).pages), layout.json['pages'])

    def test_multiple_copies_are_submitted_in_page_order(self):
        with patch.object(note_printer, 'configure_printer'), patch.object(note_printer, 'command') as command:
            command.return_value.returncode = 0
            command.return_value.stdout = 'request id is NotePrinter-1'
            response = self.client.post('/api/print', json={
                'body': 'Taak\n' * 35, 'paginate': True, 'copies': 2,
            })
        self.assertEqual(response.status_code, 200)
        arguments = command.call_args.args[0]
        self.assertEqual(arguments[arguments.index('-n') + 1], '2')
        self.assertIn('Collate=True', arguments)


if __name__ == '__main__':
    unittest.main()
