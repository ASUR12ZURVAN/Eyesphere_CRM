"""
URL configuration for CRM_Back_End project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from lead import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/login/', auth_views.LoginView.as_view(template_name='lead/login.html'), name='login'),
    path('accounts/password-reset/', auth_views.PasswordResetView.as_view(
        template_name='lead/password_reset_form.html',
        email_template_name='lead/password_reset_email.html',
        subject_template_name='lead/password_reset_subject.txt',
        success_url='/accounts/password-reset/done/',
    ), name='password_reset'),
    path('accounts/password-reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='lead/password_reset_done.html',
    ), name='password_reset_done'),
    path('accounts/reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='lead/password_reset_confirm.html',
        success_url='/accounts/reset/done/',
    ), name='password_reset_confirm'),
    path('accounts/reset/done/', auth_views.PasswordResetCompleteView.as_view(
        template_name='lead/password_reset_complete.html',
    ), name='password_reset_complete'),
    path('accounts/password-change/', views.request_password_change, name='password_change_request'),
    path('accounts/password-change/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='lead/password_change_confirm.html',
        success_url='/accounts/password-change/done/',
    ), name='password_change_confirm'),
    path('accounts/password-change/done/', auth_views.PasswordResetCompleteView.as_view(
        template_name='lead/password_change_complete.html',
    ), name='password_change_complete'),
    path('accounts/create/', views.create_account, name='create_account'),
    path('accounts/logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('', include('lead.urls')),
]
