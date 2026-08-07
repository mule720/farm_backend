import uuid
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.utils import timezone
from .managers import ProfileManager


class Organization(models.Model):
    PLAN_CHOICES = [('free', 'Free'), ('pro', 'Pro'), ('enterprise', 'Enterprise')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, max_length=100)
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default='free')
    country = models.CharField(max_length=100, blank=True)
    currency = models.CharField(max_length=10, default='ZMW')
    logo_url = models.URLField(blank=True)
    settings = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'organizations'
        ordering = ['name']

    def __str__(self):
        return self.name


class Profile(AbstractBaseUser, PermissionsMixin):
    ROLE_CHOICES = [
        ('director', 'Director / Admin'),
        ('production_manager', 'Production Manager'),
        ('finance_manager', 'Finance Manager'),
        ('sales_manager', 'Sales Manager'),
        ('supervisor', 'Supervisor'),
        ('farmhand', 'Farmhand'),
        ('vet_officer', 'Veterinary Officer'),
        ('driver', 'Driver'),
        ('saas_admin', 'SaaS Platform Admin'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='members'
    )
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=255)
    role = models.CharField(max_length=30, choices=ROLE_CHOICES, default='farmhand')
    avatar_url = models.URLField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    preferences = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_login = models.DateTimeField(null=True, blank=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['full_name']

    objects = ProfileManager()

    class Meta:
        db_table = 'profiles'
        ordering = ['full_name']

    def __str__(self):
        return f'{self.full_name} ({self.email})'

    @property
    def is_platform_admin(self):
        return self.role == 'saas_admin'

    def has_role(self, *roles):
        return self.role in roles or self.role == 'saas_admin'
