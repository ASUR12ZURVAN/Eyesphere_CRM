from django import forms

from .models import Booking, FollowUp, Lead, normalize_mobile


class StyledFormMixin:
    def apply_styles(self):
        for field in self.fields.values():
            existing = field.widget.attrs.get('class', '')
            field.widget.attrs['class'] = f'{existing} field-control'.strip()


class LeadForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Lead
        fields = (
            'name', 'mobile', 'alternate_mobile', 'email', 'location', 'address',
            'source', 'campaign', 'care_type', 'eye_health_score', 'requirement',
            'requirement_notes', 'temperature', 'status', 'outcome_reason',
            'conversation_happened', 'amount_pitched', 'amount_executed',
            'date_executed', 'brochure_sent', 'next_follow_up', 'latest_remark',
            'priority', 'priority_reason', 'external_source_id', 'conversion_reason',
        )
        widgets = {
            'address': forms.Textarea(attrs={'rows': 2}),
            'requirement_notes': forms.Textarea(attrs={'rows': 2}),
            'latest_remark': forms.Textarea(attrs={'rows': 2}),
            'next_follow_up': forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'}),
            'date_executed': forms.DateInput(attrs={'type': 'date'}),
            'amount_pitched': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
            'amount_executed': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
            'eye_health_score': forms.NumberInput(attrs={'min': '0', 'max': '100'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_styles()
        self.fields['next_follow_up'].input_formats = ['%Y-%m-%dT%H:%M']
        self.fields['mobile'].help_text = 'Indian 10-digit numbers are saved with +91.'

    def clean_mobile(self):
        try:
            mobile = normalize_mobile(self.cleaned_data['mobile'])
        except forms.ValidationError as error:
            raise forms.ValidationError(error.messages) from error
        duplicate = Lead.objects.filter(mobile=mobile)
        if self.instance.pk:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if duplicate.exists():
            existing = duplicate.first()
            raise forms.ValidationError(f'This number already belongs to {existing.name} ({existing.lead_id}). Open that record instead.')
        return mobile

    def clean_alternate_mobile(self):
        value = self.cleaned_data.get('alternate_mobile', '')
        if not value:
            return value
        try:
            return normalize_mobile(value)
        except forms.ValidationError as error:
            raise forms.ValidationError(error.messages) from error

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('priority') and not cleaned.get('priority_reason'):
            self.add_error('priority_reason', 'Add a reason for prioritizing this lead.')
        if cleaned.get('status') == Lead.Status.FOLLOW_UP and not cleaned.get('next_follow_up'):
            self.add_error('next_follow_up', 'A follow-up date and time are required.')
        if cleaned.get('temperature') == Lead.Temperature.FUTURE and not cleaned.get('next_follow_up'):
            self.add_error('next_follow_up', 'Set a follow-up date before snoozing this lead.')
        if cleaned.get('amount_executed') and not cleaned.get('date_executed'):
            self.add_error('date_executed', 'An execution date is required when revenue is recorded.')
        if self.instance.pk and not self.instance.can_transition_to(cleaned.get('status')):
            self.add_error('status', 'That status transition is not allowed. Reactivate closed leads from their profile.')
        return cleaned


class CallForm(StyledFormMixin, forms.Form):
    outcome = forms.ChoiceField(choices=(('', 'Select an outcome'), *Lead.Outcome.choices))
    remark = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}))
    next_follow_up = forms.DateTimeField(required=False, input_formats=['%Y-%m-%dT%H:%M'], widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'}))
    amount_pitched = forms.DecimalField(required=False, min_value=0, max_digits=12, decimal_places=2, widget=forms.NumberInput(attrs={'step': '0.01', 'min': '0'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_styles()

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('outcome') == Lead.Outcome.CALLBACK and not cleaned.get('next_follow_up'):
            self.add_error('next_follow_up', 'Choose when the patient asked to be called back.')
        if cleaned.get('outcome') == Lead.Outcome.PRICING_ISSUE and not cleaned.get('amount_pitched'):
            self.add_error('amount_pitched', 'Record the amount pitched for a pricing concern.')
        return cleaned


class FollowUpForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = FollowUp
        fields = ('due_at', 'kind', 'note')
        widgets = {'due_at': forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['due_at'].input_formats = ['%Y-%m-%dT%H:%M']
        self.apply_styles()


class ReactivateForm(StyledFormMixin, forms.Form):
    reason = forms.CharField(max_length=240, widget=forms.TextInput(attrs={'placeholder': 'Why is this lead reactivating?'}))
    next_follow_up = forms.DateTimeField(input_formats=['%Y-%m-%dT%H:%M'], widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_styles()


class SnoozeForm(StyledFormMixin, forms.Form):
    due_at = forms.DateTimeField(label='Snooze until', input_formats=['%Y-%m-%dT%H:%M'], widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_styles()


class BookingForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Booking
        fields = (
            'appointment_at', 'service_type', 'hospital', 'doctor', 'amount_pitched',
            'amount_booked', 'amount_executed', 'insurance', 'insurance_status',
            'patient_payable', 'status', 'execution_date', 'cancellation_reason',
        )
        widgets = {
            'appointment_at': forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'}),
            'execution_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['appointment_at'].input_formats = ['%Y-%m-%dT%H:%M']
        self.apply_styles()


class CSVUploadForm(StyledFormMixin, forms.Form):
    file = forms.FileField(help_text='Upload a CSV with Name, Mobile, and Source columns.')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_styles()

    def clean_file(self):
        uploaded = self.cleaned_data['file']
        if not uploaded.name.lower().endswith('.csv'):
            raise forms.ValidationError('Use a CSV file. Excel workbooks can be exported as CSV before import.')
        if uploaded.size > 5 * 1024 * 1024:
            raise forms.ValidationError('CSV files must be 5 MB or smaller.')
        return uploaded


class BulkLeadForm(StyledFormMixin, forms.Form):
    temperature = forms.ChoiceField(choices=(('', 'No temperature change'), *Lead.Temperature.choices), required=False)
    status = forms.ChoiceField(choices=(('', 'No status change'), *((value, label) for value, label in Lead.Status.choices if value != Lead.Status.CONVERTED)), required=False)
    source = forms.ChoiceField(choices=(('', 'No source change'), *Lead.Source.choices), required=False)
    next_follow_up = forms.DateTimeField(required=False, input_formats=['%Y-%m-%dT%H:%M'], widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_styles()

    def clean(self):
        cleaned = super().clean()
        if not any(cleaned.get(field) for field in ('temperature', 'status', 'source', 'next_follow_up')):
            raise forms.ValidationError('Choose at least one change to apply.')
        if cleaned.get('status') == Lead.Status.FOLLOW_UP and not (cleaned.get('next_follow_up')):
            raise forms.ValidationError('A new follow-up date is required when setting the status to Follow-up.')
        if cleaned.get('temperature') == Lead.Temperature.FUTURE and not cleaned.get('next_follow_up'):
            raise forms.ValidationError('A follow-up date is required when setting the temperature to Future.')
        if cleaned.get('status') in (Lead.Status.REJECTED, Lead.Status.WASTE) and cleaned.get('next_follow_up'):
            raise forms.ValidationError('Closed leads cannot have a new follow-up date.')
        return cleaned