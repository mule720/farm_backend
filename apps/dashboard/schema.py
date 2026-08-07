import graphene
from graphene_django import DjangoObjectType
from .models import DashboardWidget, Report
from django.utils import timezone
from datetime import timedelta


class DashboardWidgetType(DjangoObjectType):
    class Meta:
        model = DashboardWidget
        fields = ['id', 'widget_type', 'title', 'data_source', 'widget_size',
                  'widget_order', 'is_enabled', 'color', 'config',
                  'profile', 'created_at', 'updated_at']


class ReportType(DjangoObjectType):
    class Meta:
        model = Report
        fields = ['id', 'name', 'report_type', 'date_from', 'date_to',
                  'parameters', 'output_format', 'file_url', 'status',
                  'enterprise', 'generated_by', 'generated_at']


class DashboardSummaryType(graphene.ObjectType):
    active_enterprises = graphene.Int()
    active_batches = graphene.Int()
    low_stock_items = graphene.Int()
    open_tasks = graphene.Int()
    critical_alerts = graphene.Int()
    total_recommendations = graphene.Int()


class DashboardTrendPointType(graphene.ObjectType):
    label = graphene.String()
    value = graphene.Float()


class DashboardAlertItemType(graphene.ObjectType):
    module = graphene.String()
    msg = graphene.String()
    time = graphene.String()
    type = graphene.String()


class DashboardOrderItemType(graphene.ObjectType):
    id = graphene.ID()
    customer = graphene.String()
    items = graphene.String()
    value = graphene.Float()
    status = graphene.String()


# ─── Inputs ──────────────────────────────────────────────────────────────────

class WidgetInput(graphene.InputObjectType):
    widget_type = graphene.String(required=True)
    title = graphene.String(required=True)
    data_source = graphene.String(required=True)
    widget_size = graphene.String()
    widget_order = graphene.Int()
    is_enabled = graphene.Boolean()
    color = graphene.String()
    config = graphene.JSONString()


class ReportInput(graphene.InputObjectType):
    name = graphene.String(required=True)
    report_type = graphene.String(required=True)
    enterprise_id = graphene.ID()
    date_from = graphene.Date()
    date_to = graphene.Date()
    parameters = graphene.JSONString()
    output_format = graphene.String()


class WidgetOrderInput(graphene.InputObjectType):
    id = graphene.ID(required=True)
    widget_order = graphene.Int(required=True)


def _org(info):
    user = info.context.user
    if user.is_anonymous:
        raise Exception('Not authenticated')
    return user.organization


# ─── Queries ──────────────────────────────────────────────────────────────────

class DashboardQuery(graphene.ObjectType):
    dashboard_widgets = graphene.List(DashboardWidgetType, is_enabled=graphene.Boolean())
    dashboard_summary = graphene.Field(DashboardSummaryType)
    reports = graphene.List(
        ReportType,
        report_type=graphene.String(),
        status=graphene.String(),
    )
    report = graphene.Field(ReportType, id=graphene.ID(required=True))
    dashboard_trend = graphene.List(DashboardTrendPointType)
    dashboard_alerts = graphene.List(DashboardAlertItemType, limit=graphene.Int())
    dashboard_orders = graphene.List(DashboardOrderItemType, limit=graphene.Int())

    def resolve_dashboard_widgets(self, info, is_enabled=None):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        qs = DashboardWidget.objects.filter(organization=user.organization, profile=user)
        if not qs.exists():
            qs = DashboardWidget.objects.filter(organization=user.organization, profile=None)
        if is_enabled is not None:
            qs = qs.filter(is_enabled=is_enabled)
        return qs

    def resolve_dashboard_summary(self, info):
        org = _org(info)
        from apps.enterprises.models import Enterprise, EnterpriseBatch
        from apps.inventory.models import InventoryItem
        from apps.automation.models import Task
        from apps.intelligence.models import AIRecommendation
        from apps.devices.models import SecurityAlert
        from django.db.models import F

        return DashboardSummaryType(
            active_enterprises=Enterprise.objects.filter(organization=org, is_active=True).count(),
            active_batches=EnterpriseBatch.objects.filter(organization=org, status='active').count(),
            low_stock_items=InventoryItem.objects.filter(
                organization=org, current_stock__lte=F('reorder_level')
            ).count(),
            open_tasks=Task.objects.filter(
                organization=org, status__in=['pending', 'in_progress']
            ).count(),
            critical_alerts=SecurityAlert.objects.filter(
                organization=org, severity='critical', is_resolved=False
            ).count(),
            total_recommendations=AIRecommendation.objects.filter(
                organization=org, is_actioned=False
            ).count(),
        )

    def resolve_reports(self, info, report_type=None, status=None):
        org = _org(info)
        qs = Report.objects.filter(organization=org)
        if report_type:
            qs = qs.filter(report_type=report_type)
        if status:
            qs = qs.filter(status=status)
        return qs

    def resolve_report(self, info, id):
        org = _org(info)
        return Report.objects.get(id=id, organization=org)

    def resolve_dashboard_trend(self, info):
        org = _org(info)
        from apps.enterprises.models import EnterpriseBatch

        today = timezone.now().date()
        rows = []
        for i in range(6, -1, -1):
            day = today - timedelta(days=i)
            count = EnterpriseBatch.objects.filter(
                organization=org,
                created_at__date=day,
            ).count()
            # Lightweight signal for chart until monetary analytics endpoint is available
            rows.append(DashboardTrendPointType(label=day.strftime('%a'), value=float(count * 1000)))
        return rows

    def resolve_dashboard_alerts(self, info, limit=6):
        org = _org(info)
        from apps.devices.models import SecurityAlert

        alerts = SecurityAlert.objects.filter(organization=org).order_by('-created_at')[: (limit or 6)]
        out = []
        for a in alerts:
            out.append(
                DashboardAlertItemType(
                    module=(a.source or 'system').title(),
                    msg=a.title,
                    time=a.created_at.strftime('%H:%M'),
                    type=a.severity or 'info',
                )
            )
        return out

    def resolve_dashboard_orders(self, info, limit=6):
        org = _org(info)
        qs = Report.objects.filter(organization=org).order_by('-generated_at')[: (limit or 6)]

        status_map = {
            'ready': 'delivered',
            'processing': 'processing',
            'pending': 'pending',
            'failed': 'pending',
        }

        out = []
        for r in qs:
            out.append(
                DashboardOrderItemType(
                    id=str(r.id),
                    customer=(r.enterprise.name if r.enterprise else 'Farm Account'),
                    items=f"{r.report_type.title()} report",
                    value=float((r.parameters or {}).get('value', 0) or 0),
                    status=status_map.get(r.status, 'scheduled'),
                )
            )
        return out


# ─── Mutations ────────────────────────────────────────────────────────────────

class CreateWidget(graphene.Mutation):
    class Arguments:
        input = WidgetInput(required=True)

    widget = graphene.Field(DashboardWidgetType)

    def mutate(self, info, input):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        widget = DashboardWidget.objects.create(
            organization=user.organization,
            profile=user,
            widget_type=input.widget_type,
            title=input.title,
            data_source=input.data_source,
            widget_size=input.get('widget_size', 'medium'),
            widget_order=input.get('widget_order', 0),
            is_enabled=input.get('is_enabled', True),
            color=input.get('color', ''),
            config=input.get('config') or {},
        )
        return CreateWidget(widget=widget)


class UpdateWidget(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)
        input = WidgetInput(required=True)

    widget = graphene.Field(DashboardWidgetType)

    def mutate(self, info, id, input):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        widget = DashboardWidget.objects.get(id=id, organization=user.organization)
        for k, v in input.items():
            if v is not None:
                setattr(widget, k, v)
        widget.save()
        return UpdateWidget(widget=widget)


class DeleteWidget(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)

    success = graphene.Boolean()

    def mutate(self, info, id):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        DashboardWidget.objects.get(id=id, organization=user.organization, profile=user).delete()
        return DeleteWidget(success=True)


class ReorderWidgets(graphene.Mutation):
    class Arguments:
        orders = graphene.List(WidgetOrderInput, required=True)

    widgets = graphene.List(DashboardWidgetType)

    def mutate(self, info, orders):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        updated = []
        for o in orders:
            w = DashboardWidget.objects.get(id=o.id, organization=user.organization)
            w.widget_order = o.widget_order
            w.save(update_fields=['widget_order'])
            updated.append(w)
        return ReorderWidgets(widgets=updated)


class CreateReport(graphene.Mutation):
    class Arguments:
        input = ReportInput(required=True)

    report = graphene.Field(ReportType)

    def mutate(self, info, input):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        report = Report.objects.create(
            organization=user.organization,
            generated_by=user,
            name=input.name,
            report_type=input.report_type,
            enterprise_id=input.get('enterprise_id'),
            date_from=input.get('date_from'),
            date_to=input.get('date_to'),
            parameters=input.get('parameters') or {},
            output_format=input.get('output_format', 'pdf'),
            status='pending',
        )
        # Trigger async generation
        from .tasks import generate_report_task
        generate_report_task.delay(str(report.id))
        return CreateReport(report=report)


class DashboardMutation(graphene.ObjectType):
    create_widget = CreateWidget.Field()
    update_widget = UpdateWidget.Field()
    delete_widget = DeleteWidget.Field()
    reorder_widgets = ReorderWidgets.Field()
    create_report = CreateReport.Field()
