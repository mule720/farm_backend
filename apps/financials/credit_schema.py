"""Credit summary + lender sharing — GraphQL surface."""
import secrets
from datetime import timedelta

import graphene
from django.utils import timezone
from graphene_django import DjangoObjectType

from .models import CreditShareGrant
from apps.accounts import rbac
from .credit import compute_credit_summary, build_credit_summary_pdf


def _farm_user(info):
    user = info.context.user
    if user.is_anonymous:
        raise Exception('Not authenticated')
    if user.organization is None or user.organization.org_type != 'farm':
        raise Exception('Permission denied: farm account required')
    return user


class CreditShareGrantType(DjangoObjectType):
    is_active = graphene.Boolean()
    share_url_path = graphene.String(description='Append to the app origin: /?credit=<token>')

    class Meta:
        model = CreditShareGrant
        fields = ['id', 'lender_name', 'lender_contact', 'purpose', 'token', 'expires_at', 'is_revoked',
                  'access_count', 'last_accessed_at', 'created_at']

    def resolve_is_active(self, info):
        return self.is_active

    def resolve_share_url_path(self, info):
        return f'/?credit={self.token}'


class CreditSummaryType(graphene.ObjectType):
    """The whole summary as JSON — shape documented in credit.compute_credit_summary."""
    score = graphene.Int()
    band = graphene.String()
    band_label = graphene.String()
    thin_file = graphene.Boolean()
    summary = graphene.JSONString()


def _wrap(s):
    return CreditSummaryType(score=s['score'], band=s['band'], band_label=s['band_label'], thin_file=s['thin_file'], summary=s)


class CreditQuery(graphene.ObjectType):
    my_credit_summary = graphene.Field(CreditSummaryType)
    credit_share_grants = graphene.List(CreditShareGrantType)
    lender_credit_report = graphene.Field(CreditSummaryType, token=graphene.String(required=True),
                                          description='Public: read-only summary for a lender holding a valid share token')

    def resolve_my_credit_summary(self, info):
        return _wrap(compute_credit_summary(rbac.require_module(_farm_user(info), 'credit', 'view').organization))

    def resolve_credit_share_grants(self, info):
        return CreditShareGrant.objects.filter(organization=_farm_user(info).organization)

    def resolve_lender_credit_report(self, info, token):
        token = (token or '').strip()
        if len(token) < 20:
            raise Exception('Invalid share link')
        grant = CreditShareGrant.objects.select_related('organization').filter(token=token).first()
        if grant is None:
            raise Exception('Invalid share link')
        if grant.is_revoked:
            raise Exception('This share link has been revoked by the farm')
        if grant.expires_at <= timezone.now():
            raise Exception('This share link has expired')
        CreditShareGrant.objects.filter(pk=grant.pk).update(access_count=grant.access_count + 1, last_accessed_at=timezone.now())
        s = compute_credit_summary(grant.organization)
        s['shared_with'] = {'lender': grant.lender_name, 'purpose': grant.purpose, 'expires_at': grant.expires_at.isoformat()}
        return _wrap(s)


class CreateCreditShareGrant(graphene.Mutation):
    class Arguments:
        lender_name = graphene.String(required=True)
        lender_contact = graphene.String()
        purpose = graphene.String()
        valid_days = graphene.Int()

    grant = graphene.Field(CreditShareGrantType)

    def mutate(self, info, lender_name, lender_contact=None, purpose=None, valid_days=None):
        user = rbac.require_module(_farm_user(info), 'credit', 'create')
        days = max(1, min(valid_days or 30, 180))
        grant = CreditShareGrant.objects.create(
            organization=user.organization, lender_name=lender_name.strip(), lender_contact=(lender_contact or '').strip(),
            purpose=(purpose or '').strip(), token=secrets.token_urlsafe(32), expires_at=timezone.now() + timedelta(days=days), created_by=user)
        return CreateCreditShareGrant(grant=grant)


class RevokeCreditShareGrant(graphene.Mutation):
    class Arguments:
        id = graphene.UUID(required=True)

    ok = graphene.Boolean()

    def mutate(self, info, id):
        user = rbac.require_module(_farm_user(info), 'credit', 'delete')
        n = CreditShareGrant.objects.filter(pk=id, organization=user.organization).update(is_revoked=True)
        if not n:
            raise Exception('Share not found')
        return RevokeCreditShareGrant(ok=True)


class GenerateCreditSummaryPdf(graphene.Mutation):
    class Arguments:
        for_lender = graphene.String()

    url = graphene.String()

    def mutate(self, info, for_lender=None):
        user = _farm_user(info)
        return GenerateCreditSummaryPdf(url=build_credit_summary_pdf(user.organization, for_lender=for_lender))


class CreditMutation(graphene.ObjectType):
    create_credit_share_grant = CreateCreditShareGrant.Field()
    revoke_credit_share_grant = RevokeCreditShareGrant.Field()
    generate_credit_summary_pdf = GenerateCreditSummaryPdf.Field()
