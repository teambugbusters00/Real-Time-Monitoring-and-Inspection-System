from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.http import StreamingHttpResponse
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
import cv2
import time
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

    def _can_manage(self, user, project=None):
        if user.role == 'super_admin':
            return True
        if user.role == 'official' and project is not None:
            return project.division_id == user.division_id
        if user.role == 'official' and project is None:
            return True
        return False

    def create(self, request, *args, **kwargs):
        if request.user.role not in ('super_admin', 'official'):
            return Response({'detail': 'Only Super Admins and Officials can create projects.'}, status=403)
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        project = serializer.validated_data.get('project')
        if project is None:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'detail': 'Project is required.'})
        if project.division_id != project.ngo.division_id:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'detail': 'Project division must match the NGO division.'})
        if self.request.user.role == 'official' and project.division_id != self.request.user.division_id:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Project is outside your division.')
        serializer.save()

    def update(self, request, *args, **kwargs):
        project = self.get_object()
        if not self._can_manage(request.user, project):
            return Response({'detail': 'You do not have permission to edit this project.'}, status=403)
        return super().update(request, *args, **kwargs)

    def perform_update(self, serializer):
        division = serializer.validated_data.get('division', serializer.instance.division)
        ngo = serializer.validated_data.get('ngo', serializer.instance.ngo)
        if division.id != ngo.division_id:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'detail': 'Project division must match the NGO division.'})
        if self.request.user.role == 'official' and division.id != self.request.user.division_id:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Project is outside your division.')
        serializer.save()

    def partial_update(self, request, *args, **kwargs):
        project = self.get_object()
        if not self._can_manage(request.user, project):
            return Response({'detail': 'You do not have permission to edit this project.'}, status=403)
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if request.user.role != 'super_admin':
            return Response({'detail': 'Only Super Admins can delete projects.'}, status=403)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['get', 'post'])
    def beneficiaries(self, request, pk=None):
        project = self.get_object()
        if request.method == 'GET':
            beneficiaries = Beneficiary.objects.filter(project=project)
            serializer = BeneficiarySerializer(beneficiaries, many=True)
            return Response(serializer.data)
        elif request.method == 'POST':
            if request.user.role not in ('super_admin', 'official', 'ngo'):
                return Response({'detail': 'Only Super Admins, Officials, or the owning NGO can add beneficiaries.'}, status=403)
            if request.user.role == 'official' and project.division_id != request.user.division_id:
                return Response({'detail': 'Project is outside your division.'}, status=403)
            if request.user.role == 'ngo' and project.ngo_id != request.user.ngo_id:
                return Response({'detail': 'Project does not belong to your NGO.'}, status=403)
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
            if request.user.role not in ('super_admin', 'official'):
                return Response({'detail': 'Only Super Admins or Officials can manage project purpose items.'}, status=403)
            if request.user.role == 'official' and project.division_id != request.user.division_id:
                return Response({'detail': 'Project is outside your division.'}, status=403)
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

    @action(detail=True, methods=['post'], url_path='stream-token')
    def stream_token(self, request, pk=None):
        """Issue a short-lived signed token so an <img> can consume the RTSP relay."""
        camera = self.get_object()
        signer = TimestampSigner(salt='nirikshan-cctv-stream')
        token = signer.sign(f'{request.user.id}:{camera.id}')
        return Response({'token': token, 'expires_in': 300})

    @action(detail=True, methods=['get'], url_path='stream')
    def stream(self, request, pk=None):
        """Relay RTSP/HTTP camera input as browser-compatible MJPEG."""
        camera = self.get_object()
        token = request.query_params.get('token')
        signer = TimestampSigner(salt='nirikshan-cctv-stream')
        try:
            value = signer.unsign(token or '', max_age=300)
            user_id, camera_id = value.split(':', 1)
            if str(camera.id) != camera_id or str(request.user.id) != user_id:
                raise BadSignature('Camera token mismatch')
        except (BadSignature, SignatureExpired, ValueError):
            return Response({'error': 'Invalid or expired CCTV stream token.'}, status=403)

        if not camera.stream_url:
            return Response({'error': 'Camera stream URL is not configured.'}, status=400)

        cap = cv2.VideoCapture(camera.stream_url)
        if not cap.isOpened():
            cap.release()
            return Response({
                'error': 'CCTV source could not be opened from the Render server.',
                'source': camera.stream_url.split('://', 1)[0]
            }, status=502)

        def frames():
            try:
                while True:
                    ok, frame = cap.read()
                    if not ok:
                        break
                    ok, encoded = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                    if not ok:
                        continue
                    yield (b'--frame\\r\\n'
                           b'Content-Type: image/jpeg\\r\\n\\r\\n' +
                           encoded.tobytes() + b'\\r\\n')
                    time.sleep(0.03)
            finally:
                cap.release()

        response = StreamingHttpResponse(
            frames(),
            content_type='multipart/x-mixed-replace; boundary=frame'
        )
        response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response['X-Content-Type-Options'] = 'nosniff'
        return response

    @action(detail=True, methods=['post'], url_path='analyze')
    def analyze(self, request, pk=None):
        """Run lightweight OpenCV analytics on a live camera source."""
        camera = self.get_object()
        if not camera.stream_url:
            return Response({'error': 'Camera stream URL is not configured.'}, status=400)

        cap = cv2.VideoCapture(camera.stream_url)
        if not cap.isOpened():
            cap.release()
            return Response({'error': 'OpenCV could not open the CCTV source from Render.'}, status=502)

        hog = cv2.HOGDescriptor()
        hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

        frames_seen = 0
        people_max = 0
        motion_samples = 0
        motion_percent = 0.0
        brightness_total = 0.0
        previous_gray = None
        started = time.time()

        try:
            while frames_seen < 12 and (time.time() - started) < 8:
                ok, frame = cap.read()
                if not ok:
                    break
                frames_seen += 1

                small = cv2.resize(frame, (640, 360))
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                brightness_total += float(gray.mean())

                if previous_gray is not None:
                    diff = cv2.absdiff(previous_gray, gray)
                    _, threshold = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
                    motion_samples += float((threshold > 0).mean() * 100)
                previous_gray = gray

                if frames_seen % 3 == 0:
                    boxes, _ = hog.detectMultiScale(
                        small,
                        winStride=(8, 8),
                        padding=(8, 8),
                        scale=1.05
                    )
                    people_max = max(people_max, len(boxes))

            avg_brightness = round(brightness_total / frames_seen, 2) if frames_seen else 0
            avg_motion = round(motion_samples / max(1, frames_seen - 1), 2)
            return Response({
                'camera_id': camera.id,
                'camera': camera.name,
                'frames_analyzed': frames_seen,
                'people_detected_max': people_max,
                'motion_percent': avg_motion,
                'average_brightness': avg_brightness,
                'analysis_engine': 'OpenCV HOG + frame-difference',
                'health': 'online' if frames_seen else 'offline',
            })
        finally:
            cap.release()

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
        project = serializer.validated_data.get('project', serializer.instance.project)
        if self.request.user.role == 'official' and project.division_id != self.request.user.division_id:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Camera project is outside your division.')
        if self.request.user.role == 'ngo' and project.ngo_id != self.request.user.ngo_id:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Camera project does not belong to your NGO.')
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
        if self.request.user.role not in ('super_admin', 'official', 'ngo'):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Only Super Admins, Officials, or the owning NGO can add beneficiaries.')
        project = serializer.validated_data.get('project')
        if self.request.user.role == 'official' and project.division_id != self.request.user.division_id:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Project is outside your division.')
        if self.request.user.role == 'ngo' and project.ngo_id != self.request.user.ngo_id:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Project does not belong to your NGO.')
        ben = serializer.save()
        from accounts.models import AuditLog
        AuditLog.log_event(user=self.request.user, action='beneficiary_added', description=f"Beneficiary {ben.name} added to Project #{ben.project_id}.", model_name='Beneficiary', object_id=ben.id, project=ben.project)

    def perform_update(self, serializer):
        if self.request.user.role not in ('super_admin', 'official', 'ngo'):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Only Super Admins, Officials, or the owning NGO can edit beneficiaries.')
        ben_existing = serializer.instance
        if self.request.user.role == 'official' and ben_existing.project.division_id != self.request.user.division_id:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Project is outside your division.')
        if self.request.user.role == 'ngo' and ben_existing.project.ngo_id != self.request.user.ngo_id:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Project does not belong to your NGO.')
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
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'super_admin':
            return Complaint.objects.all().order_by('-created_at')
        if user.role in ('official', 'inspector', 'nss_volunteer'):
            return Complaint.objects.filter(ngo__division=user.division).order_by('-created_at')
        if user.role == 'ngo':
            return Complaint.objects.filter(ngo=user.ngo).order_by('-created_at')
        if user.role == 'citizen':
            return Complaint.objects.filter(submitted_by=user).order_by('-created_at')
        return Complaint.objects.none()

    def create(self, request, *args, **kwargs):
        if request.user.role not in ('citizen', 'ngo'):
            return Response({'detail': 'Only Citizens or NGOs can lodge a complaint/request.'}, status=status.HTTP_403_FORBIDDEN)

        project = None
        project_id = request.data.get('project')
        if project_id:
            try:
                project = Project.objects.select_related('ngo', 'division').get(pk=project_id)
            except Project.DoesNotExist:
                return Response({'detail': 'Selected project does not exist.'}, status=status.HTTP_404_NOT_FOUND)

        if request.user.role == 'citizen' and project is None:
            return Response({'detail': 'Project is required for a citizen grievance.'}, status=status.HTTP_400_BAD_REQUEST)
        if request.user.role == 'ngo' and project is not None and project.ngo_id != request.user.ngo_id:
            return Response({'detail': 'Selected project does not belong to your NGO.'}, status=status.HTTP_403_FORBIDDEN)

        data = request.data.copy()
        data['ngo'] = project.ngo_id if project is not None else request.user.ngo_id
        if project is not None:
            data['project'] = project.id
        data.pop('status', None)
        data.pop('submitted_by', None)

        beneficiary_id = data.get('beneficiary')
        if beneficiary_id:
            try:
                beneficiary = Beneficiary.objects.get(pk=beneficiary_id)
            except Beneficiary.DoesNotExist:
                return Response({'detail': 'Selected beneficiary does not exist.'}, status=status.HTTP_404_NOT_FOUND)
            if project is None or beneficiary.project_id != project.id or beneficiary.project.ngo_id != request.user.ngo_id:
                return Response({'detail': 'Selected beneficiary is outside the allowed project.'}, status=status.HTTP_403_FORBIDDEN)

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        complaint = serializer.save(submitted_by=request.user, status='open')
        from accounts.models import AuditLog
        AuditLog.log_event(user=request.user, action='complaint_created', description=f'Complaint #{complaint.id} created.', model_name='Complaint', object_id=complaint.id, project=complaint.project)
        return Response(self.get_serializer(complaint).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        if request.user.role not in ('official', 'super_admin'):
            return Response({'detail': 'Only Officials or Super Admins can update complaint status.'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        if request.user.role not in ('official', 'super_admin'):
            return Response({'detail': 'Only Officials or Super Admins can update complaint status.'}, status=status.HTTP_403_FORBIDDEN)
        return super().partial_update(request, *args, **kwargs)

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

    def update(self, request, *args, **kwargs):
        return Response({'detail': 'Financial disbursement records are immutable after submission.'}, status=405)

    def partial_update(self, request, *args, **kwargs):
        return Response({'detail': 'Financial disbursement records are immutable after submission.'}, status=405)

    def destroy(self, request, *args, **kwargs):
        return Response({'detail': 'Financial disbursement records cannot be deleted.'}, status=405)

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
            'id', 'scheme_name', 'title', 'ngo_id'
        ).annotate(
            total_allocated=Sum('fund_allocated'),
            ngo_count=Count('ngo', distinct=True)
        )
        return Response([
            {
                'project_id': item['id'],
                'scheme_name': item['scheme_name'],
                'title': item['title'],
                'ngo_id': item['ngo_id'],
                'total_allocated': item['total_allocated'],
                'ngo_count': item['ngo_count'],
            }
            for item in schemes
        ])
