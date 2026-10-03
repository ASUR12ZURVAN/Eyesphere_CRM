from django.utils import timezone

from .models import Lead


def crm_counts(request):
    if not request.user.is_authenticated:
        return {}
    due_count = Lead.objects.filter(next_follow_up__lte=timezone.now()).exclude(
        status__in=(Lead.Status.CONVERTED, Lead.Status.REJECTED, Lead.Status.WASTE),
    ).count()
    return {'sidebar_due_count': due_count}