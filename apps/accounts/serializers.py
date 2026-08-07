from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth.password_validation import validate_password
from .models import Organization, Profile


class OrganizationSerializer(serializers.ModelSerializer):
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = ['id', 'name', 'slug', 'plan', 'country', 'currency',
                  'logo_url', 'settings', 'is_active', 'member_count', 'created_at']
        read_only_fields = ['id', 'created_at', 'member_count']

    def get_member_count(self, obj):
        return obj.members.filter(is_active=True).count()


class ProfileSerializer(serializers.ModelSerializer):
    organization_name = serializers.CharField(source='organization.name', read_only=True)

    class Meta:
        model = Profile
        fields = ['id', 'email', 'full_name', 'role', 'avatar_url', 'phone',
                  'organization', 'organization_name', 'is_active', 'preferences',
                  'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at', 'organization_name']


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])
    organization_name = serializers.CharField(write_only=True)

    class Meta:
        model = Profile
        fields = ['email', 'full_name', 'password', 'phone', 'organization_name']

    def validate_email(self, value):
        if Profile.objects.filter(email=value).exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return value

    def create(self, validated_data):
        org_name = validated_data.pop('organization_name')
        import re
        slug = re.sub(r'[^a-z0-9]+', '-', org_name.lower()).strip('-')
        base_slug = slug
        counter = 1
        while Organization.objects.filter(slug=slug).exists():
            slug = f'{base_slug}-{counter}'
            counter += 1
        org = Organization.objects.create(name=org_name, slug=slug)
        user = Profile.objects.create_user(
            organization=org,
            role='director',
            **validated_data,
        )
        return user


class CustomTokenSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['email'] = user.email
        token['role'] = user.role
        token['org_id'] = str(user.organization_id) if user.organization_id else None
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        data['user'] = ProfileSerializer(self.user).data
        return data


class InviteUserSerializer(serializers.Serializer):
    email = serializers.EmailField()
    full_name = serializers.CharField(max_length=255)
    role = serializers.ChoiceField(choices=Profile.ROLE_CHOICES)
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True)


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField()
    new_password = serializers.CharField(validators=[validate_password])
