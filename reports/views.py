import hashlib
import json
from django.utils import timezone
from django.db.models import Sum
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import InspectionReport, Evidence, Anomaly, ReportBlock
from .serializers import InspectionReportSerializer, EvidenceSerializer
import math

def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371000  # Radius of earth in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2.0) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * \
        math.sin(delta_lambda / 2.0) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

class InspectionReportViewSet(viewsets.ModelViewSet):
    serializer_class = InspectionReportSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return InspectionReport.objects.none()

        if user.role == 'super_admin':
            return InspectionReport.objects.all()
        elif user.role == 'official':
            return InspectionReport.objects.filter(inspection__project__division=user.division)
        elif user.role == 'inspector':
            return InspectionReport.objects.filter(inspection__inspectionassignment__inspector=user)
        elif user.role == 'ngo':
            return InspectionReport.objects.filter(inspection__project__ngo=user.ngo)
        return InspectionReport.objects.none()

    def create(self, request, *args, **kwargs):
        client_submission_id = request.data.get('client_submission_id')
        if client_submission_id:
            existing = InspectionReport.objects.filter(client_submission_id=client_submission_id).first()
            if existing:
                serializer = self.get_serializer(existing)
                return Response(serializer.data, status=status.HTTP_200_OK)
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.status == 'finalized':
            from accounts.models import AuditLog
            from accounts.middleware import get_current_user
            AuditLog.log_event(
                user=get_current_user(),
                action='attempted_finalized_report_edit',
                description="Attempted to modify a finalized inspection report.",
                model_name='InspectionReport',
                object_id=instance.id,
                report=instance,
                inspection=instance.inspection,
                project=instance.inspection.project
            )
            return Response({'detail': 'Cannot modify a finalized report.'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def perform_create(self, serializer):
        report = serializer.save(submitted_by=self.request.user, status='draft')
        from accounts.models import AuditLog
        AuditLog.log_event(
            user=self.request.user,
            action='report_submitted',
            description=f"Draft report created for inspection #{report.inspection_id}.",
            model_name='InspectionReport',
            object_id=report.id,
            inspection=report.inspection,
            project=report.inspection.project,
            report=report
        )

    @action(detail=True, methods=['post'])
    def evidence(self, request, pk=None):
        report = self.get_object()
        if report.status == 'finalized':
            return Response({"error": "Cannot add evidence to a finalized report."}, status=status.HTTP_400_BAD_REQUEST)
            
        data = request.data.copy()
        print(f"Incoming Evidence Request Data: {request.data}")
        data['report'] = report.id
        serializer = EvidenceSerializer(data=data)
        if serializer.is_valid():
            evidence = serializer.save()
            response_data = serializer.data
            response_data['consistency_checked'] = False
            
            # Location Consistency Check
            proj = report.inspection.project
            if proj.latitude is not None and proj.longitude is not None:
                if evidence.geo_lat is not None and evidence.geo_lng is not None:
                    response_data['consistency_checked'] = True
                    dist = calculate_distance(evidence.geo_lat, evidence.geo_lng, proj.latitude, proj.longitude)
                    if dist > 500:
                        evidence.location_flagged = True
                        evidence.save()
                        response_data['location_flagged'] = True
                        anomaly = Anomaly.objects.create(
                            report=report,
                            type='location_mismatch',
                            description=f"Evidence uploaded {int(dist)} meters away from registered project site.",
                            severity='medium'
                        )
                        from accounts.models import AuditLog
                        AuditLog.log_event(user=request.user, action='anomaly_flagged', description="Location mismatch anomaly flagged.", model_name='Anomaly', object_id=anomaly.id, report=report, inspection=report.inspection, project=proj)
                        
            from accounts.models import AuditLog
            AuditLog.log_event(user=request.user, action='evidence_uploaded', description="Evidence photo uploaded.", model_name='Evidence', object_id=evidence.id, report=report, inspection=report.inspection, project=report.inspection.project)
            return Response(response_data, status=status.HTTP_201_CREATED)
        
        print(f"Evidence Upload Failed: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['patch'])
    def finalize(self, request, pk=None):
        report = self.get_object()

        if request.user.role not in ['inspector', 'super_admin']:
            return Response({"error": "Only the assigned Inspector or Super Admin can finalize an inspection report."}, status=status.HTTP_403_FORBIDDEN)
        
        if report.status == 'finalized':
            return Response({"error": "Report is already finalized."}, status=status.HTTP_400_BAD_REQUEST)

        # 1. Update fields and Validate if provided
        project = report.inspection.project
        from decimal import Decimal, InvalidOperation

        if 'fund_utilized_verified' in request.data and request.data['fund_utilized_verified'] not in [None, ""]:
            try:
                fund_val = Decimal(str(request.data['fund_utilized_verified']))
                if project.fund_allocated is not None and fund_val > project.fund_allocated:
                    return Response({"error": "Verified fund cannot exceed allocated fund."}, status=status.HTTP_400_BAD_REQUEST)
                report.fund_utilized_verified = fund_val
            except InvalidOperation:
                return Response({"error": "Invalid fund utilized format."}, status=status.HTTP_400_BAD_REQUEST)

        # Recalculate Ghost Beneficiaries
        total_registered = project.beneficiary_set.count()
        claimed_count = project.beneficiary_set.filter(claimed=True).count()
        report.beneficiaries_claimed_count = claimed_count

        if 'beneficiaries_verified_count' in request.data:
            try:
                verified_count = int(request.data['beneficiaries_verified_count'])
                if verified_count < 0 or verified_count > total_registered or verified_count > claimed_count:
                    return Response({"error": "Invalid beneficiary verification count"}, status=status.HTTP_400_BAD_REQUEST)
                report.beneficiaries_verified_count = verified_count
            except ValueError:
                return Response({"error": "Invalid beneficiary verification count format"}, status=status.HTTP_400_BAD_REQUEST)

        report.ghost_beneficiaries_count = max(0, report.beneficiaries_claimed_count - report.beneficiaries_verified_count)

        # Deterministic anomaly checks complement the AI analysis.
        # They are generated from the submitted verified values and the project's
        # own records, so an AI outage cannot hide a material discrepancy.
        if report.fund_utilized_verified is not None:
            claimed_fund = project.fund_utilized_claimed or Decimal('0')
            fund_gap = abs(Decimal(str(report.fund_utilized_verified)) - Decimal(str(claimed_fund)))
            if fund_gap > Decimal('0.01'):
                severity = 'high' if claimed_fund and (fund_gap / claimed_fund) >= Decimal('0.20') else 'medium'
                Anomaly.objects.update_or_create(
                    report=report, type='fund_mismatch',
                    defaults={
                        'description': f'Claimed utilization ₹{claimed_fund} differs from verified utilization ₹{report.fund_utilized_verified}.',
                        'severity': severity
                    }
                )

        if report.ghost_beneficiaries_count > 0:
            severity = 'high' if report.ghost_beneficiaries_count >= 5 else 'medium'
            Anomaly.objects.update_or_create(
                report=report, type='ghost_beneficiary',
                defaults={
                    'description': f'{report.ghost_beneficiaries_count} claimed beneficiaries were not verified during inspection.',
                    'severity': severity
                }
            )

        total_disbursed = project.disbursements.aggregate(total=Sum('amount')).get('total') or Decimal('0')
        if report.fund_utilized_verified is not None and total_disbursed > Decimal(str(report.fund_utilized_verified)) + Decimal('0.01'):
            Anomaly.objects.update_or_create(
                report=report, type='fund_mismatch',
                defaults={
                    'description': f'Logged beneficiary disbursements ₹{total_disbursed} exceed verified utilization ₹{report.fund_utilized_verified}.',
                    'severity': 'high'
                }
            )
        

        # NEW INSPECTION MODULE LOGIC
        if 'cctv_status' in request.data:
            report.cctv_status = request.data['cctv_status']
        if 'cctv_last_record_time' in request.data and request.data['cctv_last_record_time']:
            report.cctv_last_record_time = request.data['cctv_last_record_time']
            
        from .models import ReportChecklistAnswer, ReportViolation, ReportAssetVerification, ReportBeneficiaryLog, ReportFeedback
        
        # Save Checklist Answers
        if 'checklist_answers' in request.data:
            for ans in request.data['checklist_answers']:
                ReportChecklistAnswer.objects.create(
                    report=report,
                    category=ans.get('category', 'General'),
                    question=ans.get('question', ''),
                    is_compliant=ans.get('is_compliant', False),
                    remarks=ans.get('remarks', '')
                )
                
        # Save Violations
        if 'violations' in request.data:
            for vio in request.data['violations']:
                ReportViolation.objects.create(
                    report=report,
                    severity=vio.get('severity', 'minor'),
                    description=vio.get('description', ''),
                    corrective_deadline=vio.get('corrective_deadline') or None
                )
                
        # Save Assets Verification
        if 'asset_verifications' in request.data:
            from projects.models import ProjectAsset
            for av in request.data['asset_verifications']:
                try:
                    asset_obj = ProjectAsset.objects.get(id=av['asset_id'])
                    ReportAssetVerification.objects.create(
                        report=report,
                        asset=asset_obj,
                        found_quantity=av.get('found_quantity', 0),
                        condition=av.get('condition', ''),
                        discrepancy_flag=av.get('discrepancy_flag', False)
                    )
                except ProjectAsset.DoesNotExist:
                    pass

        # Save Beneficiary Logs
        if 'beneficiary_logs' in request.data:
            from projects.models import Beneficiary
            for bl in request.data['beneficiary_logs']:
                try:
                    ben_obj = Beneficiary.objects.get(id=bl['beneficiary_id'])
                    ReportBeneficiaryLog.objects.create(
                        report=report,
                        beneficiary=ben_obj,
                        interaction_notes=bl.get('interaction_notes', ''),
                        satisfaction_score=bl.get('satisfaction_score')
                    )
                except Beneficiary.DoesNotExist:
                    pass
                    
        # Save Feedback
        if 'feedback' in request.data:
            fb = request.data['feedback']
            ReportFeedback.objects.create(
                report=report,
                food_rating=fb.get('food_rating'),
                medical_rating=fb.get('medical_rating'),
                staff_rating=fb.get('staff_rating'),
                cleanliness_rating=fb.get('cleanliness_rating'),
                safety_rating=fb.get('safety_rating')
            )
            
        # Calculate compliance score
        answers = report.checklist_answers.all()
        if answers.exists():
            compliant_count = answers.filter(is_compliant=True).count()
            report.compliance_percentage = (compliant_count / answers.count()) * 100
        else:
            report.compliance_percentage = 100.0

        # Calculate final status
        critical_v = report.violations.filter(severity='critical').count()
        major_v = report.violations.filter(severity='major').count()
        if critical_v > 0 or report.compliance_percentage < 50:
            report.final_status = "Critical Intervention Required"
        elif major_v > 0 or report.compliance_percentage < 80:
            report.final_status = "Needs Corrective Action"
        else:
            report.final_status = "Satisfactory"

        # Save before hash to ensure DB has the latest
        report.status = 'finalized'
        report.save()


        # 2. Anomaly Creation triggers
        from decimal import Decimal
        project_claimed_fund = report.inspection.project.fund_utilized_claimed
        if report.fund_utilized_verified is not None:
            # Simple threshold check - if discrepancy > 0
            if project_claimed_fund != Decimal(str(report.fund_utilized_verified)):
                Anomaly.objects.create(
                    report=report,
                    type='fund_mismatch',
                    description=f"Claimed fund {project_claimed_fund} differs from verified fund {report.fund_utilized_verified}",
                    severity='high'
                )
                
        if report.ghost_beneficiaries_count > 0:
            Anomaly.objects.create(
                report=report,
                type='ghost_beneficiary',
                description=f"Found {report.ghost_beneficiaries_count} ghost beneficiaries",
                severity='high'
            )

        # AI Anomaly Creation trigger
        from .ai_utils import analyze_report_findings
        purpose_items = report.inspection.project.purposeitem_set.all()
        if purpose_items.exists() and report.findings:
            ai_results = analyze_report_findings(report.findings, purpose_items)
            for item in ai_results:
                if item.get('verdict') == 'mismatch':
                    Anomaly.objects.create(
                        report=report,
                        type='purpose_mismatch',
                        description=f"AI Flag on Purpose Item {item.get('purpose_item_id')}: {item.get('reason')}",
                        severity='medium'
                    )

        # Refresh from db to include anomalies
        report.refresh_from_db()

        # 3. Blockchain Hash-chain
        # Construct JSON for hashing
        report_data = {
            "id": report.id,
            "inspection_id": report.inspection.id,
            "findings": report.findings,
            "fund_utilized_verified": str(report.fund_utilized_verified) if report.fund_utilized_verified else None,
            "beneficiaries_claimed_count": report.beneficiaries_claimed_count,
            "beneficiaries_verified_count": report.beneficiaries_verified_count,
            "ghost_beneficiaries_count": report.ghost_beneficiaries_count,
            "anomalies": list(report.anomaly_set.values('type', 'description', 'severity'))
        }
        
        report_json_str = json.dumps(report_data, sort_keys=True)
        report_hash = hashlib.sha256(report_json_str.encode('utf-8')).hexdigest()

        # Get system-wide latest block
        last_block = ReportBlock.objects.order_by('-id').first()
        if last_block:
            previous_hash = last_block.block_hash
            new_index = last_block.index + 1
        else:
            previous_hash = "0"
            new_index = 1

        timestamp = timezone.now()
        timestamp_str = str(int(timestamp.timestamp()))
        
        block_content = f"{new_index}{report_hash}{previous_hash}{timestamp_str}"
        block_hash = hashlib.sha256(block_content.encode('utf-8')).hexdigest()

        ReportBlock.objects.create(
            report=report,
            index=new_index,
            report_hash=report_hash,
            previous_hash=previous_hash,
            block_hash=block_hash,
            timestamp=timestamp
        )

        from accounts.models import AuditLog
        AuditLog.log_event(user=request.user, action='report_finalized', description=f"Report #{report.id} finalized with blockchain hash {block_hash[:8]}...", model_name='InspectionReport', object_id=report.id, report=report, inspection=report.inspection, project=report.inspection.project)

        return Response({"status": "finalized", "report_hash": report_hash, "block_hash": block_hash})

    @action(detail=False, methods=['get'])
    def verify(self, request):
        # Admin or specific users only
        if request.user.role not in ['super_admin', 'official']:
            return Response({"error": "Unauthorized to perform chain verification."}, status=status.HTTP_403_FORBIDDEN)

        blocks = ReportBlock.objects.order_by('id')
        previous_hash = "0"

        for block in blocks:
            # Check previous hash link
            if block.previous_hash != previous_hash:
                return Response({
                    "verified": False, 
                    "broken_at_index": block.index, 
                    "reason": "Previous hash link mismatch"
                })
            
            # Recompute block hash
            timestamp_str = str(int(block.timestamp.timestamp()))
            block_content = f"{block.index}{block.report_hash}{block.previous_hash}{timestamp_str}"
            recomputed_hash = hashlib.sha256(block_content.encode('utf-8')).hexdigest()

            if block.block_hash != recomputed_hash:
                return Response({
                    "verified": False, 
                    "broken_at_index": block.index, 
                    "reason": "Block hash recalculation mismatch"
                })

            previous_hash = block.block_hash

        return Response({"verified": True, "broken_at_index": None})

from .models import NGOPeriodicReport
from .serializers import NGOPeriodicReportSerializer

class NGOPeriodicReportViewSet(viewsets.ModelViewSet):
    serializer_class = NGOPeriodicReportSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return NGOPeriodicReport.objects.none()

        if user.role == 'super_admin':
            return NGOPeriodicReport.objects.all()
        elif user.role in ['official', 'inspector']:
            return NGOPeriodicReport.objects.filter(project__division=user.division)
        elif user.role == 'ngo':
            return NGOPeriodicReport.objects.filter(project__ngo=user.ngo)
        return NGOPeriodicReport.objects.none()

from .serializers import AnomalySerializer

class AnomalyViewSet(viewsets.ReadOnlyModelViewSet):
    """Read anomalies and run a deterministic risk scan over finalized reports."""

    @action(detail=False, methods=['post'])
    def scan(self, request):
        if request.user.role not in ['official', 'super_admin']:
            return Response({'error': 'Only Officials or Super Admins can run anomaly scans.'}, status=403)

        if request.user.role == 'official':
            reports = InspectionReport.objects.filter(
                status='finalized',
                inspection__project__division=request.user.division
            ).select_related('inspection__project')
        else:
            reports = InspectionReport.objects.filter(status='finalized').select_related('inspection__project')

        created = 0
        updated = 0
        for report in reports:
            project = report.inspection.project

            if report.fund_utilized_verified is not None:
                claimed = project.fund_utilized_claimed or 0
                gap = abs(report.fund_utilized_verified - claimed)
                if gap > 0.01:
                    severity = 'high' if claimed and gap / claimed >= 0.20 else 'medium'
                    _, was_created = Anomaly.objects.update_or_create(
                        report=report, type='fund_mismatch',
                        defaults={
                            'description': f'Claimed utilization ₹{claimed} differs from verified utilization ₹{report.fund_utilized_verified}.',
                            'severity': severity
                        }
                    )
                    created += int(was_created)
                    updated += int(not was_created)

            if report.ghost_beneficiaries_count > 0:
                severity = 'high' if report.ghost_beneficiaries_count >= 5 else 'medium'
                _, was_created = Anomaly.objects.update_or_create(
                    report=report, type='ghost_beneficiary',
                    defaults={
                        'description': f'{report.ghost_beneficiaries_count} claimed beneficiaries were not verified.',
                        'severity': severity
                    }
                )
                created += int(was_created)
                updated += int(not was_created)

        return Response({
            'scanned_reports': reports.count(),
            'anomalies_created': created,
            'anomalies_updated': updated,
        })


    @action(detail=True, methods=['post'], url_path='gemini-analyze')
    def gemini_analyze(self, request, pk=None):
        if request.user.role not in ['official', 'super_admin']:
            return Response({'error': 'Only Officials or Super Admins can run Gemini anomaly analysis.'}, status=403)
        anomaly = self.get_object()
        report = anomaly.report
        from .ai_utils import analyze_full_report
        results = analyze_full_report(report)
        created = 0
        for item in results:
            if not isinstance(item, dict):
                continue
            anomaly_type = item.get('type')
            severity = item.get('severity')
            if anomaly_type not in dict(Anomaly.TYPE_CHOICES) or severity not in dict(Anomaly.SEVERITY_CHOICES):
                continue
            _, was_created = Anomaly.objects.update_or_create(
                report=report,
                type=anomaly_type,
                defaults={
                    'severity': severity,
                    'description': f"Gemini analysis: {item.get('reason', 'Evidence-based anomaly detected.')} "
                                   f"Supporting data: {item.get('data', '')}",
                }
            )
            created += int(was_created)
        return Response({
            'report_id': report.id,
            'engine': 'Gemini',
            'anomalies_created': created,
            'findings': results,
        })

    serializer_class = AnomalySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = Anomaly.objects.all().order_by('-flagged_at')
        if user.role == 'super_admin':
            return qs
        elif user.role in ['official', 'inspector']:
            return qs.filter(report__inspection__project__division=user.division)
        elif user.role == 'ngo':
            return qs.filter(report__inspection__project__ngo=user.ngo)
        return Anomaly.objects.none()

from .models import NSSVisitReport
from .serializers import NSSVisitReportSerializer
from rest_framework.parsers import MultiPartParser, FormParser

class NSSVisitReportViewSet(viewsets.ModelViewSet):
    serializer_class = NSSVisitReportSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):
        user = self.request.user
        qs = NSSVisitReport.objects.all().order_by('-created_at')
        if not user.is_authenticated:
            return NSSVisitReport.objects.none()
        
        if user.role == 'super_admin':
            return qs
        elif user.role == 'nss_volunteer':
            return qs.filter(nss_volunteer=user)
        elif user.role in ['official', 'inspector']:
            return qs.filter(project__division=user.division)
        return NSSVisitReport.objects.none()

    def perform_create(self, serializer):
        serializer.save(nss_volunteer=self.request.user)
