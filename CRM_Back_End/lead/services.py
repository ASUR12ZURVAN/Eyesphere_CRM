import csv
import io
from datetime import datetime, time, timedelta

from django.db.models import Case, Count, IntegerField, Max, Q, When
from django.utils import timezone

from .models import AuditLog, CallActivity, FollowUp, Lead


NO_CONTACT_OUTCOMES = {Lead.Outcome.NOT_PICKED_UP, Lead.Outcome.BUSY, Lead.Outcome.DISCONNECTED}


def audit(lead, action, details):
    AuditLog.objects.create(lead=lead, action=action, details=details)


def next_calling_day(from_date=None):
    day = (from_date or timezone.localdate()) + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return timezone.make_aware(datetime.combine(day, time(hour=10)))


def log_call(lead, data):
    outcome = data['outcome']
    called_at = timezone.now()
    no_contact = outcome in NO_CONTACT_OUTCOMES
    conversation = outcome in {Lead.Outcome.CONNECTED, Lead.Outcome.CALLBACK, Lead.Outcome.PRICING_ISSUE, Lead.Outcome.NOT_INTERESTED, Lead.Outcome.CONVERTED, Lead.Outcome.REJECTED}
    np_attempt = lead.np_attempt + 1 if no_contact else 0
    follow_up_at = data.get('next_follow_up')

    if no_contact and np_attempt < 4:
        follow_up_at = next_calling_day()
        lead.status = Lead.Status.NOT_PICKED_UP
    elif no_contact:
        follow_up_at = None
        lead.status = Lead.Status.WASTE
    elif outcome == Lead.Outcome.CALLBACK:
        lead.status = Lead.Status.FOLLOW_UP
    elif outcome == Lead.Outcome.CONVERTED:
        lead.status = Lead.Status.CONVERTED
        lead.converted_at = called_at
        lead.conversion_reason = data.get('remark') or 'Converted from call'
    elif outcome in {Lead.Outcome.REJECTED, Lead.Outcome.WRONG_NUMBER, Lead.Outcome.NOT_INTERESTED}:
        lead.status = Lead.Status.REJECTED
    elif follow_up_at:
        lead.status = Lead.Status.FOLLOW_UP
    elif lead.status in {Lead.Status.NEW, Lead.Status.NOT_PICKED_UP}:
        lead.status = Lead.Status.OPEN

    lead.np_attempt = np_attempt
    lead.outcome_reason = outcome
    lead.conversation_happened = lead.conversation_happened or conversation
    lead.latest_remark = data.get('remark', '')
    lead.next_follow_up = follow_up_at
    if data.get('amount_pitched') is not None:
        lead.amount_pitched = data['amount_pitched']
    lead.save()

    lead.follow_ups.filter(completed_at__isnull=True).update(completed_at=called_at)
    activity = CallActivity.objects.create(
        lead=lead,
        attempt_number=lead.calls.count() + 1,
        called_at=called_at,
        outcome=outcome,
        remark=data.get('remark', ''),
        next_action=follow_up_at,
        conversation_happened=conversation,
    )
    if follow_up_at:
        FollowUp.objects.create(
            lead=lead,
            due_at=follow_up_at,
            kind=FollowUp.Kind.CALLBACK if outcome == Lead.Outcome.CALLBACK else FollowUp.Kind.CALL,
            note=data.get('remark', ''),
        )
    audit(lead, 'call_logged', {'outcome': outcome, 'attempt': activity.attempt_number, 'np_attempt': np_attempt})
    return activity


def daily_queue(limit=65):
    now = timezone.now()
    active_statuses = (Lead.Status.NEW, Lead.Status.OPEN, Lead.Status.FOLLOW_UP, Lead.Status.NOT_PICKED_UP)
    return (
        Lead.objects.filter(status__in=active_statuses)
        .exclude(temperature=Lead.Temperature.FUTURE, next_follow_up__gt=now)
        .exclude(bookings__status__in=('BOOKED', 'COMPLETED'))
        .annotate(call_count=Count('calls', distinct=True), last_called=Max('calls__called_at'))
        .filter(Q(next_follow_up__isnull=True) | Q(next_follow_up__lte=now) | Q(priority=True))
        .annotate(queue_rank=Case(
            When(priority=True, then=0),
            When(status=Lead.Status.NEW, created_at__date=timezone.localdate(), then=1),
            When(next_follow_up__lte=now, then=2),
            When(status=Lead.Status.NOT_PICKED_UP, then=3),
            When(call_count=0, then=4),
            default=5,
            output_field=IntegerField(),
        ))
        .distinct()
        .order_by('queue_rank', '-priority', 'last_called', 'created_at')[:limit]
    )


def parse_csv(uploaded_file):
    raw = uploaded_file.read()
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = raw.decode('cp1252')
    return list(csv.DictReader(io.StringIO(text)))


def canonical_row(row):
    aliases = {
        'name': ('name', 'patient name', 'lead name'),
        'mobile': ('mobile', 'phone', 'phone number', 'mobile number'),
        'source': ('source', 'lead source'),
        'campaign': ('campaign', 'campaign name'),
        'location': ('location', 'city', 'area'),
        'email': ('email', 'email address'),
        'external_source_id': ('external source id', 'external id', 'row id'),
    }
    normalized = {str(key).strip().lower(): (value or '').strip() for key, value in row.items() if key}
    return {target: next((normalized[key] for key in keys if normalized.get(key)), '') for target, keys in aliases.items()}