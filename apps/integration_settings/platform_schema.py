"""Platform admin portal API: only accounts with the platform-admin role (role = saas_admin) can use it.

  platformOverview      counts of organisations by type, users, recent sign-ups
  platformOrganisations the organisations list with search
  platformAiSettings    whether a Claude key is saved (masked) and whether the assistant is using the model
  savePlatformAiKey     paste or replace the key (stored encrypted, never returned)
  clearPlatformAiKey    remove it
  platformGuide         the user guide as a web page
"""
from datetime import timedelta

import graphene
from django.conf import settings
from django.db.models import Count
from django.utils import timezone

from .models import IntegrationCredential


def _admin(info):
    u = info.context.user
    if u.is_anonymous or getattr(u, 'role', '') != 'saas_admin':
        raise Exception('Platform administrators only')
    return u


def _row():
    return IntegrationCredential.objects.filter(service='ai').first()


class PlatformQuery(graphene.ObjectType):
    platform_overview = graphene.JSONString()
    platform_organisations = graphene.JSONString(search=graphene.String(), limit=graphene.Int())
    platform_ai_settings = graphene.JSONString()
    platform_guide = graphene.String()

    def resolve_platform_overview(self, info):
        _admin(info)
        from apps.accounts.models import Organization, Profile
        week = timezone.now() - timedelta(days=7)
        orgs = Organization.objects.all()
        by_type = {r['business_type']: r['n'] for r in orgs.filter(org_type='farm').values('business_type').annotate(n=Count('id'))}
        by_kind = {r['org_type']: r['n'] for r in orgs.values('org_type').annotate(n=Count('id'))}
        recent = orgs.order_by('-created_at')[:8]
        return {
            'organisations': orgs.count(), 'users': Profile.objects.count(),
            'newOrganisations7d': orgs.filter(created_at__gte=week).count(), 'newUsers7d': Profile.objects.filter(created_at__gte=week).count(),
            'byBusinessType': by_type, 'byKind': by_kind,
            'recent': [{'name': o.name, 'type': o.business_type if o.org_type == 'farm' else o.org_type, 'country': o.country, 'createdAt': o.created_at.isoformat()} for o in recent],
        }

    def resolve_platform_organisations(self, info, search='', limit=200):
        _admin(info)
        from apps.accounts.models import Organization
        qs = Organization.objects.annotate(users=Count('members'))
        if search:
            qs = qs.filter(name__icontains=search)
        out = []
        for o in qs.order_by('-created_at')[:max(1, min(limit or 200, 500))]:
            out.append({'id': str(o.id), 'name': o.name, 'orgType': o.org_type, 'businessType': o.business_type, 'plan': o.plan,
                        'country': o.country, 'district': o.district, 'active': o.is_active, 'createdAt': o.created_at.isoformat(),
                        'users': getattr(o, 'users', None)})
        return out

    def resolve_platform_ai_settings(self, info):
        _admin(info)
        from apps.assistant import service
        row = _row()
        key = row.get_api_key() if row else ''
        return {
            'hasSavedKey': bool(key), 'maskedKey': IntegrationCredential.masked(key), 'active': bool(row and row.is_active),
            'updatedAt': row.updated_at.isoformat() if row else None, 'updatedBy': row.updated_by if row else '',
            'usingModel': service.available(), 'fromEnvironment': service.available() and not (row and row.is_active and key),
            'model': getattr(settings, 'ASSISTANT_MODEL', '') or 'claude-sonnet-5-5',
        }

    def resolve_platform_guide(self, info):
        _admin(info)
        path = settings.BASE_DIR / 'docs' / 'AGRINUXES-User-Guide.html'
        return path.read_text(encoding='utf-8') if path.exists() else ''


class SavePlatformAiKey(graphene.Mutation):
    class Arguments:
        api_key = graphene.String(required=True)
        active = graphene.Boolean()

    ok = graphene.Boolean()

    def mutate(self, info, api_key, active=True):
        u = _admin(info)
        key = api_key.strip()
        if len(key) < 20 or ' ' in key:
            raise Exception('That does not look like an API key. Paste the whole key.')
        row = _row() or IntegrationCredential(service='ai')
        row.set_api_key(key)
        row.is_active = True if active is None else active
        row.updated_by = u.email
        row.save()
        return SavePlatformAiKey(ok=True)


class ClearPlatformAiKey(graphene.Mutation):
    ok = graphene.Boolean()

    def mutate(self, info):
        u = _admin(info)
        row = _row()
        if row:
            row.set_api_key('')
            row.updated_by = u.email
            row.save()
        return ClearPlatformAiKey(ok=True)


class PlatformMutation(graphene.ObjectType):
    save_platform_ai_key = SavePlatformAiKey.Field()
    clear_platform_ai_key = ClearPlatformAiKey.Field()
