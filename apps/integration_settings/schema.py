"""
GraphQL surface for admin-managed integration credentials. Permission
check matches this codebase's own real, demonstrably-used pattern —
inline `info.context.user.is_staff` (see apps/market/provider_schema.py's
VerifyProvider/ApproveReview) — rather than importing a helper from
another app or inventing a decorator this codebase doesn't otherwise use.
"""
import graphene
from graphene_django import DjangoObjectType

from .models import IntegrationCredential


class IntegrationCredentialType(DjangoObjectType):
    masked_api_key = graphene.String()
    masked_secret = graphene.String()
    has_api_key = graphene.Boolean()
    has_secret = graphene.Boolean()

    class Meta:
        model = IntegrationCredential
        fields = ['id', 'service', 'base_url', 'app_id', 'is_active', 'updated_at', 'created_at']

    def resolve_masked_api_key(self, info):
        return IntegrationCredential.masked(self.get_api_key())

    def resolve_masked_secret(self, info):
        return IntegrationCredential.masked(self.get_secret())

    def resolve_has_api_key(self, info):
        return bool(self.encrypted_api_key)

    def resolve_has_secret(self, info):
        return bool(self.encrypted_secret)


class IntegrationSettingsQuery(graphene.ObjectType):
    integration_credentials = graphene.List(IntegrationCredentialType)
    available_integration_services = graphene.List(graphene.String)

    def resolve_integration_credentials(self, info):
        user = info.context.user
        if not user.is_authenticated or not user.is_staff:
            return IntegrationCredential.objects.none()
        return IntegrationCredential.objects.all().order_by('service')

    def resolve_available_integration_services(self, info):
        return [c[0] for c in IntegrationCredential.Service.choices]


class SaveIntegrationCredentialMutation(graphene.Mutation):
    """
    Admin-only. Creates or updates the one row for `service`. api_key/
    secret are optional on every call: omit or send an empty string to
    leave whatever is already stored unchanged. Use clearApiKey/
    clearSecret to actually clear a stored value.
    """
    class Arguments:
        service = graphene.String(required=True)
        base_url = graphene.String()
        app_id = graphene.String()
        api_key = graphene.String()
        secret = graphene.String()
        is_active = graphene.Boolean()
        clear_api_key = graphene.Boolean()
        clear_secret = graphene.Boolean()

    ok = graphene.Boolean()
    error = graphene.String()
    credential = graphene.Field(IntegrationCredentialType)

    @classmethod
    def mutate(cls, root, info, service, base_url=None, app_id=None, api_key=None,
               secret=None, is_active=None, clear_api_key=False, clear_secret=False):
        user = info.context.user
        if not user.is_authenticated or not user.is_staff:
            return SaveIntegrationCredentialMutation(ok=False, error='Only platform admins can manage integration settings')

        valid_services = [c[0] for c in IntegrationCredential.Service.choices]
        if service not in valid_services:
            return SaveIntegrationCredentialMutation(
                ok=False, error=f'service must be one of: {", ".join(valid_services)}',
            )

        row, _ = IntegrationCredential.objects.get_or_create(service=service)
        if base_url is not None:
            row.base_url = base_url
        if app_id is not None:
            row.app_id = app_id
        if clear_api_key:
            row.encrypted_api_key = ''
        elif api_key:
            row.set_api_key(api_key)
        if clear_secret:
            row.encrypted_secret = ''
        elif secret:
            row.set_secret(secret)
        if is_active is not None:
            row.is_active = is_active
        row.updated_by = str(getattr(user, 'email', '') or getattr(user, 'username', '') or getattr(user, 'id', ''))
        row.save()

        return SaveIntegrationCredentialMutation(ok=True, credential=row)


class IntegrationSettingsMutation(graphene.ObjectType):
    save_integration_credential = SaveIntegrationCredentialMutation.Field()
