import uuid
from django.utils import timezone
from datetime import timedelta
from django.db.models import Q
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import Inspection, InspectionAssignment
from .serializers import InspectionSerializer
from accounts.models import User

class InspectionViewSet(viewsets.ModelViewSet):
    serializer_class = InspectionSerializer
    permission_classes = [IsAuthenticated]


    @action(detail=True, methods=['post'], url_path='initiate-vc')
    def initiate_vc(self, request, pk=None):
        from .models import RandomVerificationEvent
        import uuid
        
        inspection = self.get_object()
        
        if inspection.status != 'in_progress':
            return Response({'error': 'Inspection is not active.'}, status=400)
            
        assignment = inspection.inspectionassignment_set.first()
        if not assignment:
            return Response({'error': 'No inspector assigned.'}, status=400)
            
        # Check if already a pending/in_progress event exists
        existing = RandomVerificationEvent.objects.filter(inspection=inspection, status__in=['pending', 'in_progress']).first()
        if existing:
            return Response({'error': 'A video call is already pending or in progress for this inspection.'}, status=400)

        # Create event
        room_name = f"dosje-{inspection.id}-{uuid.uuid4().hex[:8]}"
        event = RandomVerificationEvent.objects.create(
            inspection=inspection,
            official=request.user,
            inspector=assignment.inspector,
            jitsi_room_name=room_name,
            status='pending'
        )
        
        from accounts.models import AuditLog
        AuditLog.log_event(user=request.user, action='direct_vc_initiated', description=f"Official explicitly initiated VC for Inspection #{inspection.id}.", model_name='Inspection', object_id=inspection.id, inspection=inspection, project=inspection.project)
        
        return Response({'message': 'VC initiated successfully.', 'event_id': event.id})

    @action(detail=False, methods=['post'], url_path='auto-schedule')
    def auto_schedule(self, request):
        import os, json
        from django.conf import settings
        from projects.models import Project
        from reports.models import Anomaly
        from datetime import timedelta
        
        # 1. Gather Context
        if not request.user.is_authenticated:
            return Response({"error": "Not authenticated"}, status=401)
            
        if request.user.role == 'super_admin':
            projects = Project.objects.filter(status='active')
        elif request.user.role in ['official', 'inspector']:
            projects = Project.objects.filter(status='active', division=request.user.division)
        else:
            return Response({"error": f"Role '{request.user.role}' is not authorized to auto-schedule."}, status=403)

        context_data = []
        for p in projects:
            # Skip projects that already have an active inspection
            from .models import Inspection
            if Inspection.objects.filter(project=p, status__in=['pending', 'in_progress']).exists():
                continue

            risk = 1 + Anomaly.objects.filter(report__inspection__project=p).count()
            last_insp = Inspection.objects.filter(project=p).order_by('-scheduled_time').first()
            last_date = last_insp.scheduled_time.strftime("%Y-%m-%d") if last_insp else "Never"
            
            context_data.append({
                "id": p.id,
                "title": p.title,
                "fund": float(p.fund_allocated),
                "risk_score": risk,
                "last_inspection": last_date
            })
            
        if not context_data:
            return Response({"error": "No active projects to schedule."}, status=400)

        # 2. Call AI
        api_key = os.environ.get('GEMINI_API_KEY')
        if not api_key:
            return Response({"error": "GEMINI_API_KEY not configured."}, status=500)
        
        today = timezone.now()
        prompt = f"""You are a risk-assessment AI for DoSJE. Review these active projects:
{json.dumps(context_data, indent=2)}

Today is {today.strftime("%Y-%m-%dT%H:%M:%SZ")}. Select exactly 2 projects that need urgent inspections (highest risk_score and older/no last_inspection).
Schedule them for RIGHT NOW or within the next 2-3 minutes from the current time.
Return ONLY valid JSON (no markdown block, no extra text) as a list of objects with "project_id" (int) and "scheduled_time" (ISO 8601 string, e.g. '{today.strftime("%Y-%m-%dT%H:%M:%SZ")}')."""
        
        import urllib.request
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        data = {"contents": [{"parts":[{"text": prompt}]}]}
        req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers={'Content-Type': 'application/json'})
        
        import time
        max_retries = 3
        schedule_plan = None
        last_error = None
        
        for attempt in range(max_retries):
            try:
                with urllib.request.urlopen(req) as response:
                    resp_data = json.loads(response.read().decode())
                    raw_text = resp_data['candidates'][0]['content']['parts'][0]['text'].strip()
                
                # Clean possible markdown block
                if raw_text.startswith("```json"):
                    raw_text = raw_text[7:]
                if raw_text.endswith("```"):
                    raw_text = raw_text[:-3]
                
                schedule_plan = json.loads(raw_text.strip())
                break # Success
            except urllib.error.HTTPError as e:
                last_error = f"HTTP Error {e.code}: {e.reason}"
                if e.code in [503, 429]: # Service Unavailable or Too Many Requests
                    time.sleep(2) # Wait and retry
                    continue
                else:
                    break # Don't retry other HTTP errors (like 400 Bad Request)
            except Exception as e:
                last_error = str(e)
                # Could be JSON decode error if AI returned bad JSON, retry might help with a different response
                time.sleep(1)
                continue
                
        if not schedule_plan:
            return Response({"error": f"AI scheduling failed after {max_retries} attempts. Last error: {last_error}"}, status=500)

        # 3. Apply Schedule
        created_inspections = []
        errors = []
        
        for item in schedule_plan:
            try:
                pid = item['project_id']
                # DEMO OVERRIDE: Set time to 1 minute from now to ensure immediate visibility in the active window
                st = (timezone.now() + timedelta(minutes=1)).isoformat()

                
                # Check if valid project
                p = projects.filter(id=pid).first()
                if not p:
                    errors.append(f"Project ID {pid} is invalid or unauthorized.")
                    continue
                
                # Check if already has a pending inspection
                if Inspection.objects.filter(project=p, status__in=['pending', 'in_progress']).exists():
                    errors.append(f"Project {p.title} already has an active inspection.")
                    continue
                
                serializer = self.get_serializer(data={"project": pid, "scheduled_time": st})
                if serializer.is_valid():
                    self.perform_create(serializer)
                    created_inspections.append({"project": p.title, "scheduled_time": st})
                else:
                    errors.append(f"Validation failed for project {p.title}: {serializer.errors}")
            except Exception as e:
                errors.append(f"Failed to process project {item.get('project_id')}: {str(e)}")

        return Response({
            "message": f"Scheduled {len(created_inspections)} inspections via AI.",
            "scheduled": created_inspections,
            "errors": errors
        })

    def create(self, request, *args, **kwargs):
        if request.user.role not in ('super_admin', 'official'):
            return Response({'detail': 'Only Super Admins or Officials can schedule inspections.'}, status=403)
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        if request.user.role not in ('super_admin', 'official'):
            return Response({'detail': 'Only Super Admins or Officials can edit inspections.'}, status=403)
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        if request.user.role not in ('super_admin', 'official'):
            return Response({'detail': 'Only Super Admins or Officials can edit inspections.'}, status=403)
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if request.user.role != 'super_admin':
            return Response({'detail': 'Only Super Admins can delete inspections.'}, status=403)
        return super().destroy(request, *args, **kwargs)

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return Inspection.objects.none()

        if user.role == 'super_admin':
            return Inspection.objects.all()
        elif user.role == 'official':
            return Inspection.objects.filter(project__division=user.division)
        elif user.role == 'inspector':
            return Inspection.objects.filter(inspectionassignment__inspector=user)
        elif user.role == 'ngo':
            return Inspection.objects.filter(project__ngo=user.ngo)
        return Inspection.objects.none()

    def perform_create(self, serializer):
        # Only an Official may schedule within their own division; Super Admin is unrestricted.
        project = serializer.validated_data.get('project')
        if self.request.user.role == 'official' and project.division_id != self.request.user.division_id:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Project is outside your division.')
        inspection = serializer.save(created_by=self.request.user)

        # Retrieve the project's division
        division = inspection.project.division

        # 1. Random assignment of an official in the division
        official = User.objects.filter(role='official', division=division).order_by('?').first()

        # 2. Assignment of an inspector using dynamic risk-based algorithm
        busy_inspector_ids = InspectionAssignment.objects.filter(
            inspection__status__in=['pending', 'in_progress']
        ).values_list('inspector_id', flat=True)
        
        available_inspectors = User.objects.filter(role='inspector', division=division).exclude(id__in=busy_inspector_ids)
        if not available_inspectors.exists():
            available_inspectors = User.objects.filter(role='inspector', division=division)
            
        inspectors = list(available_inspectors)
        inspector = None
        
        if inspectors:
            from reports.models import Anomaly
            import random
            
            ngo = inspection.project.ngo
            risk_score = 1 + Anomaly.objects.filter(report__inspection__project=inspection.project).count()
            
            weights = []
            reasoning = []
            
            for insp in inspectors:
                history_count = InspectionAssignment.objects.filter(inspector=insp, inspection__project__ngo=ngo).count()
                penalty = history_count * 20 * risk_score
                base_weight = 100
                weight = max(1, base_weight - penalty)
                noise = random.randint(0, 10)
                final_weight = weight + noise
                weights.append(final_weight)
                reasoning.append(f"{insp.username} (Hist:{history_count}, W:{final_weight})")
            
            inspector = random.choices(inspectors, weights=weights, k=1)[0]
            
            from accounts.models import AuditLog
            reasoning_str = f"Risk Score: {risk_score}. " + ", ".join(reasoning)
            AuditLog.log_event(
                user=self.request.user,
                action='inspector_assigned',
                description=f"Algorithm assigned {inspector.username}. {reasoning_str}",
                model_name='Inspection',
                object_id=inspection.id,
                inspection=inspection,
                project=inspection.project
            )

        # Generate Assignment and Jitsi Room if both were found
        if official and inspector:
            assignment = InspectionAssignment.objects.create(
                inspection=inspection,
                inspector=inspector,
                official=official,
                jitsi_room_name="" # Placeholder to get the ID first
            )
            assignment.jitsi_room_name = f"dosje-{assignment.id}-{uuid.uuid4().hex[:8]}"
            assignment.save()
        else:
            # In a real app, we might want to log this or raise an exception
            pass

    def perform_update(self, serializer):
        old_status = serializer.instance.status if serializer.instance.pk else 'pending'
        instance = serializer.save()
        if old_status != 'in_progress' and instance.status == 'in_progress':
            from accounts.models import AuditLog
            AuditLog.log_event(
                user=self.request.user,
                action='inspection_started',
                description=f"Inspection #{instance.id} started.",
                model_name='Inspection',
                object_id=instance.id,
                inspection=instance,
                project=instance.project
            )
    @action(detail=True, methods=['post'], url_path='location-ping')
    def location_ping(self, request, pk=None):
        inspection = self.get_object()

        # 1. Enforce inspector role and assignment
        if request.user.role != 'inspector':
            return Response({"error": "Only assigned inspectors can ping location."}, status=status.HTTP_403_FORBIDDEN)
        
        assignment = InspectionAssignment.objects.filter(inspection=inspection, inspector=request.user).first()
        if not assignment:
            return Response({"error": "You are not assigned to this inspection."}, status=status.HTTP_403_FORBIDDEN)

        # 2. Check time window (same as vc-room)
        now = timezone.now()
        start_window = inspection.scheduled_time - timedelta(minutes=5)
        end_window = inspection.scheduled_time + timedelta(minutes=60)
        if not (start_window <= now <= end_window):
            return Response({"error": "Inspection window is not active."}, status=status.HTTP_403_FORBIDDEN)

        # 3. Create Ping
        lat = request.data.get('lat')
        lng = request.data.get('lng')
        if lat is None or lng is None:
            return Response({"error": "lat and lng are required."}, status=status.HTTP_400_BAD_REQUEST)

        from .models import InspectorLocationPing
        ping = InspectorLocationPing.objects.create(
            inspection=inspection,
            inspector=request.user,
            lat=lat,
            lng=lng
        )
        from accounts.models import AuditLog
        AuditLog.log_event(user=request.user, action='gps_location_ping', description=f"GPS pinged at {lat}, {lng}.", model_name='InspectorLocationPing', object_id=ping.id, inspection=inspection, project=inspection.project)
        
        return Response({"status": "ping saved", "ping_id": ping.id}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'], url_path='live-location')
    def live_location(self, request, pk=None):
        inspection = self.get_object()

        # Anyone with access to the inspection can view live location (e.g. officials/super_admin)
        from .models import InspectorLocationPing
        latest_ping = InspectorLocationPing.objects.filter(inspection=inspection).order_by('-timestamp').first()

        if latest_ping:
            return Response({
                "lat": latest_ping.lat,
                "lng": latest_ping.lng,
                "timestamp": latest_ping.timestamp
            })
        return Response({"error": "No location data available."}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=['post'], url_path='accept')
    def accept(self, request, pk=None):
        inspection = self.get_object()
        user = request.user
        if user.role != 'inspector':
            return Response({'error': 'Only inspectors can accept assignments'}, status=400)
            
        from .models import InspectionAssignment
        assignment = InspectionAssignment.objects.filter(inspection=inspection, inspector=user).first()
        if not assignment:
            return Response({'error': 'You are not assigned to this inspection'}, status=400)
            
        assignment.is_accepted = True
        assignment.save()
        
        from accounts.models import AuditLog
        AuditLog.log_event(user=request.user, action='assignment_accepted', description="Inspector accepted the assignment.", model_name='Inspection', object_id=inspection.id, inspection=inspection, project=inspection.project)
        
        return Response({'message': 'Assignment accepted successfully.'})

    @action(detail=True, methods=['post'], url_path='start')
    def start(self, request, pk=None):
        inspection = self.get_object()
        user = request.user
        if user.role != 'inspector':
            return Response({'error': 'Only inspectors can start inspections'}, status=403)
            
        from .models import InspectionAssignment
        assignment = InspectionAssignment.objects.filter(inspection=inspection, inspector=user).first()
        if not assignment or not assignment.is_accepted:
            return Response({'error': 'You must accept the assignment first'}, status=403)
            
        if inspection.status != 'in_progress':
            inspection.status = 'in_progress'
            inspection.save()
            from accounts.models import AuditLog
            AuditLog.log_event(user=request.user, action='inspection_started', description="Inspection Started. Eligible for Random Verification.", model_name='Inspection', object_id=inspection.id, inspection=inspection, project=inspection.project)
            
        return Response({'message': 'Inspection started.'})

    @action(detail=True, methods=['get'], url_path='vc-room')
    def vc_room(self, request, pk=None):
        inspection = self.get_object()
        assignment = inspection.inspectionassignment_set.select_related('inspector', 'official').first()
        if not assignment or not assignment.jitsi_room_name:
            return Response({'detail': 'No inspection video room is available.'}, status=404)

        allowed = (
            request.user.role == 'super_admin'
            or (request.user.role == 'official' and assignment.official_id == request.user.id)
            or (request.user.role == 'inspector' and assignment.inspector_id == request.user.id)
            or (request.user.role == 'ngo' and inspection.project.ngo_id == request.user.ngo_id)
        )
        if not allowed:
            return Response({'detail': 'You do not have access to this inspection video room.'}, status=403)

        return Response({
            'jitsi_room_name': assignment.jitsi_room_name,
            'inspection_id': inspection.id,
            'project_name': inspection.project.title,
        })

    @action(detail=False, methods=['get'], url_path='missed-calls')
    def missed_calls(self, request):
        if request.user.role not in ('official', 'super_admin'):
            return Response({'detail': 'Only Officials or Super Admins can view missed calls.'}, status=403)
        from .models import RandomVerificationEvent
        qs = RandomVerificationEvent.objects.filter(status__in=['no_response', 'missed']).select_related('inspection__project', 'inspector')
        if request.user.role == 'official':
            qs = qs.filter(official=request.user)
        return Response([{
            'id': event.id,
            'created_at': event.created_at,
            'inspector_name': event.inspector.get_full_name() or event.inspector.username,
            'project_name': event.inspection.project.title,
            'status': event.status,
            'attempt_number': event.attempt_number,
        } for event in qs.order_by('-created_at')])

    @action(detail=False, methods=['post'], url_path='pick-random-active')
    def pick_random_active(self, request):
        user = request.user
        if user.role != 'official':
            return Response({'error': 'Only officials can pick active inspections'}, status=403)
            
        from .models import InspectionAssignment, RandomVerificationEvent
        from projects.models import Project
        import random
        from django.utils import timezone
        
        active_inspections = self.get_queryset().filter(
            status='in_progress'
        ).exclude(
            verification_events__status__in=['pending', 'in_progress']
        )
        
        if not active_inspections.exists():
            return Response({'error': 'No eligible active inspections currently available.'}, status=404)
            
        selected_inspection = random.choice(list(active_inspections))
        
        assignment = InspectionAssignment.objects.filter(inspection=selected_inspection).first()
        if not assignment:
            return Response({'error': 'Selected inspection has no inspector assigned.'}, status=500)
            
        import uuid
        room_name = f"dosje-vc-{selected_inspection.id}-{uuid.uuid4().hex[:8]}"
        
        event = RandomVerificationEvent.objects.create(
            inspection=selected_inspection,
            inspector=assignment.inspector,
            official=user,
            status='pending',
            jitsi_room_name=room_name,
            selected_at=timezone.now(),
            vc_room_created_at=timezone.now(),
            response_deadline=timezone.now() + timezone.timedelta(seconds=20)
        )
        
        from accounts.models import AuditLog
        AuditLog.log_event(user=request.user, action='random_verification_initiated', description=f"Randomly selected Inspection {selected_inspection.id}. VC request sent.", model_name='Inspection', object_id=selected_inspection.id, inspection=selected_inspection, project=selected_inspection.project)
        
        return Response({
            'message': 'Random verification initiated.',
            'event_id': event.id,
            'inspection_id': selected_inspection.id,
            'jitsi_room_name': room_name
        })

    @action(detail=False, methods=['get'], url_path='check-verification-status')
    def check_verification_status(self, request):
        if request.user.role != 'official':
            return Response({'error': 'Only officials can check verification status'}, status=403)
            
        from .models import RandomVerificationEvent
        event = RandomVerificationEvent.objects.filter(official=request.user).order_by('-created_at').first()
        if not event:
            return Response({'status': 'none'})
            
        from django.utils import timezone
        if event.status == 'pending' and event.response_deadline and timezone.now() > event.response_deadline:
            if event.attempt_number == 1:
                event.status = 'no_response'
                event.save()
                from accounts.models import AuditLog
                AuditLog.log_event(user=request.user, action='vc_attempt_missed', description=f"Inspector did not respond to VC attempt {event.attempt_number}.", model_name='Inspection', object_id=event.inspection.id, inspection=event.inspection, project=event.inspection.project)
            else:
                event.status = 'missed'
                event.save()
                from accounts.models import AuditLog
                AuditLog.log_event(user=request.user, action='vc_missed', description=f"Inspector missed final VC attempt.", model_name='Inspection', object_id=event.inspection.id, inspection=event.inspection, project=event.inspection.project)

        from .serializers import InspectionSerializer
        return Response({
            'status': event.status,
            'event_id': event.id,
            'attempt_number': event.attempt_number,
            'jitsi_room_name': event.jitsi_room_name,
            'inspection': InspectionSerializer(event.inspection).data,
            'inspector_name': event.inspector.get_full_name() or event.inspector.username,
            'project_name': event.inspection.project.title,
        })

    @action(detail=True, methods=['post'], url_path='retry-verification')
    def retry_verification(self, request, pk=None):
        from .models import RandomVerificationEvent
        from django.utils import timezone
        
        event = RandomVerificationEvent.objects.filter(id=pk, official=request.user).first()
        if not event or event.status != 'no_response':
            return Response({'error': 'Cannot retry this verification.'}, status=400)
            
        event.attempt_number += 1
        event.status = 'pending'
        event.response_deadline = timezone.now() + timezone.timedelta(seconds=20)
        event.save()
        
        from accounts.models import AuditLog
        AuditLog.log_event(user=request.user, action='vc_retry_initiated', description=f"Official initiated retry {event.attempt_number} for VC.", model_name='Inspection', object_id=event.inspection.id, inspection=event.inspection, project=event.inspection.project)
        return Response({'message': 'Retry initiated.'})

    @action(detail=False, methods=['get'], url_path='vc-status')
    def vc_status(self, request):
        if request.user.role != 'inspector':
            return Response({'status': 'none'})
            
        from .models import RandomVerificationEvent
        event = RandomVerificationEvent.objects.filter(inspector=request.user, status='pending').order_by('-created_at').first()
        if not event:
            return Response({'status': 'none'})
            
        return Response({
            'status': 'pending',
            'event_id': event.id,
            'inspection_id': event.inspection.id,
            'jitsi_room_name': event.jitsi_room_name,
            'official_name': event.official.get_full_name() or event.official.username
        })

    @action(detail=True, methods=['post'], url_path='respond-vc')
    def respond_vc(self, request, pk=None):
        from .models import RandomVerificationEvent
        from django.utils import timezone
        from django.db.models import Q
        
        event = RandomVerificationEvent.objects.filter(id=pk, status='pending').filter(Q(inspector=request.user) | Q(official=request.user)).first()
        if not event:
            return Response({'error': 'No pending VC request found.'}, status=400)
            
        response_type = request.data.get('response')
        from accounts.models import AuditLog
        
        if response_type == 'accept':
            event.status = 'in_progress'
            event.started_at = timezone.now()
            event.save()
            AuditLog.log_event(user=request.user, action='vc_accepted', description="Inspector accepted VC.", model_name='Inspection', object_id=event.inspection.id, inspection=event.inspection, project=event.inspection.project)
            return Response({'message': 'VC Accepted.', 'jitsi_room_name': event.jitsi_room_name})
            
        elif response_type == 'decline':
            event.status = 'declined'
            event.ended_at = timezone.now()
            event.save()
            AuditLog.log_event(user=request.user, action='vc_declined', description="Inspector declined VC.", model_name='Inspection', object_id=event.inspection.id, inspection=event.inspection, project=event.inspection.project)
            return Response({'message': 'VC Declined.'})
            
        return Response({'error': 'Invalid response type'}, status=400)

    @action(detail=True, methods=['post'], url_path='end-vc')
    def end_vc(self, request, pk=None):
        from .models import RandomVerificationEvent
        from django.utils import timezone
        from django.db.models import Q
        
        event = RandomVerificationEvent.objects.filter(id=pk, status='in_progress').filter(Q(inspector=request.user) | Q(official=request.user)).first()
        if not event:
            return Response({'error': 'No active VC found to end.'}, status=400)
            
        event.status = 'completed'
        event.ended_at = timezone.now()
        event.save()
        
        from accounts.models import AuditLog
        AuditLog.log_event(user=request.user, action='vc_completed', description=f"VC completed.", model_name='Inspection', object_id=event.inspection.id, inspection=event.inspection, project=event.inspection.project)
        return Response({'message': 'VC ended successfully.'})



from .models import DutySwapRequest
from .serializers import DutySwapRequestSerializer


class DutySwapRequestViewSet(viewsets.ModelViewSet):
    serializer_class = DutySwapRequestSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'super_admin':
            return DutySwapRequest.objects.all()
        elif user.role == 'inspector':
            return DutySwapRequest.objects.filter(original_inspector=user)
        elif user.role == 'official':
            return DutySwapRequest.objects.filter(original_inspector__division=user.division)
        return DutySwapRequest.objects.none()

    def perform_create(self, serializer):
        if self.request.user.role != 'inspector':
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Only inspectors can create duty swap requests.')
        serializer.save(original_inspector=self.request.user)

    def perform_update(self, serializer):
        if self.request.user.role not in ['official', 'super_admin']:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Only an Official or Super Admin can approve or reject duty swaps.')
        instance = serializer.save()
        # If official approves the swap, update the inspection assignment
        if instance.status == 'approved':
            assignment = InspectionAssignment.objects.filter(inspection=instance.inspection, inspector=instance.original_inspector).first()
            if assignment:
                assignment.inspector = instance.proposed_inspector
                assignment.save()

from .models import DirectCall
from .serializers import DirectCallSerializer

class DirectCallViewSet(viewsets.ModelViewSet):
    serializer_class = DirectCallSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'official':
            return DirectCall.objects.filter(official=user)
        elif user.role == 'ngo':
            return DirectCall.objects.filter(ngo=user)
        return DirectCall.objects.none()

    def perform_create(self, serializer):
        if self.request.user.role != 'official':
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Only Officials can initiate NGO calls.')
        ngo = serializer.validated_data.get('ngo')
        if not ngo or ngo.role != 'ngo' or not ngo.ngo or ngo.ngo.division_id != self.request.user.division_id:
            raise PermissionDenied('NGO is outside your division.')
        import uuid
        room_name = f"dosje-direct-{uuid.uuid4().hex[:16]}"
        serializer.save(official=self.request.user, room_name=room_name, status='ringing')

    @action(detail=True, methods=['post'], url_path='end')
    def end_call(self, request, pk=None):
        call = self.get_object()
        call.status = 'ended'
        call.save(update_fields=['status'])
        return Response({"status": "Call ended"})

from .models import CallLog
from .serializers import CallLogSerializer

class CallLogViewSet(viewsets.ModelViewSet):
    serializer_class = CallLogSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        # User can see calls they made or received
        return CallLog.objects.filter(Q(caller=user) | Q(callee=user)).order_by('-timestamp')

    def perform_create(self, serializer):
        serializer.save(caller=self.request.user)
