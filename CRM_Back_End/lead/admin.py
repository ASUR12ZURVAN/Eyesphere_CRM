from django.contrib import admin

from .models import AuditLog, Booking, CallActivity, FollowUp, ImportJob, Lead


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
	list_display = ('lead_id', 'name', 'mobile', 'source', 'temperature', 'status', 'priority', 'created_at')
	list_filter = ('status', 'temperature', 'source', 'priority')
	search_fields = ('lead_id', 'name', 'mobile', 'email', 'campaign')
	readonly_fields = ('lead_id', 'created_at', 'updated_at', 'converted_at')


admin.site.register((CallActivity, FollowUp, Booking, AuditLog, ImportJob))
