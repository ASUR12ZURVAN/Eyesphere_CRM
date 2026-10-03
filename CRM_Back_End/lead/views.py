import csv
from datetime import date, datetime, time, timedelta

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import BookingForm, BulkLeadForm, CSVUploadForm, CallForm, FollowUpForm, LeadForm, ReactivateForm, SnoozeForm
from .models import AuditLog, Booking, CallActivity, FollowUp, ImportJob, Lead, normalize_mobile
from .services import audit, canonical_row, daily_queue, log_call, parse_csv


def filter_leads(request):
	leads = Lead.objects.all()
	query = request.GET.get('q', '').strip()
	if query:
		leads = leads.filter(Q(name__icontains=query) | Q(mobile__icontains=query) | Q(lead_id__icontains=query))
	for parameter, field in (('status', 'status'), ('temperature', 'temperature'), ('source', 'source'), ('care_type', 'care_type'), ('outcome', 'outcome_reason')):
		value = request.GET.get(parameter)
		if value:
			leads = leads.filter(**{field: value})
	if request.GET.get('location'):
		leads = leads.filter(location__icontains=request.GET['location'].strip())
	if request.GET.get('campaign'):
		leads = leads.filter(campaign__icontains=request.GET['campaign'].strip())
	if request.GET.get('priority') == '1':
		leads = leads.filter(priority=True)
	if request.GET.get('not_called') == '1':
		leads = leads.filter(calls__isnull=True)
	if request.GET.get('due') == '1':
		leads = leads.filter(next_follow_up__lte=timezone.now())
	if request.GET.get('converted') == '1':
		leads = leads.filter(status=Lead.Status.CONVERTED)
	elif request.GET.get('converted') == '0':
		leads = leads.exclude(status=Lead.Status.CONVERTED)
	if request.GET.get('start'):
		leads = leads.filter(created_at__date__gte=request.GET['start'])
	if request.GET.get('end'):
		leads = leads.filter(created_at__date__lte=request.GET['end'])
	return leads.distinct()


def create_account(request):
	if request.user.is_authenticated:
		return redirect('dashboard')
	if request.method == 'POST':
		form = UserCreationForm(request.POST)
		if form.is_valid():
			user = form.save()
			login(request, user)
			messages.success(request, 'Account created successfully.')
			return redirect('dashboard')
	else:
		form = UserCreationForm()
	return render(request, 'lead/create_account.html', {'form': form})


@login_required
def dashboard(request):
	today = timezone.localdate()
	month_start = today.replace(day=1)
	try:
		start_day = date.fromisoformat(request.GET.get('start', month_start.isoformat()))
		end_day = date.fromisoformat(request.GET.get('end', today.isoformat()))
	except ValueError:
		start_day, end_day = month_start, today
	start_at = timezone.make_aware(datetime.combine(start_day, time.min))
	end_at = timezone.make_aware(datetime.combine(end_day + timedelta(days=1), time.min))
	period_leads = Lead.objects.filter(created_at__gte=start_at, created_at__lt=end_at)
	calls = CallActivity.objects.filter(called_at__gte=start_at, called_at__lt=end_at)
	conversions = Lead.objects.filter(converted_at__gte=start_at, converted_at__lt=end_at)
	executed_bookings = Booking.objects.filter(
		execution_date__gte=start_day,
		execution_date__lte=end_day,
		amount_executed__gt=0,
	).exclude(status__in=(Booking.Status.CANCELLED, Booking.Status.RESCHEDULED, Booking.Status.NO_SHOW))
	direct_executions = Lead.objects.filter(
		date_executed__gte=start_day,
		date_executed__lte=end_day,
		amount_executed__gt=0,
	).exclude(bookings__amount_executed__gt=0).distinct()
	executed_revenue = (executed_bookings.aggregate(total=Sum('amount_executed'))['total'] or 0) + (direct_executions.aggregate(total=Sum('amount_executed'))['total'] or 0)
	executed_transactions = executed_bookings.count() + direct_executions.count()
	unique_called = calls.values('lead_id').distinct().count()
	converted_count = conversions.count()
	cohort_conversions = period_leads.filter(status=Lead.Status.CONVERTED).count()
	source_rows = Lead.objects.values('source', 'campaign').annotate(
		leads=Count('id'),
		conversions=Count('id', filter=Q(status=Lead.Status.CONVERTED)),
		revenue=Sum('amount_executed'),
	).order_by('-leads')[:6]
	now = timezone.now()
	upcoming = Booking.objects.filter(appointment_at__gte=now, appointment_at__lte=now + timedelta(days=7)).exclude(status__in=(Booking.Status.CANCELLED, Booking.Status.RESCHEDULED)).select_related('lead')[:5]
	return render(request, 'lead/dashboard.html', {
		'today': today,
		'start_date': start_day,
		'end_date': end_day,
		'total_leads': period_leads.count(),
		'calls_completed': calls.count(),
		'unique_called': unique_called,
		'conversions': converted_count,
		'conversion_rate': round(cohort_conversions / period_leads.count() * 100, 1) if period_leads.exists() else 0,
		'executed_revenue': executed_revenue,
		'average_order_value': executed_revenue / executed_transactions if executed_transactions else 0,
		'pending_calls': daily_queue(limit=500).count(),
		'overdue_count': Lead.objects.filter(next_follow_up__lt=now).exclude(status__in=(Lead.Status.CONVERTED, Lead.Status.REJECTED, Lead.Status.WASTE)).count(),
		'stale_count': Lead.objects.filter(created_at__lt=now - timedelta(days=7)).exclude(status__in=(Lead.Status.CONVERTED, Lead.Status.REJECTED, Lead.Status.WASTE)).count(),
		'active_count': Lead.objects.exclude(status__in=(Lead.Status.CONVERTED, Lead.Status.REJECTED, Lead.Status.WASTE)).count(),
		'source_rows': source_rows,
		'upcoming_bookings': upcoming,
		'temperature_counts': {value: Lead.objects.filter(temperature=value).count() for value, _ in Lead.Temperature.choices},
		'daily_queue': daily_queue(limit=6),
		'now': now,
	})


@login_required
def lead_list(request):
	paginator = Paginator(filter_leads(request).order_by('-priority', '-created_at'), 25)
	return render(request, 'lead/lead_list.html', {
		'page': paginator.get_page(request.GET.get('page')),
		'filters': request.GET,
		'now': timezone.now(),
		'statuses': Lead.Status.choices,
		'temperatures': Lead.Temperature.choices,
		'sources': Lead.Source.choices,
		'care_types': Lead.CareType.choices,
		'outcomes': Lead.Outcome.choices,
		'bulk_form': BulkLeadForm(),
	})


@login_required
def lead_form(request, lead_id=None):
	lead = get_object_or_404(Lead, lead_id=lead_id) if lead_id else None
	before = {field.name: getattr(lead, field.name) for field in Lead._meta.fields} if lead else {}
	form = LeadForm(request.POST or None, instance=lead)
	if request.method == 'POST' and form.is_valid():
		saved = form.save()
		if lead:
			changes = {key: {'from': str(before[key]), 'to': str(getattr(saved, key))} for key in before if before[key] != getattr(saved, key)}
			if changes:
				audit(saved, 'lead_updated', changes)
			messages.success(request, 'Lead details updated.')
		else:
			audit(saved, 'lead_created', {'source': saved.source})
			messages.success(request, f'{saved.name} was added to the lead inventory.')
		return redirect('lead_detail', lead_id=saved.lead_id)
	return render(request, 'lead/lead_form.html', {'form': form, 'lead': lead})


@login_required
def lead_detail(request, lead_id):
	lead = get_object_or_404(Lead.objects.prefetch_related('calls', 'follow_ups', 'bookings', 'audit_entries'), lead_id=lead_id)
	timeline = []
	timeline.extend({'kind': 'call', 'at': call.called_at, 'title': call.get_outcome_display(), 'body': call.remark, 'meta': f'Call {call.attempt_number}'} for call in lead.calls.all())
	timeline.extend({'kind': 'follow-up', 'at': task.created_at, 'title': f'{task.get_kind_display()} scheduled', 'body': task.note, 'meta': f'Due {timezone.localtime(task.due_at):%d %b, %I:%M %p}'} for task in lead.follow_ups.all())
	timeline.extend({'kind': 'booking', 'at': booking.created_at, 'title': f'{booking.get_status_display()} · {booking.get_service_type_display()}', 'body': f'{booking.hospital} {booking.doctor}'.strip(), 'meta': timezone.localtime(booking.appointment_at).strftime('%d %b %Y, %I:%M %p')} for booking in lead.bookings.all())
	timeline.extend({'kind': 'activity', 'at': entry.created_at, 'title': entry.action.replace('_', ' ').title(), 'body': ', '.join(f'{key}: {value}' for key, value in entry.details.items()), 'meta': ''} for entry in lead.audit_entries.all())
	timeline.append({'kind': 'created', 'at': lead.created_at, 'title': 'Lead created', 'body': f'Added from {lead.get_source_display()}', 'meta': lead.lead_id})
	timeline.sort(key=lambda item: item['at'], reverse=True)
	return render(request, 'lead/lead_detail.html', {
		'lead': lead,
		'timeline': timeline,
		'call_form': CallForm(),
		'follow_up_form': FollowUpForm(initial={'due_at': lead.next_follow_up}),
		'reactivate_form': ReactivateForm(),
		'snooze_form': SnoozeForm(initial={'due_at': lead.next_follow_up}),
		'booking_form': BookingForm(initial={'service_type': lead.care_type or Lead.CareType.OPD}),
		'bookings': lead.bookings.all(),
		'follow_ups': lead.follow_ups.all(),
	})


@login_required
@require_POST
def log_lead_call(request, lead_id):
	lead = get_object_or_404(Lead, lead_id=lead_id)
	form = CallForm(request.POST)
	if form.is_valid():
		activity = log_call(lead, form.cleaned_data)
		messages.success(request, f'{activity.get_outcome_display()} saved for {lead.name}.')
	else:
		messages.error(request, 'Call was not saved. Check the outcome details and try again.')
	return redirect('lead_detail', lead_id=lead.lead_id)


@login_required
@require_POST
def schedule_follow_up(request, lead_id):
	lead = get_object_or_404(Lead, lead_id=lead_id)
	form = FollowUpForm(request.POST)
	if form.is_valid():
		lead.follow_ups.filter(completed_at__isnull=True).update(completed_at=timezone.now())
		task = form.save(commit=False)
		task.lead = lead
		task.save()
		lead.next_follow_up = task.due_at
		if lead.status not in (Lead.Status.CONVERTED, Lead.Status.REJECTED, Lead.Status.WASTE):
			lead.status = Lead.Status.FOLLOW_UP
		lead.save()
		audit(lead, 'follow_up_scheduled', {'due_at': task.due_at.isoformat(), 'kind': task.kind})
		messages.success(request, 'Follow-up added to the daily queue.')
	else:
		messages.error(request, 'Choose a valid follow-up date and time.')
	return redirect('lead_detail', lead_id=lead.lead_id)


@login_required
@require_POST
def reactivate_lead(request, lead_id):
	lead = get_object_or_404(Lead, lead_id=lead_id)
	form = ReactivateForm(request.POST)
	if lead.status not in (Lead.Status.WASTE, Lead.Status.REJECTED):
		messages.error(request, 'Only waste or rejected leads can be reactivated.')
	elif form.is_valid():
		lead.status = Lead.Status.FOLLOW_UP
		lead.next_follow_up = form.cleaned_data['next_follow_up']
		lead.latest_remark = form.cleaned_data['reason']
		lead.save()
		lead.follow_ups.filter(completed_at__isnull=True).update(completed_at=timezone.now())
		FollowUp.objects.create(lead=lead, due_at=lead.next_follow_up, kind=FollowUp.Kind.CALL, note=form.cleaned_data['reason'])
		audit(lead, 'lead_reactivated', {'reason': form.cleaned_data['reason'], 'due_at': lead.next_follow_up.isoformat()})
		messages.success(request, 'Lead reactivated and added to the follow-up queue.')
	else:
		messages.error(request, 'Add a reason and choose the next follow-up date.')
	return redirect('lead_detail', lead_id=lead.lead_id)


@login_required
@require_POST
def snooze_follow_up(request, lead_id):
	lead = get_object_or_404(Lead, lead_id=lead_id)
	form = SnoozeForm(request.POST)
	if form.is_valid():
		due_at = form.cleaned_data['due_at']
		active_tasks = lead.follow_ups.filter(completed_at__isnull=True)
		if active_tasks.exists():
			active_tasks.update(snoozed_until=due_at)
		else:
			FollowUp.objects.create(lead=lead, due_at=due_at, snoozed_until=due_at, note='Reminder snoozed')
		lead.next_follow_up = due_at
		lead.save()
		audit(lead, 'follow_up_snoozed', {'snoozed_until': due_at.isoformat()})
		messages.success(request, 'Reminder snoozed. Its original due time remains in the activity history.')
	else:
		messages.error(request, 'Choose a valid snooze date and time.')
	return redirect('lead_detail', lead_id=lead.lead_id)


@login_required
@require_POST
def create_booking(request, lead_id):
	lead = get_object_or_404(Lead, lead_id=lead_id)
	form = BookingForm(request.POST)
	if form.is_valid():
		booking = form.save(commit=False)
		booking.lead = lead
		booking.save()
		lead.follow_ups.filter(completed_at__isnull=True).update(completed_at=timezone.now())
		lead.care_type = booking.service_type
		lead.status = Lead.Status.CONVERTED
		lead.converted_at = lead.converted_at or timezone.now()
		lead.conversion_reason = lead.conversion_reason or 'Booking created'
		lead.next_follow_up = None
		if booking.amount_executed:
			lead.amount_executed = booking.amount_executed
			lead.date_executed = booking.execution_date
		lead.save()
		audit(lead, 'booking_created', {'booking_id': booking.pk, 'status': booking.status})
		messages.success(request, 'Booking saved to the patient profile.')
	else:
		messages.error(request, 'Booking was not saved. Check the required fields.')
	return redirect('lead_detail', lead_id=lead.lead_id)


@login_required
def daily_calling(request):
	return render(request, 'lead/daily_calling.html', {
		'leads': daily_queue(),
		'due_count': Lead.objects.filter(next_follow_up__lte=timezone.now()).exclude(status__in=(Lead.Status.CONVERTED, Lead.Status.REJECTED, Lead.Status.WASTE)).count(),
		'target': 65,
	})


@login_required
@require_POST
def bulk_update_leads(request):
	form = BulkLeadForm(request.POST)
	selected_ids = request.POST.getlist('lead_ids')
	if not selected_ids:
		messages.error(request, 'Select at least one lead first.')
		return redirect('lead_list')
	if not form.is_valid():
		messages.error(request, 'Choose valid bulk changes and try again.')
		return redirect('lead_list')
	changed = 0
	skipped = 0
	for lead in Lead.objects.filter(pk__in=selected_ids):
		data = form.cleaned_data
		if data.get('status') and not lead.can_transition_to(data['status']):
			skipped += 1
			continue
		details = {}
		for field in ('temperature', 'source'):
			if data.get(field) and getattr(lead, field) != data[field]:
				details[field] = {'from': getattr(lead, field), 'to': data[field]}
				setattr(lead, field, data[field])
		if data.get('status'):
			details['status'] = {'from': lead.status, 'to': data['status']}
			lead.status = data['status']
		if data.get('next_follow_up'):
			if lead.status in (Lead.Status.CONVERTED, Lead.Status.REJECTED, Lead.Status.WASTE) and not data.get('status'):
				skipped += 1
				continue
			details['next_follow_up'] = {'from': str(lead.next_follow_up), 'to': data['next_follow_up'].isoformat()}
			lead.next_follow_up = data['next_follow_up']
			if lead.status not in (Lead.Status.CONVERTED, Lead.Status.REJECTED, Lead.Status.WASTE):
				lead.status = Lead.Status.FOLLOW_UP
		if details:
			lead.save()
			audit(lead, 'bulk_updated', details)
			changed += 1
	messages.success(request, f'{changed} lead{"s" if changed != 1 else ""} updated; {skipped} skipped due to status rules.')
	return redirect('lead_list')


@login_required
def booking_list(request):
	month_value = request.GET.get('month', timezone.localdate().strftime('%Y-%m'))
	try:
		month = date.fromisoformat(f'{month_value}-01')
	except ValueError:
		month = timezone.localdate().replace(day=1)
		month_value = month.strftime('%Y-%m')
	next_month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
	bookings = Booking.objects.filter(appointment_at__date__gte=month, appointment_at__date__lt=next_month).select_related('lead')
	if request.GET.get('status'):
		bookings = bookings.filter(status=request.GET['status'])
	return render(request, 'lead/booking_list.html', {'bookings': bookings, 'month': month_value, 'statuses': Booking.Status.choices})


@login_required
def import_leads(request):
	form = CSVUploadForm(request.POST or None, request.FILES or None)
	if request.method == 'POST' and form.is_valid():
		uploaded = form.cleaned_data['file']
		preview = []
		seen_mobiles = set()
		seen_source_ids = set()
		for index, raw in enumerate(parse_csv(uploaded), start=2):
			row = canonical_row(raw)
			errors = []
			if not row['name']:
				errors.append('Name is required')
			if not row['mobile']:
				errors.append('Mobile is required')
			if not row['source']:
				errors.append('Source is required')
			existing = None
			try:
				normalized = normalize_mobile(row['mobile']) if row['mobile'] else ''
				existing = Lead.objects.filter(mobile=normalized).first()
			except ValidationError:
				errors.append('Invalid mobile number')
			if normalized and normalized in seen_mobiles:
				errors.append('Duplicate mobile in this file')
			if normalized:
				seen_mobiles.add(normalized)
			if row['external_source_id'] and row['external_source_id'] in seen_source_ids:
				errors.append('Duplicate external source ID in this file')
			if row['external_source_id']:
				seen_source_ids.add(row['external_source_id'])
			source_value = row['source'].strip().upper().replace(' ', '_')
			valid_sources = {value for value, _ in Lead.Source.choices}
			matching_source = source_value if source_value in valid_sources else None
			if not matching_source:
				source_labels = {label.lower(): value for value, label in Lead.Source.choices}
				matching_source = source_labels.get(row['source'].strip().lower())
			if row['source'] and not matching_source:
				errors.append('Unknown source')
			preview.append({**row, 'line': index, 'errors': errors, 'duplicate': existing.lead_id if existing else '', 'source_value': matching_source or ''})
		request.session['lead_import'] = {'file_name': uploaded.name, 'rows': preview}
		return render(request, 'lead/import_preview.html', {
			'rows': preview,
			'file_name': uploaded.name,
			'ready_count': sum(not row['errors'] and not row['duplicate'] for row in preview),
			'duplicate_count': sum(bool(row['duplicate']) or any('Duplicate' in error for error in row['errors']) for row in preview),
			'invalid_count': sum(bool(row['errors']) and not any('Duplicate' in error for error in row['errors']) for row in preview),
		})
	return render(request, 'lead/import.html', {'form': form, 'recent_jobs': ImportJob.objects.all()[:5]})


@login_required
@require_POST
def confirm_import(request):
	batch = request.session.pop('lead_import', None)
	if not batch:
		messages.error(request, 'That import preview expired. Upload the CSV again.')
		return redirect('lead_import')
	imported = skipped = failed = 0
	errors = []
	for row in batch['rows']:
		if row['errors']:
			failed += 1
			errors.append({'line': row['line'], 'reason': '; '.join(row['errors'])})
			continue
		if row['duplicate'] or (row['external_source_id'] and Lead.objects.filter(external_source_id=row['external_source_id']).exists()):
			skipped += 1
			continue
		try:
			lead = Lead.objects.create(
				name=row['name'], mobile=row['mobile'], source=row['source_value'],
				campaign=row['campaign'], location=row['location'], email=row['email'],
				external_source_id=row['external_source_id'], created_from='CSV Import',
			)
			audit(lead, 'lead_imported', {'file': batch['file_name'], 'line': row['line']})
			imported += 1
		except Exception as error:
			failed += 1
			errors.append({'line': row['line'], 'reason': str(error)})
	ImportJob.objects.create(file_name=batch['file_name'], rows_read=len(batch['rows']), rows_imported=imported, rows_skipped=skipped, rows_failed=failed, errors=errors)
	messages.success(request, f'Import complete: {imported} added, {skipped} duplicates skipped, {failed} failed.')
	return redirect('lead_import')


@login_required
def export_csv(request):
	report = request.GET.get('report', 'leads')
	if report not in {'leads', 'calls', 'bookings', 'daily', 'revenue', 'source', 'lost'}:
		report = 'leads'
	response = HttpResponse(content_type='text/csv; charset=utf-8')
	response['Content-Disposition'] = f'attachment; filename="eyesphere-{report}-{timezone.localdate()}.csv"'
	response.write('\ufeff')
	writer = csv.writer(response)
	def write_row(values):
		safe_values = [f"'{value}" if isinstance(value, str) and value.startswith(('=', '+', '-', '@', '\t', '\r')) else value for value in values]
		writer.writerow(safe_values)

	if report == 'calls':
		write_row(('Lead ID', 'Name', 'Mobile', 'Call time', 'Attempt', 'Outcome', 'Remark', 'Next action'))
		for call in CallActivity.objects.select_related('lead'):
			write_row((call.lead.lead_id, call.lead.name, call.lead.mobile, call.called_at, call.attempt_number, call.get_outcome_display(), call.remark, call.next_action or ''))
	elif report == 'bookings':
		if request.GET.get('month'):
			try:
				month = date.fromisoformat(f"{request.GET['month']}-01")
				next_month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
				booking_rows = Booking.objects.filter(appointment_at__date__gte=month, appointment_at__date__lt=next_month)
			except ValueError:
				booking_rows = Booking.objects.all()
		else:
			booking_rows = Booking.objects.all()
		write_row(('Lead ID', 'Name', 'Appointment', 'Service', 'Status', 'Hospital', 'Amount booked', 'Amount executed', 'Insurance'))
		for booking in booking_rows.select_related('lead'):
			write_row((booking.lead.lead_id, booking.lead.name, booking.appointment_at, booking.get_service_type_display(), booking.get_status_display(), booking.hospital, booking.amount_booked or '', booking.amount_executed, booking.insurance))
	elif report == 'daily':
		write_row(('Lead ID', 'Name', 'Mobile', 'Source', 'Temperature', 'Status', 'NP attempt', 'Latest remark', 'Next follow-up'))
		for lead in daily_queue():
			write_row((lead.lead_id, lead.name, lead.mobile, lead.get_source_display(), lead.get_temperature_display(), lead.get_status_display(), lead.np_attempt, lead.latest_remark, lead.next_follow_up or ''))
	elif report == 'revenue':
		write_row(('Lead ID', 'Name', 'Source', 'Campaign', 'Execution date', 'Amount executed'))
		for lead in Lead.objects.filter(amount_executed__gt=0).order_by('-date_executed'):
			write_row((lead.lead_id, lead.name, lead.get_source_display(), lead.campaign, lead.date_executed or '', lead.amount_executed))
	elif report == 'source':
		write_row(('Source', 'Campaign', 'Leads', 'Converted', 'Amount executed'))
		rows = Lead.objects.values('source', 'campaign').annotate(leads=Count('pk'), converted=Count('pk', filter=Q(status=Lead.Status.CONVERTED)), revenue=Sum('amount_executed')).order_by('-leads')
		source_labels = dict(Lead.Source.choices)
		for row in rows:
			write_row((source_labels.get(row['source'], row['source']), row['campaign'], row['leads'], row['converted'], row['revenue'] or 0))
	elif report == 'lost':
		write_row(('Lead ID', 'Name', 'Mobile', 'Source', 'Status', 'Outcome reason', 'Latest remark'))
		for lead in Lead.objects.filter(status__in=(Lead.Status.REJECTED, Lead.Status.WASTE)).order_by('-updated_at'):
			write_row((lead.lead_id, lead.name, lead.mobile, lead.get_source_display(), lead.get_status_display(), lead.get_outcome_reason_display(), lead.latest_remark))
	else:
		write_row(('Lead ID', 'Created', 'Name', 'Mobile', 'Location', 'Source', 'Campaign', 'Care type', 'Temperature', 'Status', 'Outcome', 'Amount pitched', 'Amount executed', 'Next follow-up', 'Priority'))
		for lead in filter_leads(request).order_by('-created_at'):
			write_row((lead.lead_id, lead.created_at, lead.name, lead.mobile, lead.location, lead.get_source_display(), lead.campaign, lead.get_care_type_display(), lead.get_temperature_display(), lead.get_status_display(), lead.get_outcome_reason_display(), lead.amount_pitched or '', lead.amount_executed, lead.next_follow_up or '', lead.priority))
	return response
