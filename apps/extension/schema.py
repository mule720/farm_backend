"""
Extension officer services.

An extension officer (role `extension_officer`) belongs to a government /
partner organisation whose province / district is the officer's working
area. Officers:

  * build a caseload from farms in that area that have opted in to data
    sharing (identity is visible here, unlike the aggregated gov queries —
    consent is the gate);
  * see a prioritised caseload (open alerts, unresolved reports, high /
    critical AI diagnoses) and a per-farm detail view;
  * log visits, set follow-ups, resolve farmer reports, and send advice.

Farmers see their assigned officers and visit history via `my*` queries.
"""
import graphene
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from graphene_django import DjangoObjectType

from apps.accounts.models import Organization, Profile
from apps.accounts import rbac
from .models import ExtensionCaseload, ExtensionVisit


# ─── Guards ───────────────────────────────────────────────────────────────────

def _require_officer(info):
    user = info.context.user
    if user.is_anonymous:
        raise Exception('Not authenticated')
    if not user.has_role(*rbac.EXTENSION_ROLES):  # or saas_admin
        raise Exception('Permission denied: extension officer access required')
    if user.role in rbac.EXTENSION_ROLES and (user.organization is None or user.organization.org_type == 'farm'):
        raise Exception('Extension officers must belong to a government / partner organisation')
    rbac.require_module(user, 'caseload', 'view')
    return user


def _require_farm_member(info):
    user = info.context.user
    if user.is_anonymous:
        raise Exception('Not authenticated')
    if user.organization is None or user.organization.org_type != 'farm':
        raise Exception('Permission denied: farm account required')
    return user


def _area_farms(user):
    """Consenting farms inside the officer's working area."""
    qs = Organization.objects.filter(org_type='farm', data_sharing_consent=True, is_active=True)
    org = user.organization
    if user.role == 'saas_admin' or org is None:
        return qs
    # Branch geography wins over the organisation's
    bp, bd = rbac.branch_geo(user)
    if bd:
        return qs.filter(province__iexact=bp or org.province, district__iexact=bd)
    if bp:
        return qs.filter(province__iexact=bp)
    if org.district:
        return qs.filter(province__iexact=org.province, district__iexact=org.district)
    if org.province:
        return qs.filter(province__iexact=org.province)
    return qs


def _caseload_farm(user, farm_id):
    """The farm if it is on this officer's active caseload, else raise."""
    try:
        return ExtensionCaseload.objects.select_related('farm').get(
            officer=user, farm_id=farm_id, is_active=True).farm
    except ExtensionCaseload.DoesNotExist:
        raise Exception('Farm is not on your caseload')


# ─── Types ────────────────────────────────────────────────────────────────────

class OfficerType(graphene.ObjectType):
    id = graphene.ID()
    full_name = graphene.String()
    phone = graphene.String()
    email = graphene.String()
    organization_name = graphene.String()
    assigned_at = graphene.DateTime()


class CaseloadFarmType(graphene.ObjectType):
    """One row of the officer's caseload — identity plus live risk signals."""
    farm_id = graphene.ID()
    name = graphene.String()
    province = graphene.String()
    district = graphene.String()
    director_name = graphene.String()
    director_phone = graphene.String()
    enterprises = graphene.Int()
    enterprise_categories = graphene.List(graphene.String)
    active_batches = graphene.Int()
    open_alerts = graphene.Int()
    critical_alerts = graphene.Int()
    unresolved_reports = graphene.Int()
    severe_diagnoses_30d = graphene.Int()
    records_30d = graphene.Int()
    last_visit_date = graphene.Date()
    next_follow_up = graphene.Date()
    follow_up_overdue = graphene.Boolean()
    priority_score = graphene.Int()
    assigned_at = graphene.DateTime()


class AvailableFarmType(graphene.ObjectType):
    farm_id = graphene.ID()
    name = graphene.String()
    province = graphene.String()
    district = graphene.String()
    enterprises = graphene.Int()
    unresolved_reports = graphene.Int()
    consented_at = graphene.DateTime()


class FarmReportType(graphene.ObjectType):
    id = graphene.ID()
    category = graphene.String()
    title = graphene.String()
    description = graphene.String()
    crop_or_animal = graphene.String()
    severity = graphene.String()
    diagnosis = graphene.String()
    is_resolved = graphene.Boolean()
    resolution_notes = graphene.String()
    created_at = graphene.DateTime()


class FarmDiagnosisType(graphene.ObjectType):
    id = graphene.ID()
    analysis_type = graphene.String()
    diagnosis = graphene.String()
    severity = graphene.String()
    confidence_pct = graphene.Int()
    created_at = graphene.DateTime()


class FarmAlertType(graphene.ObjectType):
    id = graphene.ID()
    source = graphene.String()
    severity = graphene.String()
    title = graphene.String()
    is_resolved = graphene.Boolean()
    created_at = graphene.DateTime()


class FarmEnterpriseType(graphene.ObjectType):
    id = graphene.ID()
    name = graphene.String()
    category = graphene.String()
    production_type = graphene.String()
    active_batches = graphene.Int()


class ExtensionVisitType(DjangoObjectType):
    farm_name = graphene.String()
    officer_name = graphene.String()
    farm_id = graphene.ID()

    class Meta:
        model = ExtensionVisit
        fields = ['id', 'visit_date', 'visit_type', 'purpose', 'findings', 'recommendations',
                  'follow_up_date', 'follow_up_done', 'created_at', 'farmer_report']
        convert_choices_to_enum = False

    def resolve_farm_name(self, info):
        return self.farm.name

    def resolve_officer_name(self, info):
        return self.officer.full_name

    def resolve_farm_id(self, info):
        return self.farm_id


class FarmDetailType(graphene.ObjectType):
    summary = graphene.Field(CaseloadFarmType)
    enterprises = graphene.List(FarmEnterpriseType)
    reports = graphene.List(FarmReportType)
    diagnoses = graphene.List(FarmDiagnosisType)
    alerts = graphene.List(FarmAlertType)
    visits = graphene.List(ExtensionVisitType)


class ExtensionOverviewType(graphene.ObjectType):
    caseload_size = graphene.Int()
    farms_available = graphene.Int()
    farms_needing_attention = graphene.Int()
    follow_ups_overdue = graphene.Int()
    follow_ups_this_week = graphene.Int()
    visits_30d = graphene.Int()
    unresolved_reports = graphene.Int()
    working_area = graphene.String()


# ─── Caseload row builder ─────────────────────────────────────────────────────

def _build_rows(user, assignments):
    from apps.enterprises.models import Enterprise, EnterpriseBatch
    from apps.production.models import ProductionRecord
    from apps.devices.models import SecurityAlert
    from apps.vision.models import FarmerReport, AIVisionAnalysis

    farm_ids = [a.farm_id for a in assignments]
    if not farm_ids:
        return []
    today = timezone.localdate()
    since_dt = timezone.now() - timedelta(days=30)
    since_d = today - timedelta(days=30)

    def _count_by(qs):
        return {r['organization_id']: r['n'] for r in qs.values('organization_id').annotate(n=Count('id'))}

    ent_cats = {}
    for e in Enterprise.objects.filter(organization_id__in=farm_ids, is_active=True).values('organization_id', 'category'):
        ent_cats.setdefault(e['organization_id'], []).append(e['category'])
    batches = _count_by(EnterpriseBatch.objects.filter(organization_id__in=farm_ids, status='active'))
    alerts = _count_by(SecurityAlert.objects.filter(organization_id__in=farm_ids, is_resolved=False))
    crit = _count_by(SecurityAlert.objects.filter(organization_id__in=farm_ids, is_resolved=False, severity='critical'))
    reports = _count_by(FarmerReport.objects.filter(organization_id__in=farm_ids, is_resolved=False))
    severe = _count_by(AIVisionAnalysis.objects.filter(
        organization_id__in=farm_ids, created_at__gte=since_dt, severity__in=['high', 'critical']))
    records = _count_by(ProductionRecord.objects.filter(organization_id__in=farm_ids, record_date__gte=since_d))

    last_visit, next_fu = {}, {}
    for v in ExtensionVisit.objects.filter(officer=user, farm_id__in=farm_ids).values(
            'farm_id', 'visit_date', 'follow_up_date', 'follow_up_done'):
        f = v['farm_id']
        if f not in last_visit or v['visit_date'] > last_visit[f]:
            last_visit[f] = v['visit_date']
        if v['follow_up_date'] and not v['follow_up_done']:
            if f not in next_fu or v['follow_up_date'] < next_fu[f]:
                next_fu[f] = v['follow_up_date']

    directors = {}
    for p in Profile.objects.filter(organization_id__in=farm_ids, role='director', is_active=True) \
            .order_by('created_at').values('organization_id', 'full_name', 'phone'):
        directors.setdefault(p['organization_id'], p)

    rows = []
    for a in assignments:
        f = a.farm
        fid = f.id
        fu = next_fu.get(fid)
        overdue = bool(fu and fu < today)
        cats = sorted(set(ent_cats.get(fid, [])))
        score = (crit.get(fid, 0) * 5 + alerts.get(fid, 0) * 2 + reports.get(fid, 0) * 3
                 + severe.get(fid, 0) * 3 + (4 if overdue else 0)
                 + (2 if fid not in last_visit else 0))
        d = directors.get(fid, {})
        rows.append(CaseloadFarmType(
            farm_id=fid, name=f.name, province=f.province, district=f.district,
            director_name=d.get('full_name'), director_phone=d.get('phone'),
            enterprises=len(ent_cats.get(fid, [])), enterprise_categories=cats,
            active_batches=batches.get(fid, 0), open_alerts=alerts.get(fid, 0),
            critical_alerts=crit.get(fid, 0), unresolved_reports=reports.get(fid, 0),
            severe_diagnoses_30d=severe.get(fid, 0), records_30d=records.get(fid, 0),
            last_visit_date=last_visit.get(fid), next_follow_up=fu, follow_up_overdue=overdue,
            priority_score=score, assigned_at=a.assigned_at,
        ))
    rows.sort(key=lambda r: (-r.priority_score, r.name))
    return rows


# ─── Queries ──────────────────────────────────────────────────────────────────

class ExtensionQuery(graphene.ObjectType):
    extension_overview = graphene.Field(ExtensionOverviewType)
    extension_caseload = graphene.List(CaseloadFarmType)
    extension_available_farms = graphene.List(AvailableFarmType, search=graphene.String())
    extension_farm_detail = graphene.Field(FarmDetailType, farm_id=graphene.ID(required=True))
    extension_visits = graphene.List(ExtensionVisitType, farm_id=graphene.ID(), pending_follow_up=graphene.Boolean())
    # Farmer-facing
    my_extension_officers = graphene.List(OfficerType)
    my_extension_visits = graphene.List(ExtensionVisitType)

    def resolve_extension_overview(self, info):
        user = _require_officer(info)
        from apps.vision.models import FarmerReport
        assignments = list(ExtensionCaseload.objects.filter(officer=user, is_active=True).select_related('farm'))
        rows = _build_rows(user, assignments)
        today = timezone.localdate()
        week = today + timedelta(days=7)
        pending = ExtensionVisit.objects.filter(officer=user, follow_up_done=False, follow_up_date__isnull=False)
        org = user.organization
        area = org.district or org.province or 'All areas' if org else 'All areas'
        return ExtensionOverviewType(
            caseload_size=len(rows),
            farms_available=_area_farms(user).exclude(
                id__in=[a.farm_id for a in assignments]).count(),
            farms_needing_attention=sum(1 for r in rows if r.priority_score >= 3),
            follow_ups_overdue=pending.filter(follow_up_date__lt=today).count(),
            follow_ups_this_week=pending.filter(follow_up_date__gte=today, follow_up_date__lte=week).count(),
            visits_30d=ExtensionVisit.objects.filter(officer=user, visit_date__gte=today - timedelta(days=30)).count(),
            unresolved_reports=FarmerReport.objects.filter(
                organization_id__in=[a.farm_id for a in assignments], is_resolved=False).count(),
            working_area=area,
        )

    def resolve_extension_caseload(self, info):
        user = _require_officer(info)
        assignments = list(ExtensionCaseload.objects.filter(officer=user, is_active=True).select_related('farm'))
        return _build_rows(user, assignments)

    def resolve_extension_available_farms(self, info, search=None):
        user = _require_officer(info)
        from apps.enterprises.models import Enterprise
        from apps.vision.models import FarmerReport
        taken = ExtensionCaseload.objects.filter(officer=user, is_active=True).values('farm_id')
        qs = _area_farms(user).exclude(id__in=taken)
        if search:
            qs = qs.filter(name__icontains=search.strip())
        farms = list(qs.order_by('name')[:100])
        ids = [f.id for f in farms]
        ents = {r['organization_id']: r['n'] for r in Enterprise.objects.filter(
            organization_id__in=ids, is_active=True).values('organization_id').annotate(n=Count('id'))}
        reps = {r['organization_id']: r['n'] for r in FarmerReport.objects.filter(
            organization_id__in=ids, is_resolved=False).values('organization_id').annotate(n=Count('id'))}
        return [AvailableFarmType(farm_id=f.id, name=f.name, province=f.province, district=f.district,
                                  enterprises=ents.get(f.id, 0), unresolved_reports=reps.get(f.id, 0),
                                  consented_at=f.data_sharing_consented_at) for f in farms]

    def resolve_extension_farm_detail(self, info, farm_id):
        user = _require_officer(info)
        from apps.enterprises.models import Enterprise, EnterpriseBatch
        from apps.devices.models import SecurityAlert
        from apps.vision.models import FarmerReport, AIVisionAnalysis

        farm = _caseload_farm(user, farm_id)
        assignment = ExtensionCaseload.objects.get(officer=user, farm=farm, is_active=True)
        summary = _build_rows(user, [assignment])[0]

        batch_counts = {r['enterprise_id']: r['n'] for r in EnterpriseBatch.objects.filter(
            organization=farm, status='active').values('enterprise_id').annotate(n=Count('id'))}
        enterprises = [FarmEnterpriseType(id=e.id, name=e.name, category=e.category,
                                          production_type=e.production_type,
                                          active_batches=batch_counts.get(e.id, 0))
                       for e in Enterprise.objects.filter(organization=farm, is_active=True)]
        reports = [FarmReportType(
            id=r.id, category=r.category, title=r.title, description=r.description,
            crop_or_animal=r.crop_or_animal,
            severity=r.vision_analysis.severity if r.vision_analysis_id else None,
            diagnosis=r.vision_analysis.diagnosis if r.vision_analysis_id else None,
            is_resolved=r.is_resolved, resolution_notes=r.resolution_notes, created_at=r.created_at,
        ) for r in FarmerReport.objects.filter(organization=farm).select_related('vision_analysis')
            .order_by('is_resolved', '-created_at')[:50]]
        diagnoses = [FarmDiagnosisType(id=a.id, analysis_type=a.analysis_type, diagnosis=a.diagnosis,
                                       severity=a.severity, confidence_pct=a.confidence_pct, created_at=a.created_at)
                     for a in AIVisionAnalysis.objects.filter(organization=farm).order_by('-created_at')[:30]]
        alerts = [FarmAlertType(id=a.id, source=a.source, severity=a.severity, title=a.title,
                                is_resolved=a.is_resolved, created_at=a.created_at)
                  for a in SecurityAlert.objects.filter(organization=farm).order_by('is_resolved', '-created_at')[:30]]
        visits = ExtensionVisit.objects.filter(farm=farm).select_related('farm', 'officer')[:50]
        return FarmDetailType(summary=summary, enterprises=enterprises, reports=reports,
                              diagnoses=diagnoses, alerts=alerts, visits=visits)

    def resolve_extension_visits(self, info, farm_id=None, pending_follow_up=None):
        user = _require_officer(info)
        qs = ExtensionVisit.objects.filter(officer=user).select_related('farm', 'officer')
        if farm_id:
            qs = qs.filter(farm_id=farm_id)
        if pending_follow_up:
            qs = qs.filter(follow_up_done=False, follow_up_date__isnull=False).order_by('follow_up_date')
        return qs

    def resolve_my_extension_officers(self, info):
        user = _require_farm_member(info)
        rows = ExtensionCaseload.objects.filter(farm=user.organization, is_active=True) \
            .select_related('officer', 'officer__organization')
        return [OfficerType(id=c.officer.id, full_name=c.officer.full_name, phone=c.officer.phone,
                            email=c.officer.email,
                            organization_name=c.officer.organization.name if c.officer.organization else None,
                            assigned_at=c.assigned_at) for c in rows]

    def resolve_my_extension_visits(self, info):
        user = _require_farm_member(info)
        return ExtensionVisit.objects.filter(farm=user.organization).select_related('farm', 'officer')


# ─── Mutations ────────────────────────────────────────────────────────────────

class AssignCaseloadFarm(graphene.Mutation):
    """Add a consenting farm in the officer's area to their caseload."""

    class Arguments:
        farm_id = graphene.ID(required=True)
        notes = graphene.String()

    farm = graphene.Field(CaseloadFarmType)

    def mutate(self, info, farm_id, notes=None):
        from apps.notifications.models import Notification
        user = rbac.require_module(_require_officer(info), 'caseload', 'create')
        try:
            farm = _area_farms(user).get(id=farm_id)
        except Organization.DoesNotExist:
            raise Exception('Farm not found in your working area, or it has not opted in to data sharing')
        with transaction.atomic():
            assignment, created = ExtensionCaseload.objects.get_or_create(
                officer=user, farm=farm, defaults={'assigned_by': user, 'notes': notes or ''})
            if not created and not assignment.is_active:
                assignment.is_active = True
                assignment.ended_at = None
                assignment.assigned_at = timezone.now()
                assignment.save(update_fields=['is_active', 'ended_at', 'assigned_at'])
                created = True
            if created:
                Notification.objects.bulk_create([
                    Notification(recipient=p, title='Extension officer assigned',
                                 message=f'{user.full_name} ({user.organization.name}) is now your extension officer. '
                                         f'Contact: {user.phone or user.email}.',
                                 category='system', priority='info', action_url='/settings', ref_id=str(assignment.id))
                    for p in Profile.objects.filter(organization=farm, is_active=True)
                ])
        return AssignCaseloadFarm(farm=_build_rows(user, [assignment])[0])


class RemoveCaseloadFarm(graphene.Mutation):
    class Arguments:
        farm_id = graphene.ID(required=True)

    ok = graphene.Boolean()

    def mutate(self, info, farm_id):
        # Removing a farm from one's own caseload is editing the caseload, not deleting data
        user = rbac.require_module(_require_officer(info), 'caseload', 'edit')
        n = ExtensionCaseload.objects.filter(officer=user, farm_id=farm_id, is_active=True) \
            .update(is_active=False, ended_at=timezone.now())
        if not n:
            raise Exception('Farm is not on your caseload')
        return RemoveCaseloadFarm(ok=True)


class VisitInput(graphene.InputObjectType):
    farm_id = graphene.ID(required=True)
    visit_date = graphene.Date(required=True)
    visit_type = graphene.String()
    purpose = graphene.String(required=True)
    findings = graphene.String()
    recommendations = graphene.String()
    follow_up_date = graphene.Date()
    farmer_report_id = graphene.ID()
    notify_farm = graphene.Boolean()


class LogExtensionVisit(graphene.Mutation):
    class Arguments:
        input = VisitInput(required=True)

    visit = graphene.Field(ExtensionVisitType)

    def mutate(self, info, input):
        from apps.notifications.models import Notification
        from apps.vision.models import FarmerReport
        user = rbac.require_module(_require_officer(info), 'visits', 'create')
        farm = _caseload_farm(user, input.farm_id)
        vt = (input.get('visit_type') or 'field_visit').strip()
        if vt not in dict(ExtensionVisit.VISIT_TYPE_CHOICES):
            raise Exception('Invalid visit type')
        report = None
        if input.get('farmer_report_id'):
            report = FarmerReport.objects.filter(id=input.farmer_report_id, organization=farm).first()
            if report is None:
                raise Exception('Farmer report not found on this farm')
        with transaction.atomic():
            visit = ExtensionVisit.objects.create(
                officer=user, farm=farm, visit_date=input.visit_date, visit_type=vt,
                purpose=input.purpose.strip(), findings=(input.get('findings') or '').strip(),
                recommendations=(input.get('recommendations') or '').strip(),
                follow_up_date=input.get('follow_up_date'), farmer_report=report,
            )
            if input.get('notify_farm', True) and visit.recommendations:
                Notification.objects.bulk_create([
                    Notification(recipient=p, title=f'Extension visit: {visit.purpose}'[:200],
                                 message=f'{visit.recommendations}\n\n— {user.full_name}, {user.organization.name}',
                                 category='system', priority='info', action_url='/settings', ref_id=str(visit.id))
                    for p in Profile.objects.filter(organization=farm, is_active=True)
                ])
        return LogExtensionVisit(visit=visit)


class CompleteFollowUp(graphene.Mutation):
    class Arguments:
        visit_id = graphene.ID(required=True)

    visit = graphene.Field(ExtensionVisitType)

    def mutate(self, info, visit_id):
        user = _require_officer(info)
        try:
            visit = ExtensionVisit.objects.get(id=visit_id, officer=user)
        except ExtensionVisit.DoesNotExist:
            raise Exception('Visit not found')
        visit.follow_up_done = True
        visit.save(update_fields=['follow_up_done', 'updated_at'])
        return CompleteFollowUp(visit=visit)


class ResolveFarmerReport(graphene.Mutation):
    """Officer closes a farmer's issue report with resolution notes."""

    class Arguments:
        report_id = graphene.ID(required=True)
        resolution_notes = graphene.String(required=True)

    report = graphene.Field(FarmReportType)

    def mutate(self, info, report_id, resolution_notes):
        from apps.vision.models import FarmerReport
        from apps.notifications.models import Notification
        user = _require_officer(info)
        report = FarmerReport.objects.filter(id=report_id).select_related('organization').first()
        if report is None:
            raise Exception('Report not found')
        _caseload_farm(user, report.organization_id)
        notes = resolution_notes.strip()
        if not notes:
            raise Exception('Resolution notes are required')
        with transaction.atomic():
            report.is_resolved = True
            report.resolution_notes = f'{notes}\n— {user.full_name} (extension officer)'
            report.save(update_fields=['is_resolved', 'resolution_notes', 'updated_at'])
            if report.submitted_by_id:
                Notification.objects.create(
                    recipient=report.submitted_by, title=f'Report resolved: {report.title}'[:200],
                    message=notes, category='vision', priority='info', ref_id=str(report.id))
        return ResolveFarmerReport(report=FarmReportType(
            id=report.id, category=report.category, title=report.title, description=report.description,
            crop_or_animal=report.crop_or_animal, is_resolved=True, resolution_notes=report.resolution_notes,
            created_at=report.created_at))


class SendFarmAdvice(graphene.Mutation):
    """Direct message from officer to every member of one caseload farm."""

    class Arguments:
        farm_id = graphene.ID(required=True)
        title = graphene.String(required=True)
        message = graphene.String(required=True)
        priority = graphene.String()

    recipients = graphene.Int()

    def mutate(self, info, farm_id, title, message, priority=None):
        from apps.notifications.models import Notification
        user = _require_officer(info)
        farm = _caseload_farm(user, farm_id)
        pr = (priority or 'info').strip()
        if pr not in ('info', 'warning', 'critical'):
            raise Exception('Invalid priority')
        members = list(Profile.objects.filter(organization=farm, is_active=True))
        Notification.objects.bulk_create([
            Notification(recipient=p, title=title.strip()[:200],
                         message=f'{message.strip()}\n\n— {user.full_name}, {user.organization.name}',
                         category='system', priority=pr, action_url='/notifications')
            for p in members
        ])
        return SendFarmAdvice(recipients=len(members))


class ExtensionMutation(graphene.ObjectType):
    assign_caseload_farm = AssignCaseloadFarm.Field()
    remove_caseload_farm = RemoveCaseloadFarm.Field()
    log_extension_visit = LogExtensionVisit.Field()
    complete_follow_up = CompleteFollowUp.Field()
    resolve_farmer_report = ResolveFarmerReport.Field()
    send_farm_advice = SendFarmAdvice.Field()
