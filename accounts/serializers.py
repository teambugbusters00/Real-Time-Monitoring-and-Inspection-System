from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .models import User, Division, NGO, InspectorActivityLog, AuditLog

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        # Common login: users sign in with their registered email and password.
        # Keep username login compatible for existing accounts/API clients.
        identifier = (attrs.get('username') or '').strip()
        if '@' in identifier:
            try:
                user = User.objects.get(email__iexact=identifier)
            except User.DoesNotExist:
                pass
            else:
                attrs['username'] = user.username

        data = super().validate(attrs)

        # Add extra responses here
        data['role'] = self.user.role
        if self.user.division:
            data['division_id'] = self.user.division.id
        else:
            data['division_id'] = None
            
        if self.user.ngo:
            data['ngo_id'] = self.user.ngo.id
        else:
            data['ngo_id'] = None

        return data

class AuditLogSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    role = serializers.CharField(source='user.role', read_only=True)

    class Meta:
        model = AuditLog
        fields = '__all__'

class DivisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Division
        fields = '__all__'

class NGOSerializer(serializers.ModelSerializer):
    class Meta:
        model = NGO
        fields = '__all__'

class UserSerializer(serializers.ModelSerializer):
    division_name = serializers.CharField(source='division.name', read_only=True)
    ngo_name = serializers.CharField(source='ngo.name', read_only=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'role', 'first_name', 'last_name', 'email', 'phone', 'division', 'division_name', 'ngo', 'ngo_name']

class InspectorActivityLogSerializer(serializers.ModelSerializer):
    inspector_name = serializers.CharField(source='inspector.get_full_name', read_only=True)
    inspector_username = serializers.CharField(source='inspector.username', read_only=True)

    class Meta:
        model = InspectorActivityLog
        fields = '__all__'

from .models import LeaveApplication

class LeaveApplicationSerializer(serializers.ModelSerializer):
    inspector_name = serializers.CharField(source='inspector.get_full_name', read_only=True)
    inspector_username = serializers.CharField(source='inspector.username', read_only=True)

    class Meta:
        model = LeaveApplication
        fields = '__all__'
