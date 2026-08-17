import graphene
import graphql_jwt
from graphene_django import DjangoObjectType
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from .models import Organization, Profile


class OrganizationType(DjangoObjectType):
    member_count = graphene.Int()

    class Meta:
        model = Organization
        fields = ['id', 'name', 'slug', 'plan', 'country', 'currency',
                  'logo_url', 'is_active', 'created_at', 'updated_at']

    def resolve_member_count(self, info):
        return self.members.filter(is_active=True).count()


class ProfileType(DjangoObjectType):
    organization_name = graphene.String()
    is_platform_admin = graphene.Boolean()

    class Meta:
        model = Profile
        fields = ['id', 'email', 'full_name', 'role', 'avatar_url', 'phone',
                  'organization', 'is_active', 'preferences', 'created_at', 'updated_at']
        convert_choices_to_enum = False

    def resolve_organization_name(self, info):
        return self.organization.name if self.organization else None

    def resolve_is_platform_admin(self, info):
        return self.role == 'saas_admin'


# ─── Inputs ──────────────────────────────────────────────────────────────────

class RegisterInput(graphene.InputObjectType):
    email = graphene.String()          # optional — auto-generated from phone if omitted
    full_name = graphene.String(required=True)
    password = graphene.String(required=True)
    organization_name = graphene.String(required=True)
    role = graphene.String()
    phone = graphene.String(required=True)  # mandatory


class UpdateProfileInput(graphene.InputObjectType):
    full_name = graphene.String()
    phone = graphene.String()
    avatar_url = graphene.String()
    preferences = graphene.JSONString()


class UpdateOrganizationInput(graphene.InputObjectType):
    name = graphene.String()
    country = graphene.String()
    currency = graphene.String()
    logo_url = graphene.String()
    settings = graphene.JSONString()


class InviteUserInput(graphene.InputObjectType):
    email = graphene.String()           # optional — auto-generated from phone if omitted
    full_name = graphene.String(required=True)
    role = graphene.String(required=True)
    phone = graphene.String(required=True)  # mandatory
    password = graphene.String()  # optional — director can set it; auto-generated if omitted


# ─── Auth payload ─────────────────────────────────────────────────────────────

class AuthPayload(graphene.ObjectType):
    token = graphene.String()
    refresh_token = graphene.String()
    user = graphene.Field(ProfileType)


# ─── Queries ──────────────────────────────────────────────────────────────────

class AccountQuery(graphene.ObjectType):
    me = graphene.Field(ProfileType)
    organization = graphene.Field(OrganizationType)
    members = graphene.List(ProfileType, role=graphene.String(), is_active=graphene.Boolean())
    member = graphene.Field(ProfileType, id=graphene.ID(required=True))
    all_organizations = graphene.List(OrganizationType)

    def resolve_me(self, info):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        return user

    def resolve_organization(self, info):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        return user.organization

    def resolve_members(self, info, role=None, is_active=None):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        qs = Profile.objects.filter(organization=user.organization)
        if role:
            qs = qs.filter(role=role)
        if is_active is not None:
            qs = qs.filter(is_active=is_active)
        return qs

    def resolve_member(self, info, id):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        return Profile.objects.get(id=id, organization=user.organization)

    def resolve_all_organizations(self, info):
        user = info.context.user
        if not user.is_authenticated or user.role != 'saas_admin':
            raise Exception('Permission denied')
        return Organization.objects.all()


# ─── Mutations ────────────────────────────────────────────────────────────────

class Register(graphene.Mutation):
    class Arguments:
        input = RegisterInput(required=True)

    Output = AuthPayload

    def mutate(self, info, input):
        import re
        from graphql_jwt.shortcuts import get_token
        from graphql_jwt.refresh_token.shortcuts import create_refresh_token

        # Phone is mandatory
        phone = (input.get('phone') or '').strip()
        if not phone:
            raise Exception('Phone number is required.')

        # Email is optional — auto-generate from phone if not provided
        email = (input.get('email') or '').strip()
        if not email:
            clean_phone = re.sub(r'[^0-9]', '', phone)
            email = f'{clean_phone}@agrinuxes.local'

        if Profile.objects.filter(email=email).exists():
            raise Exception('A user with this email already exists.')
        if Profile.objects.filter(phone=phone).exists():
            raise Exception('A user with this phone number already exists.')

        selected_role = (input.role or 'director').strip()
        allowed_roles = {choice[0] for choice in Profile.ROLE_CHOICES}
        if selected_role not in allowed_roles:
            raise Exception('Invalid role selected.')

        slug = re.sub(r'[^a-z0-9]+', '-', input.organization_name.lower()).strip('-')
        base_slug = slug
        counter = 1
        while Organization.objects.filter(slug=slug).exists():
            slug = f'{base_slug}-{counter}'
            counter += 1

        org = Organization.objects.create(name=input.organization_name, slug=slug)
        user = Profile.objects.create_user(
            email=email,
            full_name=input.full_name,
            password=input.password,
            phone=phone,
            organization=org,
            role=selected_role,
        )
        token = get_token(user)
        refresh = create_refresh_token(user)
        return AuthPayload(token=token, refresh_token=refresh.token, user=user)


class Login(graphene.Mutation):
    class Arguments:
        email = graphene.String(required=True)
        password = graphene.String(required=True)

    Output = AuthPayload

    def mutate(self, info, email, password):
        import re
        from graphql_jwt.shortcuts import get_token
        from graphql_jwt.refresh_token.shortcuts import create_refresh_token

        login_email = email.strip()

        # If the identifier looks like a phone number (digits/+/spaces), try the
        # auto-generated email pattern first, then fall back to direct match.
        if not '@' in login_email:
            clean = re.sub(r'[^0-9]', '', login_email)
            try:
                phone_user = Profile.objects.get(phone=login_email)
                login_email = phone_user.email
            except Profile.DoesNotExist:
                # Try the auto-generated email pattern
                login_email = f'{clean}@agrinuxes.local'

        user = authenticate(email=login_email, password=password)
        if not user:
            raise Exception('Invalid phone/email or password.')
        if not user.is_active:
            raise Exception('Account is disabled.')
        token = get_token(user)
        refresh = create_refresh_token(user)
        return AuthPayload(token=token, refresh_token=refresh.token, user=user)


class UpdateProfile(graphene.Mutation):
    class Arguments:
        input = UpdateProfileInput(required=True)

    profile = graphene.Field(ProfileType)

    def mutate(self, info, input):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        for field, value in input.items():
            if value is not None:
                setattr(user, field, value)
        user.save()
        return UpdateProfile(profile=user)


class UpdateOrganization(graphene.Mutation):
    class Arguments:
        input = UpdateOrganizationInput(required=True)

    organization = graphene.Field(OrganizationType)

    def mutate(self, info, input):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        if user.role not in ('director', 'saas_admin'):
            raise Exception('Permission denied')
        org = user.organization
        for field, value in input.items():
            if value is not None:
                setattr(org, field, value)
        org.save()
        return UpdateOrganization(organization=org)


class InviteUser(graphene.Mutation):
    class Arguments:
        input = InviteUserInput(required=True)

    profile = graphene.Field(ProfileType)
    temp_password = graphene.String()

    def mutate(self, info, input):
        import re
        import random
        from django.core.mail import send_mail
        from django.conf import settings as django_settings
        from apps.notifications.utils import notify

        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        if user.role not in ('director', 'saas_admin'):
            raise Exception('Permission denied — only Directors can add employees.')

        # Phone is mandatory
        phone = (input.get('phone') or '').strip()
        if not phone:
            raise Exception('Phone number is required.')
        if Profile.objects.filter(phone=phone, organization=user.organization).exists():
            raise Exception('A user with this phone number already exists in your organisation.')

        # Email is optional — auto-generate from phone if not provided
        email = (input.get('email') or '').strip()
        if not email:
            clean_phone = re.sub(r'[^0-9]', '', phone)
            email = f'{clean_phone}@agrinuxes.local'
        if Profile.objects.filter(email=email).exists():
            raise Exception('A user with this email already exists.')

        allowed_roles = {choice[0] for choice in Profile.ROLE_CHOICES}
        role = (input.role or 'farmhand').strip()
        if role not in allowed_roles:
            raise Exception('Invalid role.')

        # Use director-supplied password, or auto-generate one with unambiguous characters
        custom_pwd = input.get('password', '').strip() if input.get('password') else ''
        if custom_pwd:
            if len(custom_pwd) < 6:
                raise Exception('Password must be at least 6 characters.')
            pwd = custom_pwd
        else:
            chars = 'ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789'
            pwd = ''.join(random.choices(chars, k=10))

        new_user = Profile.objects.create_user(
            email=email,
            full_name=input.full_name,
            password=pwd,
            role=role,
            phone=phone,
            organization=user.organization,
        )

        # ── In-app notification to new user ───────────────────────────────────
        login_identifier = phone if email.endswith('@agrinuxes.local') else email
        notify(
            new_user,
            title='Welcome to Agrinuxes!',
            message=(
                f'Your account has been created by {user.full_name}.\n'
                f'Login: {login_identifier}\n'
                f'Temporary password: {pwd}\n'
                f'Please change your password after first login.'
            ),
            category='system',
            priority='info',
            action_url='/settings',
        )

        # ── Email notification (best-effort — skip if SMTP not configured) ────
        has_real_email = not email.endswith('@agrinuxes.local')
        if has_real_email:
            try:
                send_mail(
                    subject=f'Your Agrinuxes account — {user.organization.name}',
                    message=(
                        f'Hello {input.full_name},\n\n'
                        f'{user.full_name} has created an account for you on Agrinuxes.\n\n'
                        f'Organisation: {user.organization.name}\n'
                        f'Role: {role.replace("_", " ").title()}\n'
                        f'Login (email): {email}\n'
                        f'Temporary password: {pwd}\n\n'
                        f'Please sign in and change your password immediately.\n\n'
                        f'— The Agrinuxes Team'
                    ),
                    from_email=getattr(django_settings, 'DEFAULT_FROM_EMAIL', 'noreply@agrinuxes.com'),
                    recipient_list=[email],
                    fail_silently=True,
                )
            except Exception:
                pass  # Never block user creation over email failure

        return InviteUser(profile=new_user, temp_password=pwd)


class SetMemberPermissions(graphene.Mutation):
    """Director sets module-level action permissions for a member of their org.
    permissions is a JSON object: { moduleId: [action, ...] }
    where action ∈ ['view','create','edit','delete'].
    """
    class Arguments:
        user_id = graphene.ID(required=True)
        permissions = graphene.JSONString(required=True)

    profile = graphene.Field(ProfileType)

    def mutate(self, info, user_id, permissions):
        import json
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        if user.role not in ('director', 'saas_admin'):
            raise Exception('Permission denied')
        target = Profile.objects.get(id=user_id, organization=user.organization)
        prefs = dict(target.preferences or {})
        # graphene JSONString may arrive already-parsed or as a string
        if isinstance(permissions, str):
            permissions = json.loads(permissions)
        prefs['permissions'] = permissions
        target.preferences = prefs
        target.save()
        return SetMemberPermissions(profile=target)


class ActivateUser(graphene.Mutation):
    class Arguments:
        user_id = graphene.ID(required=True)

    success = graphene.Boolean()

    def mutate(self, info, user_id):
        user = info.context.user
        if user.role not in ('director', 'saas_admin'):
            raise Exception('Permission denied')
        target = Profile.objects.get(id=user_id, organization=user.organization)
        target.is_active = True
        target.save()
        return ActivateUser(success=True)


class UpdateMemberRole(graphene.Mutation):
    class Arguments:
        user_id = graphene.ID(required=True)
        role = graphene.String(required=True)

    profile = graphene.Field(ProfileType)

    def mutate(self, info, user_id, role):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        if user.role not in ('director', 'saas_admin'):
            raise Exception('Permission denied — only Directors can change roles.')
        allowed_roles = {choice[0] for choice in Profile.ROLE_CHOICES}
        if role not in allowed_roles:
            raise Exception('Invalid role.')
        target = Profile.objects.get(id=user_id, organization=user.organization)
        target.role = role
        target.save()
        return UpdateMemberRole(profile=target)


class ChangePassword(graphene.Mutation):
    class Arguments:
        old_password = graphene.String(required=True)
        new_password = graphene.String(required=True)

    success = graphene.Boolean()
    message = graphene.String()

    def mutate(self, info, old_password, new_password):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        if not user.check_password(old_password):
            return ChangePassword(success=False, message='Incorrect current password.')
        user.set_password(new_password)
        user.save()
        return ChangePassword(success=True, message='Password updated successfully.')


class DeactivateUser(graphene.Mutation):
    class Arguments:
        user_id = graphene.ID(required=True)

    success = graphene.Boolean()

    def mutate(self, info, user_id):
        user = info.context.user
        if user.role not in ('director', 'saas_admin'):
            raise Exception('Permission denied')
        target = Profile.objects.get(id=user_id, organization=user.organization)
        target.is_active = False
        target.save()
        return DeactivateUser(success=True)


class AccountMutation(graphene.ObjectType):
    register = Register.Field()
    login = Login.Field()
    verify_token = graphql_jwt.Verify.Field()
    refresh_token = graphql_jwt.Refresh.Field()
    revoke_token = graphql_jwt.Revoke.Field()
    update_profile = UpdateProfile.Field()
    update_organization = UpdateOrganization.Field()
    invite_user = InviteUser.Field()
    set_member_permissions = SetMemberPermissions.Field()
    activate_user = ActivateUser.Field()
    update_member_role = UpdateMemberRole.Field()
    change_password = ChangePassword.Field()
    deactivate_user = DeactivateUser.Field()
