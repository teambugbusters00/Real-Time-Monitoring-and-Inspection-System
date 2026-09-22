from rest_framework import serializers
from .models import Project, Beneficiary, PurposeItem, CCTVCamera, Complaint

class CCTVCameraSerializer(serializers.ModelSerializer):
    class Meta:
        model = CCTVCamera
        fields = '__all__'

class BeneficiarySerializer(serializers.ModelSerializer):
    duplicate_of_name = serializers.CharField(source='duplicate_of.name', read_only=True)
    duplicate_of_project = serializers.CharField(source='duplicate_of.project.title', read_only=True)
    duplicate_of_unique_id = serializers.CharField(source='duplicate_of.unique_id', read_only=True)

    class Meta:
        model = Beneficiary
        fields = '__all__'
        read_only_fields = ('unique_id', 'duplicate_status', 'duplicate_of')

class ComplaintSerializer(serializers.ModelSerializer):
    beneficiary_name = serializers.CharField(source='beneficiary.name', read_only=True)
    ngo_name = serializers.CharField(source='ngo.name', read_only=True)
    project_name = serializers.CharField(source='project.title', read_only=True)

    class Meta:
        model = Complaint
        fields = '__all__'
        read_only_fields = ('submitted_by',)

class PurposeItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurposeItem
        fields = '__all__'

from .models import Project, Beneficiary, PurposeItem, CCTVCamera, Complaint, ProjectAsset

class ProjectAssetSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectAsset
        fields = '__all__'

class ProjectSerializer(serializers.ModelSerializer):
    beneficiaries_count = serializers.SerializerMethodField()
    purpose_items_count = serializers.SerializerMethodField()
    fund_utilized_verified = serializers.SerializerMethodField()
    cameras = CCTVCameraSerializer(many=True, read_only=True)
    assets = ProjectAssetSerializer(many=True, read_only=True)
    risk_score = serializers.SerializerMethodField()
    risk_status = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = '__all__'
        read_only_fields = ('fund_utilized_claimed',)

    def get_beneficiaries_count(self, obj):
        return obj.beneficiary_set.count()
        
    def get_purpose_items_count(self, obj):
        return obj.purposeitem_set.count()

    def _get_latest_finalized_report(self, obj):
        if not hasattr(obj, '_latest_finalized_report'):
            from reports.models import InspectionReport
            obj._latest_finalized_report = InspectionReport.objects.filter(
                inspection__project=obj,
                status='finalized'
            ).order_by('-submitted_at').first()
        return obj._latest_finalized_report

    def get_fund_utilized_verified(self, obj):
        latest_report = self._get_latest_finalized_report(obj)
        if latest_report:
            return latest_report.fund_utilized_verified
        return None

    def get_risk_score(self, obj):
        report = self._get_latest_finalized_report(obj)
        if not report:
            return 0
        
        score = 0
        for anomaly in report.anomaly_set.all():
            if anomaly.severity == 'high':
                score += 30
            elif anomaly.severity == 'medium':
                score += 15
            elif anomaly.severity == 'low':
                score += 5
        
        return min(score, 100)

    def get_risk_status(self, obj):
        score = self.get_risk_score(obj)
        if score <= 40:
            return "Normal"
        elif score <= 70:
            return "Needs Review"
        else:
            return "High Risk"

from .models import FundDisbursement

class FundDisbursementSerializer(serializers.ModelSerializer):
    beneficiary_name = serializers.CharField(source='beneficiary.name', read_only=True)
    beneficiary_pan = serializers.CharField(source='beneficiary.pan_number', read_only=True)
    
    class Meta:
        model = FundDisbursement
        fields = ['id', 'project', 'beneficiary', 'beneficiary_name', 'beneficiary_pan', 'amount', 'transaction_reference_number', 'receipt', 'disbursed_date']
        read_only_fields = ['id', 'disbursed_date', 'beneficiary_name', 'beneficiary_pan']
