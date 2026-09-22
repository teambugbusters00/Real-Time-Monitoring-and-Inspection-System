from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import Project, Beneficiary, PurposeItem, CCTVCamera
from .serializers import ProjectSerializer, BeneficiarySerializer, PurposeItemSerializer, CCTVCameraSerializer
from accounts.permissions import IsSuperAdmin, IsOfficialOfDivision, IsOwnerNGO

class ProjectViewSet(viewsets.ModelViewSet):
    serializer_class = ProjectSerializer
    permission_classes = [IsAuthenticated] # Fine-grained object permissions can be checked per action

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return Project.objects.none()
            
        if user.role == 'super_admin':
            return Project.objects.all()
        elif user.role in ['official', 'inspector', 'nss_volunteer']:
            return Project.objects.filter(division=user.division)
        elif user.role == 'ngo':
            return Project.objects.filter(ngo=user.ngo)
        return Project.objects.none()

    @action(detail=True, methods=['get', 'post'])
    def beneficiaries(self, request, pk=None):
        project = self.get_object()
        if request.method == 'GET':
            beneficiaries = Beneficiary.objects.filter(project=project)
            serializer = BeneficiarySerializer(beneficiaries, many=True)
            return Response(serializer.data)
        elif request.method == 'POST':
            # Create beneficiary
            data = request.data.copy()
            data['project'] = project.id
            serializer = BeneficiarySerializer(data=data)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data, status=201)
            return Response(serializer.errors, status=400)

    @action(detail=True, methods=['get', 'post'])
    def purpose_items(self, request, pk=None):
        project = self.get_object()
        if request.method == 'GET':
            items = PurposeItem.objects.filter(project=project)
            serializer = PurposeItemSerializer(items, many=True)
            return Response(serializer.data)
        elif request.method == 'POST':
            data = request.data.copy()
            data['project'] = project.id
            serializer = PurposeItemSerializer(data=data)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data, status=201)
            return Response(serializer.errors, status=400)


class CCTVCameraViewSet(viewsets.ModelViewSet):
    """Manage project CCTV metadata without exposing cameras across divisions."""
    serializer_class = CCTVCameraSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = CCTVCamera.objects.select_related('project').order_by('project_id', 'name')
        if user.role == 'super_admin':
            return qs
        if user.role in ['official', 'inspector', 'nss_volunteer']:
            return qs.filter(project__division=user.division)
        if user.role == 'ngo':
            return qs.filter(project__ngo=user.ngo)
        return qs.none()

    def perform_create(self, serializer):
        if self.request.user.role not in ['super_admin', 'official', 'ngo']:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Only officials, super admins, or the owning NGO can add cameras.')
        project = serializer.validated_data.get('project')
        if self.request.user.role == 'official' and project.division_id != self.request.user.division_id:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Camera project is outside your division.')
        if self.request.user.role == 'ngo' and project.ngo_id != self.request.user.ngo_id:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Camera project does not belong to your NGO.')
        serializer.save()

    def perform_update(self, serializer):
        if self.request.user.role not in ['super_admin', 'official', 'ngo']:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Only officials, super admins, or the owning NGO can edit cameras.')
        serializer.save()


class BeneficiaryViewSet(viewsets.ModelViewSet):
    serializer_class = BeneficiarySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return Beneficiary.objects.none()
            
        if user.role == 'super_admin':
            return Beneficiary.objects.all()
        elif user.role in ['official', 'inspector', 'nss_volunteer']:
            return Beneficiary.objects.filter(project__division=user.division)
        elif user.role == 'ngo':
            return Beneficiary.objects.filter(project__ngo=user.ngo)
        return Beneficiary.objects.none()

    def perform_create(self, serializer):
        ben = serializer.save()
        from accounts.models import AuditLog
        AuditLog.log_event(user=self.request.user, action='beneficiary_added', description=f"Beneficiary {ben.name} added to Project #{ben.project_id}.", model_name='Beneficiary', object_id=ben.id, project=ben.project)

    def perform_update(self, serializer):
        ben = serializer.save()
        from accounts.models import AuditLog
        AuditLog.log_event(user=self.request.user, action='beneficiary_updated', description=f"Beneficiary {ben.name} updated.", model_name='Beneficiary', object_id=ben.id, project=ben.project)

    @action(detail=True, methods=['post'])
    def confirm_duplicate(self, request, pk=None):
        beneficiary = self.get_object()
        beneficiary.duplicate_status = 'confirmed'
        beneficiary.save(update_fields=['duplicate_status'])
        return Response({'status': 'confirmed'})

    @action(detail=True, methods=['post'])
    def dismiss_duplicate(self, request, pk=None):
        beneficiary = self.get_object()
        beneficiary.duplicate_status = 'dismissed'
        beneficiary.save(update_fields=['duplicate_status'])
        return Response({'status': 'dismissed'})

from .models import Complaint
from .serializers import ComplaintSerializer

class ComplaintViewSet(viewsets.ModelViewSet):
    serializer_class = ComplaintSerializer
    permission_classes = [] # Publicly readable/writable (can be locked down if needed)

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return Complaint.objects.all() # Public viewing of complaints? Or restrict? Let's return all.
            
        if user.role == 'super_admin':
            return Complaint.objects.all()
        elif user.role in ['official', 'inspector', 'nss_volunteer']:
            return Complaint.objects.filter(ngo__division=user.division)
        elif user.role == 'ngo':
            return Complaint.objects.filter(ngo=user.ngo)
        return Complaint.objects.all()

import jwt
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from django.db.models import Sum, Count

from rest_framework.response import Response
from rest_framework import status

def get_beneficiary_from_request(request):
    auth = request.headers.get('Authorization')
    if auth and auth.startswith('Bearer '):
        token = auth.split(' ')[1]
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
            if 'beneficiary_id' in payload:
                return Beneficiary.objects.get(id=payload['beneficiary_id'])
        except Exception:
            pass
    return None

class BeneficiaryMeView(APIView):
    authentication_classes = []
    permission_classes = [] # Handled manually

    def get(self, request):
        beneficiary = get_beneficiary_from_request(request)
        if not beneficiary:
            return Response({'detail': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
            
        project = beneficiary.project
        complaints = Complaint.objects.filter(beneficiary=beneficiary).order_by('-created_at')
        complaints_data = [{
            'id': c.id,
            'subject': c.subject,
            'description': c.description,
            'status': c.status,
            'created_at': c.created_at
        } for c in complaints]
        
        return Response({
            'name': beneficiary.name,
            'phone_number': beneficiary.phone_number,
            'pan_number': beneficiary.pan_number,
            'project': {
                'id': project.id,
                'title': project.title,
                'ngo_name': project.ngo.name,
                'status': project.status,
                'fund_allocated': project.fund_allocated
            },
            'complaints': complaints_data
        })

class BeneficiaryComplaintView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        beneficiary = get_beneficiary_from_request(request)
        if not beneficiary:
            return Response({'detail': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
            
        subject = request.data.get('subject')
        description = request.data.get('description')
        
        if not subject or not description:
            return Response({'detail': 'Subject and description are required.'}, status=status.HTTP_400_BAD_REQUEST)
            
        complaint = Complaint.objects.create(
            ngo=beneficiary.project.ngo,
            project=beneficiary.project,
            beneficiary=beneficiary,
            subject=subject,
            description=description,
            status='open'
        )
        return Response({'detail': 'Complaint submitted successfully.', 'id': complaint.id}, status=status.HTTP_201_CREATED)

from .models import FundDisbursement
from .serializers import FundDisbursementSerializer
from rest_framework import viewsets

class FundDisbursementViewSet(viewsets.ModelViewSet):
    serializer_class = FundDisbursementSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        queryset = FundDisbursement.objects.all().order_by('-disbursed_date')
        
        project_id = self.request.query_params.get('project', None)
        if project_id:
            queryset = queryset.filter(project_id=project_id)
            
        if user.role == 'ngo':
            return queryset.filter(project__ngo=user.ngo)
        elif user.role in ['official', 'inspector', 'nss_volunteer']:
            return queryset.filter(project__ngo__division=user.division)
        return queryset

    def create(self, request, *args, **kwargs):
        user = request.user
        if user.role != 'ngo':
            return Response({'detail': 'Only NGOs can log disbursements.'}, status=status.HTTP_403_FORBIDDEN)
            
        pan_number = request.data.get('pan_number')
        project_id = request.data.get('project')
        
        if not pan_number or not project_id:
            return Response({'detail': 'pan_number and project are required.'}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            # We look up the beneficiary by PAN, ensuring they are enrolled in this project
            beneficiary = Beneficiary.objects.get(pan_number__iexact=pan_number, project_id=project_id)
        except Beneficiary.DoesNotExist:
            return Response({'detail': 'No beneficiary found with this PAN in the specified project.'}, status=status.HTTP_404_NOT_FOUND)
            
        # Verify the project belongs to the NGO
        project = Project.objects.get(id=project_id)
        if project.ngo != user.ngo:
            return Response({'detail': 'Project does not belong to your NGO.'}, status=status.HTTP_403_FORBIDDEN)
            
        # Add beneficiary ID to data
        request_data = request.data.copy()
        request_data['beneficiary'] = beneficiary.id
        
        serializer = self.get_serializer(data=request_data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class PublicProjectListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        # Group by scheme title
        schemes = Project.objects.filter(status='active').values(
            'scheme_name', 'title'
        ).annotate(
            total_allocated=Sum('fund_allocated'),
            ngo_count=Count('ngo', distinct=True)
        )
        return Response(list(schemes))
