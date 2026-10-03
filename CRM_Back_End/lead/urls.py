from django.urls import path

from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('leads/', views.lead_list, name='lead_list'),
    path('leads/new/', views.lead_form, name='lead_create'),
    path('leads/bulk-update/', views.bulk_update_leads, name='bulk_update_leads'),
    path('leads/<str:lead_id>/', views.lead_detail, name='lead_detail'),
    path('leads/<str:lead_id>/edit/', views.lead_form, name='lead_edit'),
    path('leads/<str:lead_id>/call/', views.log_lead_call, name='log_call'),
    path('leads/<str:lead_id>/follow-up/', views.schedule_follow_up, name='schedule_follow_up'),
    path('leads/<str:lead_id>/reactivate/', views.reactivate_lead, name='reactivate_lead'),
    path('leads/<str:lead_id>/snooze/', views.snooze_follow_up, name='snooze_follow_up'),
    path('leads/<str:lead_id>/booking/', views.create_booking, name='create_booking'),
    path('daily-calling/', views.daily_calling, name='daily_calling'),
    path('bookings/', views.booking_list, name='booking_list'),
    path('import/', views.import_leads, name='lead_import'),
    path('import/confirm/', views.confirm_import, name='confirm_import'),
    path('reports/export/', views.export_csv, name='export_csv'),
]