from django.db import models
from django.contrib.auth.models import AbstractUser

class Division(models.Model):
    name = models.CharField(max_length=255)

    def __str__(self):
        return self.name

class NGO(models.Model):
    name = models.CharField(max_length=255)
    registration_number = models.CharField(max_length=100)
    division = models.ForeignKey(Division, on_delete=models.CASCADE)

    def __str__(self):
        return self.name

class User(AbstractUser):
    ROLE_CHOICES = (
        ('super_admin', 'Super Admin'),
        ('official', 'Official'),
        ('inspector', 'Inspector'),
        ('ngo', 'NGO'),
        ('nss_volunteer', 'NSS Volunteer'),
        ('citizen', 'Citizen'),
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    division = models.ForeignKey(Division, on_delete=models.SET_NULL, null=True, blank=True)
    ngo = models.ForeignKey(NGO, on_delete=models.SET_NULL, null=True, blank=True)
    phone = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"

class InspectorActivityLog(models.Model):
    inspector = models.ForeignKey(User, on_delete=models.CASCADE, limit_choices_to={'role': 'inspector'})
    login_time = models.DateTimeField(auto_now_add=True)
    logout_time = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.inspector.username} - Active: {self.is_active}"

class LeaveApplication(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    )
    inspector = models.ForeignKey(User, on_delete=models.CASCADE, limit_choices_to={'role': 'inspector'})
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField()
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Leave: {self.inspector.username} ({self.start_date} to {self.end_date})"

from django.core.exceptions import PermissionDenied

import hashlib

class AuditLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=100)
    model_name = models.CharField(max_length=100, blank=True, null=True)
    object_id = models.IntegerField(default=0)
    field_name = models.CharField(max_length=100, blank=True, null=True)
    old_value = models.TextField(blank=True, null=True)
    new_value = models.TextField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    
    project = models.ForeignKey('projects.Project', on_delete=models.SET_NULL, null=True, blank=True)
    inspection = models.ForeignKey('inspections.Inspection', on_delete=models.SET_NULL, null=True, blank=True)
    report = models.ForeignKey('reports.InspectionReport', on_delete=models.SET_NULL, null=True, blank=True)
    
    previous_hash = models.CharField(max_length=64, default="0")
    current_hash = models.CharField(max_length=64, default="0")
    timestamp = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.pk is None:
            last_log = AuditLog.objects.order_by('-id').first()
            self.previous_hash = last_log.current_hash if last_log else "0"
            
            data_str = f"{self.user_id}{self.action}{self.model_name}{self.object_id}{self.field_name}{self.old_value}{self.new_value}{self.description}{self.project_id}{self.inspection_id}{self.report_id}{self.previous_hash}"
            self.current_hash = hashlib.sha256(data_str.encode('utf-8')).hexdigest()
            super().save(*args, **kwargs)
        else:
            raise PermissionDenied("AuditLog entries are immutable and cannot be updated.")

    def delete(self, *args, **kwargs):
        raise PermissionDenied("AuditLog entries are immutable and cannot be deleted.")

    def __str__(self):
        return f"{self.timestamp} - {self.action} on {self.model_name} {self.object_id}"

    @classmethod
    def log_event(cls, user, action, description='', model_name='', object_id=0, project=None, inspection=None, report=None, field_name='', old_value='', new_value=''):
        return cls.objects.create(
            user=user,
            action=action,
            description=description,
            model_name=model_name,
            object_id=object_id,
            project=project,
            inspection=inspection,
            report=report,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value
        )
