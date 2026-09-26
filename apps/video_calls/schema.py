import graphene
from graphene_django import DjangoObjectType
from django.contrib.auth import get_user_model

from .models import VideoCall
from . import services

User = get_user_model()


# ─── Types ────────────────────────────────────────────────────────────────────

class VideoCallType(DjangoObjectType):
    class Meta:
        model = VideoCall
        fields = ['id', 'room_name', 'provider_name', 'subject', 'status',
                  'started_at', 'joined_at', 'ended_at']


class StartCallResult(graphene.ObjectType):
    success      = graphene.Boolean()
    error        = graphene.String()
    call         = graphene.Field(VideoCallType)
    room_name    = graphene.String()
    jitsi_domain = graphene.String()
    token        = graphene.String()


class JoinCallResult(graphene.ObjectType):
    success      = graphene.Boolean()
    error        = graphene.String()
    call         = graphene.Field(VideoCallType)
    room_name    = graphene.String()
    jitsi_domain = graphene.String()
    token        = graphene.String()


class EndCallResult(graphene.ObjectType):
    success = graphene.Boolean()
    error   = graphene.String()
    call    = graphene.Field(VideoCallType)


# ─── Mutations ────────────────────────────────────────────────────────────────

def _require_auth(info):
    user = info.context.user
    if user.is_anonymous:
        raise Exception('Authentication required')
    return user


class StartVideoCall(graphene.Mutation):
    """
    Initiates a video consultation.  Pass provider_user_id if you know the
    Django user who owns the provider profile; otherwise the call is open and
    the counterpart must join by call ID.
    """
    class Arguments:
        provider_user_id = graphene.String(required=False)
        provider_id      = graphene.String(required=False)
        provider_name    = graphene.String(required=False)
        subject          = graphene.String(required=False)

    Output = StartCallResult

    def mutate(self, info, provider_user_id=None, provider_id=None,
               provider_name='', subject=''):
        initiator = _require_auth(info)
        counterpart = None
        if provider_user_id:
            try:
                counterpart = User.objects.get(pk=provider_user_id)
            except User.DoesNotExist:
                return StartCallResult(success=False, error='Provider user not found')

        call, token = services.start_call(
            initiator=initiator,
            counterpart_user=counterpart,
            provider_id=provider_id,
            provider_name=provider_name,
            subject=subject,
        )
        return StartCallResult(
            success=True,
            call=call,
            room_name=call.room_name,
            jitsi_domain=services._jitsi_domain(),
            token=token,
        )


class JoinVideoCall(graphene.Mutation):
    """Join an existing call by its ID (from an incoming-call notification)."""
    class Arguments:
        call_id = graphene.String(required=True)

    Output = JoinCallResult

    def mutate(self, info, call_id):
        user = _require_auth(info)
        try:
            from django.db.models import Q
            # Scope: caller must be a participant (initiator or counterpart) in this call
            call = VideoCall.objects.get(
                Q(pk=call_id) & (Q(initiator=user) | Q(counterpart=user))
            )
        except VideoCall.DoesNotExist:
            return JoinCallResult(success=False, error='Call not found')

        if call.status == 'ended':
            return JoinCallResult(success=False, error='This call has already ended')

        token = services.join_call(call, user)
        return JoinCallResult(
            success=True,
            call=call,
            room_name=call.room_name,
            jitsi_domain=services._jitsi_domain(),
            token=token,
        )


class EndVideoCall(graphene.Mutation):
    """End a call — called when the Jitsi room fires readyToClose."""
    class Arguments:
        call_id = graphene.String(required=True)

    Output = EndCallResult

    def mutate(self, info, call_id):
        user = _require_auth(info)
        try:
            from django.db.models import Q
            # Scope: caller must be a participant (initiator or counterpart) in this call
            call = VideoCall.objects.get(
                Q(pk=call_id) & (Q(initiator=user) | Q(counterpart=user))
            )
        except VideoCall.DoesNotExist:
            return EndCallResult(success=False, error='Call not found')

        call = services.end_call(call)
        return EndCallResult(success=True, call=call)


# ─── Queries ──────────────────────────────────────────────────────────────────

class VideoCallQuery(graphene.ObjectType):
    my_video_calls = graphene.List(
        VideoCallType,
        status=graphene.String(),
        limit=graphene.Int(),
    )
    video_call = graphene.Field(VideoCallType, call_id=graphene.String(required=True))

    def resolve_my_video_calls(self, info, status=None, limit=20):
        user = _require_auth(info)
        from django.db.models import Q
        qs = VideoCall.objects.filter(Q(initiator=user) | Q(counterpart=user))
        if status:
            qs = qs.filter(status=status)
        return qs[:limit]

    def resolve_video_call(self, info, call_id):
        user = _require_auth(info)
        try:
            from django.db.models import Q
            # Scope: caller must be a participant (initiator or counterpart) in this call
            return VideoCall.objects.get(
                Q(pk=call_id) & (Q(initiator=user) | Q(counterpart=user))
            )
        except VideoCall.DoesNotExist:
            return None


class VideoCallMutation(graphene.ObjectType):
    start_video_call = StartVideoCall.Field()
    join_video_call  = JoinVideoCall.Field()
    end_video_call   = EndVideoCall.Field()
