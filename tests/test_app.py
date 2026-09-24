import io
import base64
import os
import tempfile
import unittest
from unittest.mock import patch

from pypdf import PdfReader
from PIL import Image

import app as note_printer


class NotePrinterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        patcher = patch.dict(os.environ, {"NOTE_PRINTER_DATA_DIR": temporary.name})
        patcher.start()
        self.addCleanup(patcher.stop)
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

    def test_each_template_changes_the_printed_label(self):
        cases = [
            ('shopping', 'Boodschappen', 'BOODSCHAPPEN'),
            ('tasks', 'Taken', 'TAKEN'),
            ('reminder', 'Niet vergeten', 'HERINNERING'),
            ('message', 'Berichtje', 'BERICHT'),
        ]
        for template, title, heading in cases:
            with self.subTest(template=template):
                payload = {'template': template, 'title': title, 'body': 'Eerste regel\nTweede regel', 'checklist': True}
                layout = self.client.post('/api/layout', json=payload)
                self.assertEqual(layout.status_code, 200)
                self.assertEqual(layout.json['template'], template)
                self.assertTrue(layout.json['first_page'][0]['checkbox'])
                pdf = self.client.post('/api/preview', json=payload)
                self.assertEqual(pdf.status_code, 200)
                text = PdfReader(io.BytesIO(pdf.data)).pages[0].extract_text()
                self.assertIn(heading, text)
                self.assertIn('Eerste regel', text)
                if template == 'tasks':
                    self.assertIn('1.', text)
                    self.assertIn('2.', text)

    def test_unrecognised_template_is_rejected(self):
        response = self.client.post('/api/preview', json={'template': 'other', 'body': 'Test'})
        self.assertEqual(response.status_code, 400)

    def test_saved_template_note_and_history_can_be_reused(self):
        payload = {'title': 'Belangrijk', 'body': 'Vergeet je afspraak niet', 'template': 'appointment',
                   'heading': 'MORGEN', 'font_size': 12, 'event_at': '2026-09-25T14:00', 'icon': 'warning'}
        saved_template = self.client.post('/api/templates', json={'name': 'Mijn afspraak', 'note': payload})
        self.assertEqual(saved_template.status_code, 200)
        template_id = saved_template.json['id']
        restored = self.client.get(f'/api/templates/{template_id}').json['item']['payload']
        self.assertEqual(restored['heading'], 'MORGEN')
        self.assertEqual(restored['event_at'], '25-09-2026 14:00')
        saved_note = self.client.post('/api/notes', json=payload)
        self.assertEqual(saved_note.status_code, 200)
        self.assertEqual(self.client.get(f"/api/notes/{saved_note.json['id']}").json['item']['payload']['body'], payload['body'])
        with patch.object(note_printer, 'configure_printer'), patch.object(note_printer, 'command') as command:
            command.return_value.returncode = 0
            command.return_value.stdout = 'request id is NotePrinter-123'
            self.assertEqual(self.client.post('/api/print', json=payload).status_code, 200)
            history = self.client.get('/api/history').json['items']
            self.assertEqual(history[0]['status'], 'sent')
            self.assertEqual(self.client.post(f"/api/history/{history[0]['id']}/reprint").status_code, 200)
            self.assertEqual(command.call_count, 2)

    def test_photo_and_extra_fields_fit_on_label(self):
        image = Image.new('RGB', (80, 70), color='navy')
        output = io.BytesIO()
        image.save(output, format='JPEG')
        photo = 'data:image/jpeg;base64,' + base64.b64encode(output.getvalue()).decode()
        response = self.client.post('/api/preview', json={
            'template': 'message', 'title': 'Berichtje', 'body': 'Ik ben later thuis.',
            'recipient': 'Simon', 'sender': 'Kevin', 'photo': photo,
        })
        self.assertEqual(response.status_code, 200, response.json if response.is_json else None)
        page = PdfReader(io.BytesIO(response.data)).pages[0]
        text = page.extract_text()
        self.assertIn('AAN: Simon', text)
        self.assertIn('VAN: Kevin', text)
        self.assertEqual(float(page.mediabox.width), 154)

    def test_own_heading_is_printed_on_free_layout(self):
        payload = {'heading': 'MIJN LABEL', 'title': 'Eigen sjabloon', 'body': 'Een eigen indeling'}
        layout = self.client.post('/api/layout', json=payload)
        self.assertEqual(layout.json['style'], 'free')
        pdf = self.client.post('/api/preview', json=payload)
        self.assertIn('MIJN LABEL', PdfReader(io.BytesIO(pdf.data)).pages[0].extract_text())

    def test_frontend_assets_are_served(self):
        page = self.client.get('/')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'/static/app.js', page.data)
        self.assertIn(b'/static/style.css', page.data)
        for path in ('/static/app.js', '/static/style.css'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            response.close()

    def test_cancel_only_accepts_own_queue_job(self):
        with patch.object(note_printer, 'command') as command:
            result = self.client.post('/api/printer/cancel', json={'job': 'OtherPrinter-2; rm -rf /'})
        self.assertEqual(result.status_code, 400)
        command.assert_not_called()


if __name__ == '__main__':
    unittest.main()
