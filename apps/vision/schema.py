import graphene
from graphene_django import DjangoObjectType
from django.utils import timezone
from .models import AIVisionAnalysis, StockCountLog, FarmerReport, DroneFieldReport
from .ai_client import analyse_image


# ─── Types ────────────────────────────────────────────────────────────────────

class AIVisionAnalysisType(DjangoObjectType):
    class Meta:
        model = AIVisionAnalysis
        fields = ['id', 'enterprise', 'batch', 'analysis_type', 'image_url',
                  'user_description', 'diagnosis', 'severity', 'confidence_pct',
                  'findings', 'recommendations', 'ai_summary', 'extra_data',
                  'is_public', 'submitted_by', 'ai_model_used', 'created_at']


class StockCountLogType(DjangoObjectType):
    class Meta:
        model = StockCountLog
        fields = ['id', 'enterprise', 'batch', 'device', 'counted_quantity',
                  'expected_quantity', 'discrepancy', 'discrepancy_pct',
                  'status', 'is_authorized', 'authorization_ref',
                  'snapshot_url', 'vision_analysis', 'notes',
                  'counted_by', 'reviewed_by', 'counted_at', 'reviewed_at']


class FarmerReportType(DjangoObjectType):
    class Meta:
        model = FarmerReport
        fields = ['id', 'enterprise', 'category', 'title', 'description',
                  'crop_or_animal', 'location_hint', 'image_url',
                  'vision_analysis', 'is_resolved', 'resolution_notes',
                  'visibility', 'helpful_count', 'submitted_by',
                  'created_at', 'updated_at']


class DroneFieldReportType(DjangoObjectType):
    class Meta:
        model = DroneFieldReport
        fields = ['id', 'flight', 'enterprise', 'overall_health', 'health_score',
                  'zones', 'detected_issues', 'action_plan',
                  'estimated_yield_impact_pct', 'ai_summary',
                  'vision_analysis', 'generated_at']


def _org(info):
    user = info.context.user
    if user.is_anonymous:
        raise Exception('Not authenticated')
    return user.organization


# ─── Queries ──────────────────────────────────────────────────────────────────

class VisionQuery(graphene.ObjectType):
    vision_analyses = graphene.List(
        AIVisionAnalysisType,
        analysis_type=graphene.String(),
        enterprise_id=graphene.ID(),
        limit=graphene.Int(),
    )
    vision_analysis = graphene.Field(AIVisionAnalysisType, id=graphene.ID(required=True))

    stock_count_logs = graphene.List(
        StockCountLogType,
        enterprise_id=graphene.ID(),
        status=graphene.String(),
        limit=graphene.Int(),
    )
    stock_count_alerts = graphene.List(
        StockCountLogType,
        enterprise_id=graphene.ID(),
    )

    farmer_reports = graphene.List(
        FarmerReportType,
        category=graphene.String(),
        visibility=graphene.String(),
        enterprise_id=graphene.ID(),
        limit=graphene.Int(),
    )
    community_reports = graphene.List(
        FarmerReportType,
        category=graphene.String(),
        limit=graphene.Int(),
    )

    drone_field_reports = graphene.List(
        DroneFieldReportType,
        enterprise_id=graphene.ID(),
        limit=graphene.Int(),
    )
    drone_field_report = graphene.Field(DroneFieldReportType, id=graphene.ID(required=True))

    def resolve_vision_analyses(self, info, analysis_type=None, enterprise_id=None, limit=20):
        org = _org(info)
        qs = AIVisionAnalysis.objects.filter(organization=org)
        if analysis_type:
            qs = qs.filter(analysis_type=analysis_type)
        if enterprise_id:
            qs = qs.filter(enterprise_id=enterprise_id)
        return qs[:limit]

    def resolve_vision_analysis(self, info, id):
        org = _org(info)
        return AIVisionAnalysis.objects.get(id=id, organization=org)

    def resolve_stock_count_logs(self, info, enterprise_id=None, status=None, limit=50):
        org = _org(info)
        qs = StockCountLog.objects.filter(organization=org)
        if enterprise_id:
            qs = qs.filter(enterprise_id=enterprise_id)
        if status:
            qs = qs.filter(status=status)
        return qs[:limit]

    def resolve_stock_count_alerts(self, info, enterprise_id=None):
        org = _org(info)
        qs = StockCountLog.objects.filter(organization=org, status='discrepancy')
        if enterprise_id:
            qs = qs.filter(enterprise_id=enterprise_id)
        return qs[:100]

    def resolve_farmer_reports(self, info, category=None, visibility=None,
                                enterprise_id=None, limit=30):
        org = _org(info)
        qs = FarmerReport.objects.filter(organization=org)
        if category:
            qs = qs.filter(category=category)
        if visibility:
            qs = qs.filter(visibility=visibility)
        if enterprise_id:
            qs = qs.filter(enterprise_id=enterprise_id)
        return qs[:limit]

    def resolve_community_reports(self, info, category=None, limit=30):
        # Public reports from ALL organizations
        qs = FarmerReport.objects.filter(visibility='community')
        if category:
            qs = qs.filter(category=category)
        return qs.order_by('-helpful_count', '-created_at')[:limit]

    def resolve_drone_field_reports(self, info, enterprise_id=None, limit=20):
        org = _org(info)
        qs = DroneFieldReport.objects.filter(organization=org)
        if enterprise_id:
            qs = qs.filter(enterprise_id=enterprise_id)
        return qs[:limit]

    def resolve_drone_field_report(self, info, id):
        org = _org(info)
        return DroneFieldReport.objects.get(id=id, organization=org)


# ─── Mutations ────────────────────────────────────────────────────────────────

class AnalyzeImage(graphene.Mutation):
    """
    Trigger AI vision analysis on an image URL.
    The image must be publicly accessible.
    Results are persisted and returned.
    """
    class Arguments:
        image_url = graphene.String(required=True)
        analysis_type = graphene.String(required=True)
        user_description = graphene.String()
        enterprise_id = graphene.ID()
        batch_id = graphene.ID()
        is_public = graphene.Boolean()
        extra_context = graphene.String()

    analysis = graphene.Field(AIVisionAnalysisType)

    def mutate(self, info, image_url, analysis_type, user_description='',
               enterprise_id=None, batch_id=None, is_public=False, extra_context=''):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')

        # Build context string for AI
        context_parts = []
        if enterprise_id:
            try:
                from apps.enterprises.models import Enterprise
                ent = Enterprise.objects.get(id=enterprise_id, organization=user.organization)
                context_parts.append(f'Enterprise: {ent.name} ({ent.category})')
            except Exception:
                pass
        if extra_context:
            context_parts.append(extra_context)

        result = analyse_image(
            image_url=image_url,
            analysis_type=analysis_type,
            user_description=user_description,
            extra_context='\n'.join(context_parts),
        )

        obj = AIVisionAnalysis.objects.create(
            organization=user.organization,
            enterprise_id=enterprise_id,
            batch_id=batch_id,
            analysis_type=analysis_type,
            image_url=image_url,
            user_description=user_description,
            diagnosis=result.get('diagnosis', ''),
            severity=result.get('severity', 'none'),
            confidence_pct=result.get('confidence_pct', 0),
            findings=result.get('findings', []),
            recommendations=result.get('recommendations', []),
            ai_summary=result.get('ai_summary', ''),
            extra_data=result.get('extra_data', {}),
            is_public=is_public,
            submitted_by=user,
            ai_model_used=result.get('ai_model_used', ''),
        )

        # Auto-create an AI recommendation from the findings
        if result.get('severity') in ('high', 'critical') and enterprise_id:
            from apps.intelligence.models import AIRecommendation
            AIRecommendation.objects.create(
                organization=user.organization,
                enterprise_id=enterprise_id,
                batch_id=batch_id,
                title=f'Vision Alert: {result.get("diagnosis", "Issue detected")}',
                detail=result.get('ai_summary', ''),
                recommendation_type='health' if 'disease' in analysis_type else 'operational',
                urgency='critical' if result.get('severity') == 'critical' else 'high',
                impact='\n'.join(result.get('recommendations', [])),
                data_sources=['vision_ai'],
                model_version=result.get('ai_model_used', ''),
            )

        return AnalyzeImage(analysis=obj)


class LogStockCount(graphene.Mutation):
    """
    Record a camera or manual livestock count.
    Automatically compares against batch records and flags discrepancies.
    """
    class Arguments:
        enterprise_id = graphene.ID(required=True)
        batch_id = graphene.ID()
        device_id = graphene.ID()
        counted_quantity = graphene.Float(required=True)
        snapshot_url = graphene.String()
        notes = graphene.String()
        image_url = graphene.String()

    log = graphene.Field(StockCountLogType)
    alert_created = graphene.Boolean()

    def mutate(self, info, enterprise_id, counted_quantity, batch_id=None,
               device_id=None, snapshot_url='', notes='', image_url=''):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')

        # Get expected quantity from the active batch
        expected = 0
        active_batch = None
        if batch_id:
            from apps.enterprises.models import EnterpriseBatch
            try:
                active_batch = EnterpriseBatch.objects.get(id=batch_id, organization=user.organization)
                expected = float(active_batch.quantity)
            except EnterpriseBatch.DoesNotExist:
                pass
        else:
            from apps.enterprises.models import EnterpriseBatch
            active = EnterpriseBatch.objects.filter(
                enterprise_id=enterprise_id,
                organization=user.organization,
                status='active',
            ).first()
            if active:
                active_batch = active
                expected = float(active.quantity)
                batch_id = str(active.id)

        # Run AI count analysis if image provided
        vision_obj = None
        if image_url:
            result = analyse_image(image_url, 'livestock_count', notes)
            vision_obj = AIVisionAnalysis.objects.create(
                organization=user.organization,
                enterprise_id=enterprise_id,
                batch_id=batch_id,
                analysis_type='livestock_count',
                image_url=image_url,
                user_description=notes,
                diagnosis=result.get('diagnosis', ''),
                severity=result.get('severity', 'none'),
                confidence_pct=result.get('confidence_pct', 0),
                findings=result.get('findings', []),
                recommendations=result.get('recommendations', []),
                ai_summary=result.get('ai_summary', ''),
                extra_data=result.get('extra_data', {}),
                submitted_by=user,
                ai_model_used=result.get('ai_model_used', ''),
            )
            # Use AI-detected count if we ran the model
            ai_count = result.get('extra_data', {}).get('total_counted')
            if ai_count is not None:
                counted_quantity = float(ai_count)

        log = StockCountLog.objects.create(
            organization=user.organization,
            enterprise_id=enterprise_id,
            batch_id=batch_id,
            device_id=device_id,
            counted_quantity=counted_quantity,
            expected_quantity=expected,
            snapshot_url=snapshot_url,
            vision_analysis=vision_obj,
            notes=notes,
            counted_by=user,
        )

        # Create security alert if flagged
        alert_created = False
        if log.status == 'discrepancy':
            from apps.devices.models import SecurityAlert
            SecurityAlert.objects.create(
                organization=user.organization,
                source='camera',
                source_id=log.id,
                severity='critical',
                title=f'Unauthorized Stock Movement — {log.enterprise.name if log.enterprise else "Unknown"}',
                detail=(
                    f'Camera count: {counted_quantity:.0f} animals. '
                    f'Expected: {expected:.0f}. '
                    f'Missing {log.discrepancy:.0f} ({log.discrepancy_pct:.1f}%) '
                    f'without a sales order. Immediate investigation required.'
                ),
            )
            alert_created = True

        return LogStockCount(log=log, alert_created=alert_created)


class AuthorizeStockMovement(graphene.Mutation):
    """Mark a stock count discrepancy as authorized (e.g., matches a sales order)."""
    class Arguments:
        log_id = graphene.ID(required=True)
        authorization_ref = graphene.String(required=True)
        notes = graphene.String()

    log = graphene.Field(StockCountLogType)

    def mutate(self, info, log_id, authorization_ref, notes=''):
        user = info.context.user
        if user.role not in ('director', 'production_manager', 'supervisor', 'sales_manager', 'saas_admin'):
            raise Exception('Permission denied')
        log = StockCountLog.objects.get(id=log_id, organization=user.organization)
        log.is_authorized = True
        log.authorization_ref = authorization_ref
        log.status = 'authorized'
        log.reviewed_by = user
        log.reviewed_at = timezone.now()
        if notes:
            log.notes = (log.notes + '\n' + notes).strip()
        log.save()
        return AuthorizeStockMovement(log=log)


class SubmitFarmerReport(graphene.Mutation):
    """Submit a farmer-reported issue with optional AI analysis."""
    class Arguments:
        category = graphene.String(required=True)
        title = graphene.String(required=True)
        description = graphene.String()
        crop_or_animal = graphene.String()
        location_hint = graphene.String()
        image_url = graphene.String()
        enterprise_id = graphene.ID()
        visibility = graphene.String()
        run_ai_analysis = graphene.Boolean()

    report = graphene.Field(FarmerReportType)

    def mutate(self, info, category, title, description='', crop_or_animal='',
               location_hint='', image_url='', enterprise_id=None,
               visibility='private', run_ai_analysis=True):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')

        vision_obj = None
        if image_url and run_ai_analysis:
            # Map report category to analysis type
            type_map = {
                'crop_disease': 'crop_disease',
                'pest': 'pest_identification',
                'animal_disease': 'livestock_health',
                'nutritional': 'crop_disease',
                'yield_issue': 'field_survey',
                'weed': 'weed_detection',
                'soil': 'soil_assessment',
            }
            atype = type_map.get(category, 'general')
            ctx = f'Crop/animal: {crop_or_animal}. Location: {location_hint}.' if crop_or_animal else ''
            result = analyse_image(image_url, atype, description, ctx)
            vision_obj = AIVisionAnalysis.objects.create(
                organization=user.organization,
                enterprise_id=enterprise_id,
                analysis_type=atype,
                image_url=image_url,
                user_description=description,
                diagnosis=result.get('diagnosis', ''),
                severity=result.get('severity', 'none'),
                confidence_pct=result.get('confidence_pct', 0),
                findings=result.get('findings', []),
                recommendations=result.get('recommendations', []),
                ai_summary=result.get('ai_summary', ''),
                extra_data=result.get('extra_data', {}),
                is_public=(visibility == 'community'),
                submitted_by=user,
                ai_model_used=result.get('ai_model_used', ''),
            )

        report = FarmerReport.objects.create(
            organization=user.organization,
            enterprise_id=enterprise_id,
            category=category,
            title=title,
            description=description,
            crop_or_animal=crop_or_animal,
            location_hint=location_hint,
            image_url=image_url,
            vision_analysis=vision_obj,
            visibility=visibility,
            submitted_by=user,
        )
        return SubmitFarmerReport(report=report)


class MarkReportHelpful(graphene.Mutation):
    class Arguments:
        report_id = graphene.ID(required=True)

    report = graphene.Field(FarmerReportType)

    def mutate(self, info, report_id):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        report = FarmerReport.objects.get(id=report_id, visibility='community')
        report.helpful_count += 1
        report.save(update_fields=['helpful_count'])
        return MarkReportHelpful(report=report)


class ResolveReport(graphene.Mutation):
    class Arguments:
        report_id = graphene.ID(required=True)
        resolution_notes = graphene.String()

    report = graphene.Field(FarmerReportType)

    def mutate(self, info, report_id, resolution_notes=''):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        report = FarmerReport.objects.get(id=report_id, organization=user.organization)
        report.is_resolved = True
        report.resolution_notes = resolution_notes
        report.save()
        return ResolveReport(report=report)


class AnalyzeDroneFlight(graphene.Mutation):
    """Run AI field analysis on a completed drone flight's images."""
    class Arguments:
        flight_id = graphene.ID(required=True)
        image_url = graphene.String(required=True)
        user_notes = graphene.String()

    field_report = graphene.Field(DroneFieldReportType)

    def mutate(self, info, flight_id, image_url, user_notes=''):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')

        from apps.devices.models import DroneFlight
        flight = DroneFlight.objects.get(id=flight_id, organization=user.organization)

        ctx = f'Flight type: {flight.flight_type}. Area covered: {flight.area_covered_ha} ha.' if flight.area_covered_ha else ''
        result = analyse_image(image_url, 'field_survey', user_notes, ctx)

        vision_obj = AIVisionAnalysis.objects.create(
            organization=user.organization,
            enterprise=flight.enterprise,
            analysis_type='field_survey',
            image_url=image_url,
            user_description=user_notes,
            diagnosis=result.get('diagnosis', ''),
            severity=result.get('severity', 'none'),
            confidence_pct=result.get('confidence_pct', 0),
            findings=result.get('findings', []),
            recommendations=result.get('recommendations', []),
            ai_summary=result.get('ai_summary', ''),
            extra_data=result.get('extra_data', {}),
            submitted_by=user,
            ai_model_used=result.get('ai_model_used', ''),
        )

        extra = result.get('extra_data', {})
        health_score = extra.get('overall_health_score', 70)
        if health_score >= 85:
            overall = 'excellent'
        elif health_score >= 70:
            overall = 'good'
        elif health_score >= 55:
            overall = 'fair'
        elif health_score >= 35:
            overall = 'poor'
        else:
            overall = 'critical'

        field_report = DroneFieldReport.objects.create(
            organization=user.organization,
            flight=flight,
            enterprise=flight.enterprise,
            overall_health=overall,
            health_score=health_score,
            zones=[{'zone': f.get('title', ''), 'observation': f.get('detail', '')} for f in result.get('findings', [])],
            detected_issues=extra.get('detected_issues', []),
            action_plan=result.get('recommendations', []),
            estimated_yield_impact_pct=None,
            ai_summary=result.get('ai_summary', ''),
            vision_analysis=vision_obj,
        )

        # Persist findings back to the flight
        flight.findings = {
            'health_score': health_score,
            'diagnosis': result.get('diagnosis', ''),
            'issues': extra.get('detected_issues', []),
        }
        flight.save(update_fields=['findings'])

        # Create an AI recommendation if issues are significant
        if result.get('severity') in ('medium', 'high', 'critical') and flight.enterprise_id:
            from apps.intelligence.models import AIRecommendation
            AIRecommendation.objects.create(
                organization=user.organization,
                enterprise=flight.enterprise,
                title=f'Drone Survey Alert: {result.get("diagnosis", "Field issues detected")}',
                detail=result.get('ai_summary', ''),
                recommendation_type='operational',
                urgency='high' if result.get('severity') in ('high', 'critical') else 'medium',
                impact=extra.get('yield_impact_estimate', ''),
                data_sources=['drone_survey', 'vision_ai'],
                model_version=result.get('ai_model_used', ''),
            )

        return AnalyzeDroneFlight(field_report=field_report)


# ─── Root ─────────────────────────────────────────────────────────────────────

class VisionMutation(graphene.ObjectType):
    analyze_image = AnalyzeImage.Field()
    log_stock_count = LogStockCount.Field()
    authorize_stock_movement = AuthorizeStockMovement.Field()
    submit_farmer_report = SubmitFarmerReport.Field()
    mark_report_helpful = MarkReportHelpful.Field()
    resolve_report = ResolveReport.Field()
    analyze_drone_flight = AnalyzeDroneFlight.Field()
