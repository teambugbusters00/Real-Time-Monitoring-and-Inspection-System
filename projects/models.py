from django.db import models
from accounts.models import NGO, Division

class Project(models.Model):
    STATUS_CHOICES = (
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('flagged', 'Flagged'),
    )
    SCHEME_CHOICES = (
        ('AVYAY', 'Atal Vayo Abhyuday Yojana (AVYAY)'),
        ('NAPDDR', 'National Action Plan for Drug Demand Reduction (NAPDDR)'),
        ('SMILE', 'SMILE - Transgender/Beggary Rehabilitation'),
        ('ELDERLINE', 'Elder Helpline (Elderline)'),
        ('SWAVALAMBAN', 'Swavalamban Yojana'),
        ('DDRS', 'Deen Dayal Disabled Rehabilitation Scheme (DDRS)'),
        ('NATIONAL_TRUST', 'National Trust Schemes'),
        ('VAYOSHRI', 'Rashtriya Vayoshri Yojana'),
        ('SAGE', 'Seniorcare Ageing Growth Engine (SAGE)'),
        ('PM_AJAY', 'PM-AJAY (Pradhan Mantri Anusuchit Jaati Abhyuday Yojana)'),
        ('OTHER', 'Other / General'),
    )
    ngo = models.ForeignKey(NGO, on_delete=models.CASCADE)
    division = models.ForeignKey(Division, on_delete=models.CASCADE)
    scheme_name = models.CharField(max_length=50, choices=SCHEME_CHOICES, default='OTHER')
    title = models.CharField(max_length=255)
    description = models.TextField()
    fund_allocated = models.DecimalField(max_digits=12, decimal_places=2)
    fund_utilized_claimed = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

class Beneficiary(models.Model):
    DUPLICATE_STATUS_CHOICES = (
        ('none', 'No Duplicate'),
        ('potential', 'Potential Duplicate'),
        ('confirmed', 'Confirmed Duplicate'),
        ('dismissed', 'Dismissed'),
    )
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    unique_id = models.CharField(max_length=20, unique=True, null=True, blank=True)
    name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    pan_number = models.CharField(max_length=10, unique=True, null=True, blank=True)
    address = models.TextField(blank=True, null=True)
    details = models.TextField()
    claimed = models.BooleanField(default=True)
    duplicate_status = models.CharField(max_length=20, choices=DUPLICATE_STATUS_CHOICES, default='none')
    duplicate_of = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True)

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        
        updates = []
        if not self.unique_id:
            self.unique_id = f"BEN-{self.pk:06d}"
            updates.append('unique_id')
            
        if is_new:
            duplicates = Beneficiary.objects.filter(
                project__ngo=self.project.ngo,
                name__iexact=self.name
            ).exclude(pk=self.pk)
            
            if duplicates.exists():
                self.duplicate_status = 'potential'
                self.duplicate_of = duplicates.first()
                updates.extend(['duplicate_status', 'duplicate_of'])
                
        if updates:
            self.save(update_fields=updates)

    def __str__(self):
        return self.name

class Complaint(models.Model):
    STATUS_CHOICES = (
        ('open', 'Open'),
        ('investigating', 'Investigating'),
        ('resolved', 'Resolved'),
    )
    ngo = models.ForeignKey(NGO, on_delete=models.CASCADE)
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True)
    beneficiary = models.ForeignKey(Beneficiary, on_delete=models.SET_NULL, null=True, blank=True)
    submitted_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='complaints_submitted')
    subject = models.CharField(max_length=255)
    description = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Complaint: {self.subject} ({self.ngo.name})"

class PurposeItem(models.Model):
    CLAIMED_STATUS_CHOICES = (
        ('done', 'Done'),
        ('partial', 'Partial'),
        ('not_done', 'Not Done'),
    )
    ACTUAL_STATUS_CHOICES = (
        ('done', 'Done'),
        ('partial', 'Partial'),
        ('not_done', 'Not Done'),
        ('unverified', 'Unverified'),
    )
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    description = models.TextField()
    claimed_status = models.CharField(max_length=20, choices=CLAIMED_STATUS_CHOICES)
    actual_status = models.CharField(max_length=20, choices=ACTUAL_STATUS_CHOICES, default='unverified')

    def __str__(self):
        return self.description

class CCTVCamera(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='cameras')
    name = models.CharField(max_length=255)
    stream_url = models.URLField(max_length=500)
    is_working = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.project.title})"

class FundDisbursement(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='disbursements')
    beneficiary = models.ForeignKey(Beneficiary, on_delete=models.CASCADE, related_name='disbursements')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    transaction_reference_number = models.CharField(max_length=100)
    receipt = models.FileField(upload_to='disbursement_receipts/', null=True, blank=True)
    disbursed_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"₹{self.amount} to {self.beneficiary.name} (Ref: {self.transaction_reference_number})"

class ProjectAsset(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='assets')
    asset_name = models.CharField(max_length=255)
    approved_quantity = models.IntegerField(default=1)

    def __str__(self):
        return f"{self.approved_quantity}x {self.asset_name} ({self.project.title})"
