import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


def normalize_mobile(value):
    digits = ''.join(character for character in value if character.isdigit())
    if len(digits) == 11 and digits.startswith('0'):
        digits = digits[1:]
    if len(digits) == 10:
        digits = '91' + digits
    if not 8 <= len(digits) <= 15:
        raise ValidationError('Enter a valid mobile number with 8 to 15 digits.')
    return f'+{digits}'


class Lead(models.Model):
    class Source(models.TextChoices):
        META = 'META', 'Meta'
        GOOGLE = 'GOOGLE', 'Google'
        CORPORATE = 'CORPORATE', 'Corporate'
        CAMP = 'CAMP', 'Camp'
        OFFLINE = 'OFFLINE', 'Offline'
        REFERRAL = 'REFERRAL', 'Referral'
        WEBSITE = 'WEBSITE', 'Website'
        WHATSAPP = 'WHATSAPP', 'WhatsApp'
        OTHER = 'OTHER', 'Other'

    class CareType(models.TextChoices):
        AT_HOME = 'AT_HOME', 'At Home Screening / Visit'
        OPD = 'OPD', 'OPD'
        IPD = 'IPD', 'IPD'
        HOSPITAL_REFERRED = 'HOSPITAL_REFERRED', 'Hospital Referred'
        SURGERY = 'SURGERY', 'Surgery'
        MULTIPLE = 'MULTIPLE', 'Multiple'

    class Temperature(models.TextChoices):
        HOT = 'HOT', 'Hot'
        WARM = 'WARM', 'Warm'
        COLD = 'COLD', 'Cold'
        FUTURE = 'FUTURE', 'Future'

    class Status(models.TextChoices):
        NEW = 'NEW', 'New'
        OPEN = 'OPEN', 'Open'
        FOLLOW_UP = 'FOLLOW_UP', 'Follow-up'
        NOT_PICKED_UP = 'NOT_PICKED_UP', 'Not picked up'
        CONVERTED = 'CONVERTED', 'Converted'
        REJECTED = 'REJECTED', 'Rejected'
        WASTE = 'WASTE', 'Waste'

    class Outcome(models.TextChoices):
        NOT_PICKED_UP = 'NOT_PICKED_UP', 'Not picked up'
        BUSY = 'BUSY', 'Busy'
        DISCONNECTED = 'DISCONNECTED', 'Disconnected'
        CONNECTED = 'CONNECTED', 'Connected'
        CALLBACK = 'CALLBACK', 'Callback requested'
        CONVERTED = 'CONVERTED', 'Converted / booked'
        REJECTED = 'REJECTED', 'Rejected / not interested'
        WRONG_NUMBER = 'WRONG_NUMBER', 'Wrong number'
        PRICING_ISSUE = 'PRICING_ISSUE', 'Pricing issue'
        NOT_INTERESTED = 'NOT_INTERESTED', 'Not interested'
        OTHER = 'OTHER', 'Other'

    lead_id = models.CharField(max_length=16, unique=True, editable=False, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    name = models.CharField(max_length=160)
    mobile = models.CharField(max_length=16, unique=True)
    alternate_mobile = models.CharField(max_length=16, blank=True)
    email = models.EmailField(blank=True)
    location = models.CharField(max_length=120, blank=True)
    address = models.TextField(blank=True)
    source = models.CharField(max_length=20, choices=Source.choices)
    campaign = models.CharField(max_length=160, blank=True)
    care_type = models.CharField(max_length=24, choices=CareType.choices, blank=True)
    eye_health_score = models.PositiveSmallIntegerField(null=True, blank=True)
    requirement = models.CharField(max_length=160, blank=True)
    requirement_notes = models.TextField(blank=True)
    temperature = models.CharField(max_length=8, choices=Temperature.choices, default=Temperature.WARM)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.NEW)
    outcome_reason = models.CharField(max_length=24, choices=Outcome.choices, blank=True)
    conversation_happened = models.BooleanField(default=False)
    amount_pitched = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    amount_executed = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    date_executed = models.DateField(null=True, blank=True)
    brochure_sent = models.BooleanField(default=False)
    np_attempt = models.PositiveSmallIntegerField(default=0)
    next_follow_up = models.DateTimeField(null=True, blank=True)
    latest_remark = models.TextField(blank=True)
    priority = models.BooleanField(default=False)
    priority_reason = models.CharField(max_length=240, blank=True)
    created_from = models.CharField(max_length=40, default='Manual')
    external_source_id = models.CharField(max_length=200, blank=True)
    conversion_reason = models.CharField(max_length=240, blank=True)
    converted_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-priority', '-created_at')
        indexes = [
            models.Index(fields=('status', 'next_follow_up')),
            models.Index(fields=('temperature', 'status')),
            models.Index(fields=('source', 'campaign')),
        ]

    def __str__(self):
        return f'{self.lead_id} · {self.name}'

    def can_transition_to(self, status):
        allowed = {
            self.Status.NEW: {self.Status.OPEN, self.Status.FOLLOW_UP, self.Status.NOT_PICKED_UP, self.Status.CONVERTED, self.Status.REJECTED, self.Status.WASTE},
            self.Status.OPEN: {self.Status.FOLLOW_UP, self.Status.NOT_PICKED_UP, self.Status.CONVERTED, self.Status.REJECTED, self.Status.WASTE},
            self.Status.NOT_PICKED_UP: {self.Status.OPEN, self.Status.FOLLOW_UP, self.Status.NOT_PICKED_UP, self.Status.CONVERTED, self.Status.REJECTED, self.Status.WASTE},
            self.Status.FOLLOW_UP: {self.Status.OPEN, self.Status.CONVERTED, self.Status.REJECTED, self.Status.WASTE},
            self.Status.WASTE: {self.Status.OPEN, self.Status.FOLLOW_UP},
            self.Status.REJECTED: {self.Status.OPEN, self.Status.FOLLOW_UP},
            self.Status.CONVERTED: set(),
        }
        return status == self.status or status in allowed.get(self.status, set())

    def save(self, *args, **kwargs):
        self.mobile = normalize_mobile(self.mobile)
        if self.alternate_mobile:
            self.alternate_mobile = normalize_mobile(self.alternate_mobile)
        if not self.lead_id:
            self.lead_id = f'ES-{timezone.now():%y%m%d}-{uuid.uuid4().hex[:5].upper()}'
        if self.status == self.Status.CONVERTED and not self.converted_at:
            self.converted_at = timezone.now()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.status == self.Status.FOLLOW_UP and not self.next_follow_up:
            raise ValidationError({'next_follow_up': 'A follow-up date and time are required.'})
        if self.temperature == self.Temperature.FUTURE and not self.next_follow_up:
            raise ValidationError({'next_follow_up': 'Set a date before snoozing a lead for the future.'})
        if self.status == self.Status.CONVERTED and not (self.conversion_reason or (self.pk and self.bookings.exists())):
            raise ValidationError({'conversion_reason': 'Add a conversion reason or create a booking.'})
        if self.amount_executed and not self.date_executed:
            raise ValidationError({'date_executed': 'An execution date is required when revenue is recorded.'})
        if self.priority and not self.priority_reason:
            raise ValidationError({'priority_reason': 'Add a reason for prioritizing this lead.'})

    @property
    def last_called_at(self):
        return self.calls.order_by('-called_at').values_list('called_at', flat=True).first()

    @property
    def ageing_days(self):
        return max((timezone.localdate() - timezone.localtime(self.created_at).date()).days, 0)

    @property
    def ageing_label(self):
        days = self.ageing_days
        if days <= 2:
            return 'Fresh'
        if days <= 7:
            return 'Ageing'
        if days <= 30:
            return 'Stale risk'
        return 'Long-open'


class CallActivity(models.Model):
    lead = models.ForeignKey(Lead, related_name='calls', on_delete=models.CASCADE)
    attempt_number = models.PositiveSmallIntegerField()
    called_at = models.DateTimeField(default=timezone.now)
    outcome = models.CharField(max_length=24, choices=Lead.Outcome.choices)
    remark = models.TextField(blank=True)
    next_action = models.DateTimeField(null=True, blank=True)
    conversation_happened = models.BooleanField(default=False)

    class Meta:
        ordering = ('-called_at',)


class FollowUp(models.Model):
    class Kind(models.TextChoices):
        CALL = 'CALL', 'Call'
        CALLBACK = 'CALLBACK', 'Callback'
        BOOKING = 'BOOKING', 'Booking'
        OTHER = 'OTHER', 'Other'

    lead = models.ForeignKey(Lead, related_name='follow_ups', on_delete=models.CASCADE)
    due_at = models.DateTimeField()
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.CALL)
    note = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    snoozed_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('due_at',)


class Booking(models.Model):
    class Status(models.TextChoices):
        BOOKED = 'BOOKED', 'Booked'
        COMPLETED = 'COMPLETED', 'Completed'
        CANCELLED = 'CANCELLED', 'Cancelled'
        RESCHEDULED = 'RESCHEDULED', 'Rescheduled'
        NO_SHOW = 'NO_SHOW', 'No show'

    class InsuranceStatus(models.TextChoices):
        NOT_APPLICABLE = 'NOT_APPLICABLE', 'Not applicable'
        PENDING = 'PENDING', 'Pending'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'
        SETTLED = 'SETTLED', 'Settled'

    lead = models.ForeignKey(Lead, related_name='bookings', on_delete=models.CASCADE)
    appointment_at = models.DateTimeField()
    service_type = models.CharField(max_length=24, choices=Lead.CareType.choices)
    hospital = models.CharField(max_length=160, blank=True)
    doctor = models.CharField(max_length=160, blank=True)
    amount_pitched = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    amount_booked = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    amount_executed = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    insurance = models.BooleanField(default=False)
    insurance_status = models.CharField(max_length=16, choices=InsuranceStatus.choices, default=InsuranceStatus.NOT_APPLICABLE)
    patient_payable = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.BOOKED)
    execution_date = models.DateField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ('appointment_at',)

    def clean(self):
        super().clean()
        if self.status == self.Status.COMPLETED and not self.execution_date:
            raise ValidationError({'execution_date': 'An execution date is required for completed bookings.'})
        if self.amount_executed and not self.execution_date:
            raise ValidationError({'execution_date': 'An execution date is required when revenue is recorded.'})
        if self.status in (self.Status.CANCELLED, self.Status.RESCHEDULED) and not self.cancellation_reason:
            raise ValidationError({'cancellation_reason': 'Add a reason for this booking change.'})


class AuditLog(models.Model):
    lead = models.ForeignKey(Lead, related_name='audit_entries', null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=40)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ('-created_at',)


class ImportJob(models.Model):
    file_name = models.CharField(max_length=255)
    rows_read = models.PositiveIntegerField(default=0)
    rows_imported = models.PositiveIntegerField(default=0)
    rows_skipped = models.PositiveIntegerField(default=0)
    rows_failed = models.PositiveIntegerField(default=0)
    errors = models.JSONField(default=list)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    def __str__(self):
        return self.file_name
