import graphene
from graphene_django import DjangoObjectType
from .models import CarbonEntry, WaterUsageEntry, CertificationRecord, ComplianceTask, AuditRecord
def _org(info):
    user = info.context.user
    if user.is_anonymous:
        raise Exception('Not authenticated')
    return user.organization
from django.db.models import Sum


class CarbonEntryType(DjangoObjectType):
    class Meta:
        model = CarbonEntry
        fields = '__all__'


class WaterUsageEntryType(DjangoObjectType):
    class Meta:
        model = WaterUsageEntry
        fields = '__all__'


class CertificationRecordType(DjangoObjectType):
    class Meta:
        model = CertificationRecord
        fields = '__all__'


class ComplianceTaskType(DjangoObjectType):
    class Meta:
        model = ComplianceTask
        fields = '__all__'


class AuditRecordType(DjangoObjectType):
    class Meta:
        model = AuditRecord
        fields = '__all__'


class CarbonSummaryType(graphene.ObjectType):
    total_emissions_co2e_kg = graphene.Float()
    total_offsets_co2e_kg = graphene.Float()
    net_co2e_kg = graphene.Float()
    total_credit_value = graphene.Float()


class SustainabilityQuery(graphene.ObjectType):
    carbon_entries = graphene.List(CarbonEntryType, entry_type=graphene.String(), enterprise_id=graphene.UUID())
    carbon_summary = graphene.Field(CarbonSummaryType)
    water_entries = graphene.List(WaterUsageEntryType, use_type=graphene.String(), limit=graphene.Int())
    certifications = graphene.List(CertificationRecordType, status=graphene.String())
    certification = graphene.Field(CertificationRecordType, id=graphene.UUID(required=True))
    compliance_tasks = graphene.List(ComplianceTaskType, status=graphene.String())
    overdue_tasks = graphene.List(ComplianceTaskType)
    audit_records = graphene.List(AuditRecordType, certification_id=graphene.UUID())

    def resolve_carbon_entries(self, info, entry_type=None, enterprise_id=None):
        qs = CarbonEntry.objects.filter(organization=_org(info))
        if entry_type:
            qs = qs.filter(entry_type=entry_type)
        if enterprise_id:
            qs = qs.filter(enterprise_id=enterprise_id)
        return qs

    def resolve_carbon_summary(self, info):
        org = _org(info)
        emissions = CarbonEntry.objects.filter(organization=org, entry_type='emission').aggregate(t=Sum('co2e_kg'))['t'] or 0
        offsets = CarbonEntry.objects.filter(organization=org, entry_type='offset').aggregate(t=Sum('co2e_kg'))['t'] or 0
        credit_value = CarbonEntry.objects.filter(organization=org, entry_type='offset').aggregate(t=Sum('credit_value'))['t'] or 0
        return CarbonSummaryType(
            total_emissions_co2e_kg=float(emissions),
            total_offsets_co2e_kg=float(offsets),
            net_co2e_kg=float(emissions) - float(offsets),
            total_credit_value=float(credit_value),
        )

    def resolve_water_entries(self, info, use_type=None, limit=100):
        qs = WaterUsageEntry.objects.filter(organization=_org(info))
        if use_type:
            qs = qs.filter(use_type=use_type)
        return qs[:limit]

    def resolve_certifications(self, info, status=None):
        qs = CertificationRecord.objects.filter(organization=_org(info))
        if status:
            qs = qs.filter(status=status)
        return qs

    def resolve_certification(self, info, id):
        return CertificationRecord.objects.get(pk=id, organization=_org(info))

    def resolve_compliance_tasks(self, info, status=None):
        qs = ComplianceTask.objects.filter(organization=_org(info))
        if status:
            qs = qs.filter(status=status)
        return qs

    def resolve_overdue_tasks(self, info):
        from django.utils import timezone
        return ComplianceTask.objects.filter(
            organization=_org(info),
            status__in=['open', 'in_progress'],
            due_date__lt=timezone.now().date(),
        )

    def resolve_audit_records(self, info, certification_id=None):
        qs = AuditRecord.objects.filter(organization=_org(info))
        if certification_id:
            qs = qs.filter(certification_id=certification_id)
        return qs


class LogCarbonEntry(graphene.Mutation):
    class Arguments:
        category = graphene.String(required=True)
        description = graphene.String(required=True)
        entry_type = graphene.String()
        quantity = graphene.Float(required=True)
        unit = graphene.String(required=True)
        emission_factor = graphene.Float()
        co2e_kg = graphene.Float()
        entry_date = graphene.Date(required=True)
        enterprise_id = graphene.UUID()
        credit_value = graphene.Float()

    entry = graphene.Field(CarbonEntryType)

    def mutate(self, info, category, description, quantity, unit, entry_date, **kwargs):
        entry = CarbonEntry(
            organization=_org(info),
            category=category, description=description,
            quantity=quantity, unit=unit, entry_date=entry_date,
            created_by=info.context.user,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        entry.save()
        return LogCarbonEntry(entry=entry)


class LogWaterUsage(graphene.Mutation):
    class Arguments:
        source = graphene.String(required=True)
        use_type = graphene.String(required=True)
        volume_m3 = graphene.Float(required=True)
        entry_date = graphene.Date(required=True)
        cost = graphene.Float()
        enterprise_id = graphene.UUID()
        notes = graphene.String()

    entry = graphene.Field(WaterUsageEntryType)

    def mutate(self, info, source, use_type, volume_m3, entry_date, **kwargs):
        entry = WaterUsageEntry.objects.create(
            organization=_org(info),
            source=source, use_type=use_type,
            volume_m3=volume_m3, entry_date=entry_date,
            created_by=info.context.user,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        return LogWaterUsage(entry=entry)


class CreateCertification(graphene.Mutation):
    class Arguments:
        certification_name = graphene.String(required=True)
        certifying_body = graphene.String(required=True)
        status = graphene.String()
        issue_date = graphene.Date()
        expiry_date = graphene.Date()
        scope = graphene.String()
        renewal_cost = graphene.Float()

    certification = graphene.Field(CertificationRecordType)

    def mutate(self, info, certification_name, certifying_body, **kwargs):
        cert = CertificationRecord.objects.create(
            organization=_org(info),
            certification_name=certification_name,
            certifying_body=certifying_body,
            created_by=info.context.user,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        return CreateCertification(certification=cert)


class CreateComplianceTask(graphene.Mutation):
    class Arguments:
        title = graphene.String(required=True)
        due_date = graphene.Date(required=True)
        description = graphene.String()
        priority = graphene.String()
        certification_id = graphene.UUID()
        assigned_to_id = graphene.UUID()

    task = graphene.Field(ComplianceTaskType)

    def mutate(self, info, title, due_date, **kwargs):
        task = ComplianceTask.objects.create(
            organization=_org(info),
            title=title, due_date=due_date,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        return CreateComplianceTask(task=task)


class UpdateComplianceTask(graphene.Mutation):
    class Arguments:
        id = graphene.UUID(required=True)
        status = graphene.String()
        notes = graphene.String()
        evidence_url = graphene.String()

    task = graphene.Field(ComplianceTaskType)

    def mutate(self, info, id, **kwargs):
        task = ComplianceTask.objects.get(pk=id, organization=_org(info))
        for k, v in kwargs.items():
            if v is not None:
                setattr(task, k, v)
        if kwargs.get('status') == 'done':
            from django.utils import timezone
            task.completed_at = timezone.now()
        task.save()
        return UpdateComplianceTask(task=task)


class SustainabilityMutation(graphene.ObjectType):
    log_carbon_entry = LogCarbonEntry.Field()
    log_water_usage = LogWaterUsage.Field()
    create_certification = CreateCertification.Field()
    create_compliance_task = CreateComplianceTask.Field()
    update_compliance_task = UpdateComplianceTask.Field()
