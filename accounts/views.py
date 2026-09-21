from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from .serializers import CustomTokenObtainPairSerializer, DivisionSerializer, NGOSerializer, UserSerializer
from .models import Division, NGO, User
from .permissions import IsSuperAdmin

from django.utils import timezone
from .models import InspectorActivityLog

class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            # Login successful, log activity if inspector
            user = User.objects.get(username=request.data.get('username'))
            from .models import AuditLog
            AuditLog.log_event(user=user, action="user_login", description=f"{user.username} logged in successfully.", model_name="User", object_id=user.id)
            if user.role == 'inspector':
                # Mark previous active sessions as inactive
                InspectorActivityLog.objects.filter(inspector=user, is_active=True).update(is_active=False, logout_time=timezone.now())
                InspectorActivityLog.objects.create(inspector=user)
        return response

class DivisionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Division.objects.all()
    serializer_class = DivisionSerializer
    permission_classes = [IsSuperAdmin]

class NGOViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = NGOSerializer
    permission_classes = [] # Public can view NGOs to file complaints

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return NGO.objects.all()

        if user.role == 'super_admin':
            return NGO.objects.all()
        elif user.role in ['official', 'inspector']:
            return NGO.objects.filter(division=user.division)
        elif user.role == 'ngo':
            return NGO.objects.filter(id=user.ngo.id)
        return NGO.objects.none()

class UserViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = User.objects.all()

        # Role param filtering
        role_param = self.request.query_params.get('role', None)
        if role_param:
            qs = qs.filter(role=role_param)

        if user.role == 'super_admin':
            return qs
        elif user.role in ['official', 'inspector']:
            return qs.filter(division=user.division)
        elif user.role == 'ngo':
            return qs.filter(ngo=user.ngo)
        
        return User.objects.none()

    from rest_framework.decorators import action
    @action(detail=False, methods=['get'])
    def available_inspectors(self, request):
        user = request.user
        if user.role not in ['official', 'inspector']:
            return Response({'detail': 'Not allowed.'}, status=status.HTTP_403_FORBIDDEN)
        
        # Get inspectors in same division
        inspectors = User.objects.filter(role='inspector', division=user.division).exclude(id=user.id)
        
        # Filter out those with active/upcoming assignments (status='pending' or 'in_progress')
        available = []
        for insp in inspectors:
            has_active = insp.assignments_as_inspector.filter(
                inspection__status__in=['pending', 'in_progress']
            ).exists()
            if not has_active:
                available.append(insp)
                
        serializer = self.get_serializer(available, many=True)
        return Response(serializer.data)

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

class NGOLoginView(APIView):
    permission_classes = []

    def post(self, request):
        ngo_name = request.data.get('ngo_name')
        registration_number = request.data.get('registration_number')

        if not ngo_name or not registration_number:
            return Response({'detail': 'ngo_name and registration_number are required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            ngo = NGO.objects.get(name=ngo_name, registration_number=registration_number)
            user = User.objects.get(ngo=ngo, role='ngo')
            
            refresh = RefreshToken.for_user(user)
            
            from .models import AuditLog
            AuditLog.log_event(user=user, action="ngo_login", description=f"NGO {ngo_name} logged in.", model_name="User", object_id=user.id)
            
            return Response({
                'refresh': str(refresh),
                'access': str(refresh.access_token),
                'role': user.role,
                'division_id': user.division.id if user.division else None,
                'ngo_id': user.ngo.id if user.ngo else None
            }, status=status.HTTP_200_OK)
        except NGO.DoesNotExist:
            return Response({'detail': 'Invalid NGO credentials.'}, status=status.HTTP_401_UNAUTHORIZED)
        except User.DoesNotExist:
            return Response({'detail': 'No user account linked to this NGO.'}, status=status.HTTP_401_UNAUTHORIZED)

class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        from .models import AuditLog
        if user.is_authenticated:
            AuditLog.log_event(user=user, action="user_logout", description=f"{user.username} logged out.", model_name="User", object_id=user.id)
        if user.role == 'inspector':
            active_logs = InspectorActivityLog.objects.filter(inspector=user, is_active=True)
            active_logs.update(logout_time=timezone.now(), is_active=False)
        return Response({'detail': 'Logged out successfully.'}, status=status.HTTP_200_OK)

from .serializers import InspectorActivityLogSerializer

class InspectorActivityLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = InspectorActivityLogSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = InspectorActivityLog.objects.all().order_by('-login_time')

        if user.role == 'super_admin':
            return qs
        elif user.role in ['official', 'inspector']:
            return qs.filter(inspector__division=user.division)
        
        return InspectorActivityLog.objects.none()

from .models import LeaveApplication
from .serializers import LeaveApplicationSerializer

class LeaveApplicationViewSet(viewsets.ModelViewSet):
    serializer_class = LeaveApplicationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'super_admin':
            return LeaveApplication.objects.all()
        elif user.role == 'inspector':
            return LeaveApplication.objects.filter(inspector=user)
        elif user.role == 'official':
            return LeaveApplication.objects.filter(inspector__division=user.division)
        return LeaveApplication.objects.none()


    from rest_framework.decorators import action
    from rest_framework.response import Response
    from inspections.models import InspectionAssignment
    from accounts.models import User
    import random

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        leave = self.get_object()
        if leave.status != 'pending':
            return Response({'detail': 'Leave is already processed.'}, status=400)
        
        leave.status = 'approved'
        leave.save()

        # Reassign inspections scheduled during leave
        assignments = InspectionAssignment.objects.filter(
            inspector=leave.inspector,
            inspection__status='pending',
            inspection__scheduled_time__date__gte=leave.start_date,
            inspection__scheduled_time__date__lte=leave.end_date
        )

        reassigned_count = 0
        for assignment in assignments:
            inspection_date = assignment.inspection.scheduled_time.date()
            
            # Exclude inspectors who are on leave on this date
            on_leave_inspectors = type(leave).objects.filter(
                status='approved',
                start_date__lte=inspection_date,
                end_date__gte=inspection_date
            ).values_list('inspector_id', flat=True)

            eligible_inspectors = User.objects.filter(
                role='inspector',
                division=leave.inspector.division,
                is_active=True
            ).exclude(
                id__in=on_leave_inspectors
            ).exclude(id=leave.inspector.id)

            if eligible_inspectors.exists():
                chosen_inspector = random.choice(list(eligible_inspectors))
                assignment.inspector = chosen_inspector
                assignment.save()
                reassigned_count += 1

        return Response({
            'detail': f'Leave approved. {reassigned_count} inspections reassigned.'
        })

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        leave = self.get_object()
        leave.status = 'rejected'
        leave.save()
        return Response({'detail': 'Leave rejected.'})

    def perform_create(self, serializer):
        serializer.save(inspector=self.request.user)

from .models import AuditLog
from .serializers import AuditLogSerializer

class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AuditLogSerializer
    permission_classes = [IsSuperAdmin]

    def get_queryset(self):
        qs = AuditLog.objects.all().order_by('-timestamp')
        user_id = self.request.query_params.get('user', None)
        if user_id:
            qs = qs.filter(user_id=user_id)
        start_date = self.request.query_params.get('start_date', None)
        if start_date:
            qs = qs.filter(timestamp__gte=start_date)
        end_date = self.request.query_params.get('end_date', None)
        if end_date:
            qs = qs.filter(timestamp__lte=end_date)
        return qs

    from rest_framework.decorators import action
    import hashlib
    
    @action(detail=False, methods=['get'])
    def verify_chain(self, request):
        import hashlib
        logs = AuditLog.objects.order_by('id')
        prev_hash = "0"
        for log in logs:
            if log.previous_hash != prev_hash:
                return Response({"status": "FAILED", "tampering_detected_at": log.id, "reason": f"Broken chain: expected prev {prev_hash}, got {log.previous_hash}"})
            data_str = f"{log.user_id}{log.action}{log.model_name}{log.object_id}{log.field_name}{log.old_value}{log.new_value}{log.description}{log.project_id}{log.inspection_id}{log.report_id}{log.previous_hash}"
            expected_hash = hashlib.sha256(data_str.encode('utf-8')).hexdigest()
            if log.current_hash != expected_hash:
                return Response({"status": "FAILED", "tampering_detected_at": log.id, "reason": "Data modified (hash mismatch)"})
            prev_hash = log.current_hash
        return Response({"status": "VALID", "records_verified": logs.count()})

import jwt
from django.conf import settings
from projects.models import Beneficiary

class BeneficiaryLoginView(APIView):
    permission_classes = []

    def post(self, request):
        pan_number = request.data.get('pan_number')
        phone_number = request.data.get('phone_number')
        
        if not pan_number or not phone_number:
            return Response({'detail': 'PAN number and phone number are required.'}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            beneficiary = Beneficiary.objects.get(pan_number__iexact=pan_number, phone_number=phone_number)
            token = jwt.encode({'beneficiary_id': beneficiary.id}, settings.SECRET_KEY, algorithm='HS256')
            
            # Log it in AuditLog but since beneficiary is not a User, we can leave user=None or create a custom log.
            AuditLog.log_event(user=None, action="beneficiary_login", description=f"Beneficiary {beneficiary.name} (PAN: {pan_number}) logged in.", model_name="Beneficiary", object_id=beneficiary.id)
            
            return Response({
                'access': token,
                'refresh': token, # Dummy refresh to keep frontend happy
                'role': 'beneficiary',
                'name': beneficiary.name
            })
        except Beneficiary.DoesNotExist:
            return Response({'detail': 'No beneficiary found with this PAN and Phone number.'}, status=status.HTTP_401_UNAUTHORIZED)


from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

class GoogleLoginView(APIView):
    """
    Accept a Google Identity Services ID token and exchange it for
    the application's normal Django JWT. Only existing, active users
    with a matching verified email can sign in with Google.
    """
    permission_classes = []

    def post(self, request):
        credential = request.data.get('credential')
        if not credential:
            return Response({'detail': 'Google credential is required.'}, status=status.HTTP_400_BAD_REQUEST)

        client_id = getattr(settings, 'GOOGLE_CLIENT_ID', '')
        if not client_id:
            return Response({'detail': 'Google authentication is not configured.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        try:
            token_info = id_token.verify_oauth2_token(
                credential,
                google_requests.Request(),
                client_id,
            )
        except ValueError:
            return Response({'detail': 'Invalid or expired Google credential.'}, status=status.HTTP_401_UNAUTHORIZED)

        if not token_info.get('email_verified'):
            return Response({'detail': 'Google email is not verified.'}, status=status.HTTP_403_FORBIDDEN)

        email = (token_info.get('email') or '').strip().lower()
        users = User.objects.filter(email__iexact=email, is_active=True)

        if not users.exists():
            return Response(
                {'detail': 'No active Nirikshan account is linked to this Google email.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        if users.count() > 1:
            return Response(
                {'detail': 'Multiple Nirikshan accounts use this email. Contact an administrator.'},
                status=status.HTTP_409_CONFLICT,
            )

        user = users.first()
        refresh = RefreshToken.for_user(user)

        AuditLog.log_event(
            user=user,
            action='google_login',
            description=f'{user.username} signed in with Google.',
            model_name='User',
            object_id=user.id,
        )

        if user.role == 'inspector':
            InspectorActivityLog.objects.filter(
                inspector=user,
                is_active=True
            ).update(is_active=False, logout_time=timezone.now())
            InspectorActivityLog.objects.create(inspector=user)

        return Response({
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'role': user.role,
            'division_id': user.division.id if user.division else None,
            'ngo_id': user.ngo.id if user.ngo else None,
        }, status=status.HTTP_200_OK)


class GoogleClientConfigView(APIView):
    permission_classes = []

    def get(self, request):
        client_id = getattr(settings, 'GOOGLE_CLIENT_ID', '')
        return Response({'client_id': client_id})
