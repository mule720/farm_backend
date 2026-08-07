import graphene
from graphene_django import DjangoObjectType
from django.utils import timezone
from .models import AIRecommendation
from .engine import generate_recommendations


class AIRecommendationType(DjangoObjectType):
    class Meta:
        model = AIRecommendation
        fields = ['id', 'enterprise', 'batch', 'title', 'detail',
                  'recommendation_type', 'urgency', 'impact', 'data_sources',
                  'is_actioned', 'actioned_at', 'actioned_by', 'model_version',
                  'generated_at', 'expires_at']


class IntelligenceSummaryType(graphene.ObjectType):
    total = graphene.Int()
    critical = graphene.Int()
    high = graphene.Int()
    medium = graphene.Int()
    low = graphene.Int()
    actioned = graphene.Int()


def _org(info):
    user = info.context.user
    if user.is_anonymous:
        raise Exception('Not authenticated')
    return user.organization


# ─── Queries ──────────────────────────────────────────────────────────────────

class IntelligenceQuery(graphene.ObjectType):
    recommendations = graphene.List(
        AIRecommendationType,
        enterprise_id=graphene.ID(),
        batch_id=graphene.ID(),
        urgency=graphene.String(),
        recommendation_type=graphene.String(),
        is_actioned=graphene.Boolean(),
        limit=graphene.Int(),
    )
    recommendation = graphene.Field(AIRecommendationType, id=graphene.ID(required=True))
    intelligence_summary = graphene.Field(IntelligenceSummaryType)

    def resolve_recommendations(self, info, enterprise_id=None, batch_id=None,
                                 urgency=None, recommendation_type=None,
                                 is_actioned=None, limit=50):
        org = _org(info)
        qs = AIRecommendation.objects.filter(organization=org)
        if enterprise_id:
            qs = qs.filter(enterprise_id=enterprise_id)
        if batch_id:
            qs = qs.filter(batch_id=batch_id)
        if urgency:
            qs = qs.filter(urgency=urgency)
        if recommendation_type:
            qs = qs.filter(recommendation_type=recommendation_type)
        if is_actioned is not None:
            qs = qs.filter(is_actioned=is_actioned)
        return qs[:limit]

    def resolve_recommendation(self, info, id):
        org = _org(info)
        return AIRecommendation.objects.get(id=id, organization=org)

    def resolve_intelligence_summary(self, info):
        org = _org(info)
        qs = AIRecommendation.objects.filter(organization=org)
        return IntelligenceSummaryType(
            total=qs.count(),
            critical=qs.filter(urgency='critical').count(),
            high=qs.filter(urgency='high').count(),
            medium=qs.filter(urgency='medium').count(),
            low=qs.filter(urgency='low').count(),
            actioned=qs.filter(is_actioned=True).count(),
        )


# ─── Mutations ────────────────────────────────────────────────────────────────

class GenerateRecommendations(graphene.Mutation):
    class Arguments:
        enterprise_id = graphene.ID()
        batch_id = graphene.ID()

    recommendations = graphene.List(AIRecommendationType)
    count = graphene.Int()

    def mutate(self, info, enterprise_id=None, batch_id=None):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        recs = generate_recommendations(user.organization, enterprise_id, batch_id, user)
        return GenerateRecommendations(recommendations=recs, count=len(recs))


class ActionRecommendation(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)

    recommendation = graphene.Field(AIRecommendationType)

    def mutate(self, info, id):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        rec = AIRecommendation.objects.get(id=id, organization=user.organization)
        rec.is_actioned = True
        rec.actioned_at = timezone.now()
        rec.actioned_by = user
        rec.save()
        return ActionRecommendation(recommendation=rec)


class DismissRecommendation(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)

    success = graphene.Boolean()

    def mutate(self, info, id):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        AIRecommendation.objects.get(id=id, organization=user.organization).delete()
        return DismissRecommendation(success=True)


class IntelligenceMutation(graphene.ObjectType):
    generate_recommendations = GenerateRecommendations.Field()
    action_recommendation = ActionRecommendation.Field()
    dismiss_recommendation = DismissRecommendation.Field()
