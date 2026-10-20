import json

import graphene

from . import service


def _ip(info):
    meta = getattr(info.context, 'META', {}) or {}
    fwd = meta.get('HTTP_X_FORWARDED_FOR', '')
    return (fwd.split(',')[0].strip() if fwd else meta.get('REMOTE_ADDR', '')) or 'unknown'


def _load(raw):
    if raw is None or raw == '':
        return None
    return json.loads(raw) if isinstance(raw, str) else raw


class AssistantQuery(graphene.ObjectType):
    assistant_status = graphene.JSONString(description='Whether the AI guide uses a language model or the built-in guide search.')

    def resolve_assistant_status(self, info):
        return {'model': service.available(), 'dailyLimit': service.DAILY_LIMIT}


class AskAssistant(graphene.Mutation):
    class Arguments:
        question = graphene.String(required=True)
        history = graphene.JSONString(description='Earlier turns: [{role, content}]')
        context = graphene.JSONString(description='accountType, page, steps, enterprises, mode, lesson')
        conversation_id = graphene.String()

    result = graphene.JSONString()

    def mutate(self, info, question, history=None, context=None, conversation_id=None):
        user = info.context.user
        return AskAssistant(result=service.ask(
            None if user.is_anonymous else user, _ip(info), question,
            history=_load(history), context=_load(context), conversation_id=conversation_id,
        ))


class AssistantMutation(graphene.ObjectType):
    ask_assistant = AskAssistant.Field()
