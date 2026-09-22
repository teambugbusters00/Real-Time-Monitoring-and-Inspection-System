from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView
from rest_framework.routers import DefaultRouter
from accounts.views import CustomTokenObtainPairView, DivisionViewSet, NGOViewSet, UserViewSet, BeneficiaryLoginView
from rest_framework_simplejwt.views import TokenRefreshView

from reports.views import InspectionReportViewSet, NGOPeriodicReportViewSet, AnomalyViewSet
from projects.views import ProjectViewSet, ComplaintViewSet, BeneficiaryMeView, BeneficiaryComplaintView, CCTVCameraViewSet
from inspections.views import InspectionViewSet, DutySwapRequestViewSet
from accounts.views import LeaveApplicationViewSet, InspectorActivityLogViewSet

router = DefaultRouter()
router.register(r'divisions', DivisionViewSet, basename='division')
router.register(r'ngos', NGOViewSet, basename='ngo')
router.register(r'users', UserViewSet, basename='user')
router.register(r'inspector-activity', InspectorActivityLogViewSet, basename='inspector-activity')
router.register(r'projects', ProjectViewSet, basename='project')
router.register(r'cctv-cameras', CCTVCameraViewSet, basename='cctv-camera')
router.register(r'inspections', InspectionViewSet, basename='inspection')
router.register(r'reports', InspectionReportViewSet, basename='report')
router.register(r'complaints', ComplaintViewSet, basename='complaint')
router.register(r'ngo-reports', NGOPeriodicReportViewSet, basename='ngo-report')
router.register(r'leaves', LeaveApplicationViewSet, basename='leave')
router.register(r'duty-swaps', DutySwapRequestViewSet, basename='duty-swap')
router.register(r'anomalies', AnomalyViewSet, basename='anomaly')
from projects.views import BeneficiaryViewSet
router.register(r'beneficiaries', BeneficiaryViewSet, basename='beneficiary')
from accounts.views import AuditLogViewSet
router.register(r'audit-logs', AuditLogViewSet, basename='audit-log')
from inspections.views import DirectCallViewSet, CallLogViewSet
router.register(r'direct-calls', DirectCallViewSet, basename='direct-call')
router.register(r'call-logs', CallLogViewSet, basename='call-log')
from reports.views import NSSVisitReportViewSet
router.register(r'nss-reports', NSSVisitReportViewSet, basename='nss-report')
from projects.views import FundDisbursementViewSet
router.register(r'disbursements', FundDisbursementViewSet, basename='disbursement')

from django.views.generic import TemplateView, RedirectView

from accounts.views import CustomTokenObtainPairView, DivisionViewSet, NGOViewSet, UserViewSet

from accounts.views import LogoutView, GoogleLoginView, GoogleClientConfigView, UserRegistrationView, GeminiChatView
from django.conf import settings
from django.conf.urls.static import static
from projects.views import PublicProjectListView

urlpatterns = [
    path('sw.js', TemplateView.as_view(template_name='sw.js', content_type='application/javascript'), name='sw.js'),
    path('manifest.json', TemplateView.as_view(template_name='manifest.json', content_type='application/manifest+json'), name='manifest.json'),

    # Frontend Routes
    path('', TemplateView.as_view(template_name='landing.html'), name='landing_page'),
    path('login/', TemplateView.as_view(template_name='login.html'), name='login_page'),
    path('register/', TemplateView.as_view(template_name='register.html'), name='register_page'),
    path('dashboard/admin/', TemplateView.as_view(template_name='dashboards/admin.html'), name='admin_dashboard'),
    path('dashboard/official/', TemplateView.as_view(template_name='dashboards/official.html'), name='official_dashboard'),
    path('dashboard/inspector/', TemplateView.as_view(template_name='dashboards/inspector.html'), name='inspector_dashboard'),
    path('dashboard/ngo/', TemplateView.as_view(template_name='dashboards/ngo.html'), name='ngo_dashboard'),
    path('dashboard/nss/', TemplateView.as_view(template_name='dashboards/nss.html'), name='nss_dashboard'),
    path('dashboard/citizen/', TemplateView.as_view(template_name='dashboards/citizen.html'), name='citizen_dashboard'),
    path('dashboard/beneficiary/', TemplateView.as_view(template_name='dashboards/beneficiary.html'), name='beneficiary_dashboard'),

    # API Routes
    path('admin/', admin.site.urls),
    path('api/public/projects/', PublicProjectListView.as_view(), name='public_projects'),
    path('api/auth/login/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/auth/login-beneficiary/', BeneficiaryLoginView.as_view(), name='login_beneficiary'),
    path('api/auth/logout/', LogoutView.as_view(), name='logout'),
    path('api/auth/google/', GoogleLoginView.as_view(), name='google_login'),
    path('api/auth/google/config/', GoogleClientConfigView.as_view(), name='google_config'),
    path('api/auth/register/', UserRegistrationView.as_view(), name='user_register'),
    path('api/ai/chat/', GeminiChatView.as_view(), name='gemini_chat'),
    path('api/auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/beneficiary/me/', BeneficiaryMeView.as_view(), name='beneficiary_me'),
    path('api/beneficiary/complaints/', BeneficiaryComplaintView.as_view(), name='beneficiary_complaint'),
    path('api/', include(router.urls)),
]

from django.urls import re_path
from django.views.static import serve
from django.conf import settings

if not settings.DEBUG:
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
        re_path(r'^static/(?P<path>.*)$', serve, {'document_root': settings.STATIC_ROOT}),
    ]
else:
    from django.conf.urls.static import static
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

