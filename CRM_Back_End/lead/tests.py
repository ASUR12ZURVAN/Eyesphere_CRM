from datetime import timedelta
from io import BytesIO
import tempfile

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .forms import LeadForm
from .models import Booking, CallActivity, Lead, LeadDocument, normalize_mobile
from .services import daily_queue


class LeadRulesTests(TestCase):
	def setUp(self):
		cache.clear()
		user = get_user_model().objects.create_user(username='owner', password='test-password-123')
		self.client.force_login(user)
		self.lead = Lead.objects.create(name='Asha Mehta', mobile='98765 43210', source=Lead.Source.REFERRAL)

	def test_mobile_normalization_and_duplicate_warning(self):
		self.assertEqual(normalize_mobile('09876543210'), '+919876543210')
		form = LeadForm(data={
			'name': 'Another patient',
			'mobile': '+91 98765 43210',
			'source': Lead.Source.GOOGLE,
			'temperature': Lead.Temperature.WARM,
			'status': Lead.Status.NEW,
			'amount_executed': '0',
		})
		self.assertFalse(form.is_valid())
		self.assertIn('Asha Mehta', str(form.errors['mobile']))

	def test_four_no_contact_attempts_close_lead(self):
		for attempt in range(1, 5):
			response = self.client.post(reverse('log_call', args=(self.lead.lead_id,)), {
				'outcome': Lead.Outcome.NOT_PICKED_UP,
				'remark': f'No answer {attempt}',
			})
			self.assertEqual(response.status_code, 302)
			self.lead.refresh_from_db()
			self.assertEqual(self.lead.np_attempt, attempt)
			if attempt < 4:
				self.assertEqual(self.lead.status, Lead.Status.NOT_PICKED_UP)
				self.assertIsNotNone(self.lead.next_follow_up)
			else:
				self.assertEqual(self.lead.status, Lead.Status.WASTE)
				self.assertIsNone(self.lead.next_follow_up)
		self.assertEqual(CallActivity.objects.filter(lead=self.lead).count(), 4)
		self.assertNotIn(self.lead, daily_queue())

	def test_real_conversation_resets_np_sequence_and_preserves_history(self):
		self.client.post(reverse('log_call', args=(self.lead.lead_id,)), {'outcome': Lead.Outcome.NOT_PICKED_UP})
		self.lead.refresh_from_db()
		self.assertEqual(self.lead.np_attempt, 1)
		self.client.post(reverse('log_call', args=(self.lead.lead_id,)), {
			'outcome': Lead.Outcome.CONNECTED,
			'remark': 'Asked about an OPD appointment',
		})
		self.lead.refresh_from_db()
		self.assertEqual(self.lead.np_attempt, 0)
		self.assertTrue(self.lead.conversation_happened)
		self.assertEqual(self.lead.calls.count(), 2)
		self.assertEqual(self.lead.latest_remark, 'Asked about an OPD appointment')

	def test_future_leads_are_hidden_until_follow_up_is_due(self):
		self.lead.temperature = Lead.Temperature.FUTURE
		self.lead.status = Lead.Status.FOLLOW_UP
		self.lead.next_follow_up = timezone.now() + timedelta(days=20)
		self.lead.save()
		self.assertNotIn(self.lead, daily_queue())

	def test_dashboard_login_and_master_lead_render(self):
		response = self.client.get(reverse('dashboard'))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Today\'s calling list')
		response = self.client.get(reverse('lead_list'))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, self.lead.lead_id)
		self.assertEqual(self.client.get(reverse('lead_detail', args=(self.lead.lead_id,))).status_code, 200)

	def test_private_views_redirect_to_login(self):
		self.client.logout()
		response = self.client.get(reverse('lead_list'))
		self.assertEqual(response.status_code, 302)
		self.assertIn(reverse('login'), response.url)

	def test_reactivation_requires_reason_and_schedules_new_action(self):
		self.lead.status = Lead.Status.WASTE
		self.lead.save()
		due_at = timezone.localtime(timezone.now() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M')
		response = self.client.post(reverse('reactivate_lead', args=(self.lead.lead_id,)), {
			'reason': 'Patient asked to revisit after family discussion',
			'next_follow_up': due_at,
		})
		self.assertEqual(response.status_code, 302)
		self.lead.refresh_from_db()
		self.assertEqual(self.lead.status, Lead.Status.FOLLOW_UP)
		self.assertEqual(self.lead.follow_ups.count(), 1)
		self.assertEqual(self.lead.latest_remark, 'Patient asked to revisit after family discussion')

	def test_booking_updates_converted_lead_and_revenue_dashboard(self):
		appointment = timezone.localtime(timezone.now() + timedelta(days=2)).strftime('%Y-%m-%dT%H:%M')
		response = self.client.post(reverse('create_booking', args=(self.lead.lead_id,)), {
			'appointment_at': appointment,
			'service_type': Lead.CareType.OPD,
			'amount_booked': '12500.00',
			'amount_executed': '12500.00',
			'status': 'COMPLETED',
			'execution_date': timezone.localdate().isoformat(),
			'insurance': '',
			'insurance_status': 'NOT_APPLICABLE',
			'cancellation_reason': '',
		})
		self.assertEqual(response.status_code, 302)
		self.lead.refresh_from_db()
		self.assertEqual(self.lead.status, Lead.Status.CONVERTED)
		self.assertEqual(self.lead.amount_executed, 12500)
		self.assertContains(self.client.get(reverse('dashboard')), '₹12500')

	def test_csv_import_preview_and_duplicate_skipping(self):
		csv_data = b'Name,Mobile,Source,Campaign\nNew Patient,9876543211,Google,Spring\nAsha Duplicate,919876543210,Referral,Repeat\n'
		upload = SimpleUploadedFile('leads.csv', csv_data, content_type='text/csv')
		response = self.client.post(reverse('lead_import'), {'file': upload})
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, '1')
		response = self.client.post(reverse('confirm_import'))
		self.assertEqual(response.status_code, 302)
		self.assertEqual(Lead.objects.count(), 2)

	def test_csv_import_page_shows_format_guidelines(self):
		response = self.client.get(reverse('lead_import'))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'CSV Format Guidelines')
		self.assertContains(response, 'Patient Name')
		self.assertContains(response, 'External Source ID')
		self.assertContains(response, '8–15 digits')
		self.assertContains(response, 'REFERRAL / Referral')

	def test_snoozing_moves_current_reminder_without_erasing_its_due_time(self):
		original_due = timezone.now() + timedelta(hours=1)
		self.lead.next_follow_up = original_due
		self.lead.status = Lead.Status.FOLLOW_UP
		self.lead.save()
		from .models import FollowUp
		task = FollowUp.objects.create(lead=self.lead, due_at=original_due)
		snoozed_until = timezone.localtime(timezone.now() + timedelta(days=3)).strftime('%Y-%m-%dT%H:%M')
		response = self.client.post(reverse('snooze_follow_up', args=(self.lead.lead_id,)), {'due_at': snoozed_until})
		self.assertEqual(response.status_code, 302)
		task.refresh_from_db()
		self.lead.refresh_from_db()
		self.assertEqual(task.due_at, original_due)
		self.assertIsNotNone(task.snoozed_until)
		self.assertEqual(self.lead.next_follow_up, task.snoozed_until)

	def test_bulk_update_applies_selected_values_and_audits(self):
		due_at = timezone.localtime(timezone.now() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M')
		response = self.client.post(reverse('bulk_update_leads'), {
			'lead_ids': [self.lead.pk],
			'temperature': Lead.Temperature.HOT,
			'status': Lead.Status.FOLLOW_UP,
			'source': Lead.Source.GOOGLE,
			'next_follow_up': due_at,
		})
		self.assertEqual(response.status_code, 302)
		self.lead.refresh_from_db()
		self.assertEqual(self.lead.temperature, Lead.Temperature.HOT)
		self.assertEqual(self.lead.status, Lead.Status.FOLLOW_UP)
		self.assertEqual(self.lead.source, Lead.Source.GOOGLE)
		self.assertTrue(self.lead.audit_entries.filter(action='bulk_updated').exists())

	def test_all_report_exports_return_csv(self):
		for report in ('leads', 'calls', 'bookings', 'daily', 'revenue', 'source', 'lost'):
			with self.subTest(report=report):
				response = self.client.get(reverse('export_csv'), {'report': report})
				self.assertEqual(response.status_code, 200)
				self.assertTrue(response['Content-Type'].startswith('text/csv'))

	def test_average_order_value_counts_each_executed_booking(self):
		for amount in ('10000.00', '20000.00'):
			Booking.objects.create(
				lead=self.lead,
				appointment_at=timezone.now(),
				service_type=Lead.CareType.OPD,
				amount_executed=amount,
				status=Booking.Status.COMPLETED,
				execution_date=timezone.localdate(),
			)
		response = self.client.get(reverse('dashboard'))
		self.assertEqual(response.context['executed_revenue'], 30000)
		self.assertEqual(response.context['average_order_value'], 15000)

	def test_csv_export_escapes_formula_like_patient_names(self):
		self.lead.name = '=1+1'
		self.lead.save()
		response = self.client.get(reverse('export_csv'))
		self.assertIn("'=1+1", response.content.decode('utf-8-sig'))


class LeadDocumentUploadTests(TestCase):
	def setUp(self):
		cache.clear()
		self.media_dir = tempfile.TemporaryDirectory()
		self.settings_override = override_settings(MEDIA_ROOT=self.media_dir.name)
		self.settings_override.enable()
		self.addCleanup(self.settings_override.disable)
		self.addCleanup(self.media_dir.cleanup)
		user = get_user_model().objects.create_user(username='owner', password='test-password-123')
		self.client.force_login(user)
		self.lead = Lead.objects.create(name='Asha Mehta', mobile='98765 43210', source=Lead.Source.REFERRAL)

	def test_upload_and_authenticated_download(self):
		upload = SimpleUploadedFile(
			'eye-report.pdf',
			b'%PDF-1.7\npatient report',
			content_type='application/pdf',
		)
		response = self.client.post(
			reverse('upload_lead_document', args=(self.lead.lead_id,)),
			{'title': 'Eye examination', 'description': 'Initial visit', 'file': upload},
		)
		self.assertRedirects(response, reverse('lead_detail', args=(self.lead.lead_id,)))
		document = LeadDocument.objects.get(lead=self.lead)
		self.assertEqual(document.original_filename, 'eye-report.pdf')
		self.assertEqual(document.uploaded_by.username, 'owner')
		self.assertTrue(document.file.storage.exists(document.file.name))
		self.assertIn(self.lead.lead_id, document.file.name)
		self.assertNotIn(document.original_filename, document.file.name)
		detail_response = self.client.get(reverse('lead_detail', args=(self.lead.lead_id,)))
		self.assertContains(detail_response, 'Documents')
		self.assertContains(detail_response, 'Eye examination')
		self.assertContains(detail_response, 'Download')

		response = self.client.get(reverse(
			'download_lead_document',
			args=(self.lead.lead_id, document.pk),
		))
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response['Content-Type'], 'application/pdf')
		self.assertIn('attachment;', response['Content-Disposition'])
		self.assertIn('eye-report.pdf', response['Content-Disposition'])
		self.assertEqual(b''.join(response.streaming_content), b'%PDF-1.7\npatient report')

	def test_rejects_unsupported_and_mismatched_files(self):
		for filename, contents, error in (
			('report.exe', b'%PDF-1.7\nnot an executable', 'Upload a PDF, JPEG, or PNG file.'),
			('report.pdf', b'not a PDF', 'file contents do not match its file type.'),
		):
			with self.subTest(filename=filename):
				response = self.client.post(
					reverse('upload_lead_document', args=(self.lead.lead_id,)),
					{
						'title': 'Invalid document',
						'file': SimpleUploadedFile(filename, contents),
					},
				)
				self.assertEqual(response.status_code, 200)
				self.assertContains(response, error, status_code=200)
		self.assertFalse(LeadDocument.objects.exists())

	def test_rejects_files_over_10_mb(self):
		upload = SimpleUploadedFile(
			'large.pdf',
			b'%PDF-' + b'x' * (10 * 1024 * 1024),
		)
		response = self.client.post(
			reverse('upload_lead_document', args=(self.lead.lead_id,)),
			{'title': 'Large report', 'file': upload},
		)
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Documents must be 10 MB or smaller.', status_code=200)
		self.assertFalse(LeadDocument.objects.exists())

	def test_download_requires_login_and_document_belonging_to_lead(self):
		document = LeadDocument.objects.create(
			lead=self.lead,
			title='Eye examination',
			original_filename='report.pdf',
			file=SimpleUploadedFile('report.pdf', b'%PDF-1.7\nreport'),
		)
		self.client.logout()
		response = self.client.get(reverse(
			'download_lead_document',
			args=(self.lead.lead_id, document.pk),
		))
		self.assertRedirects(
			response,
			f'{reverse("login")}?next={reverse("download_lead_document", args=(self.lead.lead_id, document.pk))}',
		)
		self.client.force_login(get_user_model().objects.get(username='owner'))
		other_lead = Lead.objects.create(name='Ravi Kumar', mobile='9876543211', source=Lead.Source.REFERRAL)
		response = self.client.get(reverse(
			'download_lead_document',
			args=(other_lead.lead_id, document.pk),
		))
		self.assertEqual(response.status_code, 404)
