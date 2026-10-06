"""Shared farm workspace — one copy per organisation, readable and writable by every member."""
import json

import graphene

from .models import OrgWorkspace


def _member(info):
    u = info.context.user
    if u.is_anonymous:
        raise Exception('Not authenticated')
    if not u.organization_id:
        raise Exception('Account has no organisation')
    return u


def _load(raw):
    """Accept either a JSON string (graphene JSONString) or an already-parsed value."""
    if raw is None:
        return None
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


class WorkspaceType(graphene.ObjectType):
    org_data = graphene.JSONString()
    cycles = graphene.JSONString()
    edit_requests = graphene.JSONString()
    updated_at = graphene.DateTime()


class WorkspaceQuery(graphene.ObjectType):
    workspace = graphene.Field(WorkspaceType, description="This organisation's shared farm workspace, or null if not set up yet")

    def resolve_workspace(self, info):
        u = _member(info)
        ws = OrgWorkspace.objects.filter(organization_id=u.organization_id).first()
        if not ws or not ws.org_data:
            return None
        return WorkspaceType(org_data=ws.org_data, cycles=ws.cycles, edit_requests=ws.edit_requests, updated_at=ws.updated_at)


class SaveWorkspaceInput(graphene.InputObjectType):
    org_data = graphene.JSONString()
    cycles = graphene.JSONString()
    edit_requests = graphene.JSONString()


class SaveWorkspace(graphene.Mutation):
    """Partial save: only the parts supplied are replaced."""
    class Arguments:
        input = SaveWorkspaceInput(required=True)

    ok = graphene.Boolean()
    updated_at = graphene.DateTime()

    def mutate(self, info, input):
        u = _member(info)
        ws, _ = OrgWorkspace.objects.get_or_create(organization_id=u.organization_id)
        org_data = _load(input.get('org_data'))
        cycles = _load(input.get('cycles'))
        edits = _load(input.get('edit_requests'))
        if org_data is not None:
            if not isinstance(org_data, dict):
                raise Exception('orgData must be an object')
            # The workspace id is the organisation id — never let a client re-key it
            org_data['id'] = str(u.organization_id)
            ws.org_data = org_data
        if cycles is not None:
            if not isinstance(cycles, list):
                raise Exception('cycles must be a list')
            ws.cycles = cycles
        if edits is not None:
            if not isinstance(edits, list):
                raise Exception('editRequests must be a list')
            ws.edit_requests = edits
        ws.updated_by = u
        ws.save()
        return SaveWorkspace(ok=True, updated_at=ws.updated_at)


class ResetWorkspace(graphene.Mutation):
    """Erase the organisation's workspace so onboarding runs again. Org admins / directors only."""
    ok = graphene.Boolean()

    def mutate(self, info):
        u = _member(info)
        if not (u.is_org_admin or u.role in ('director', 'owner', 'saas_admin')):
            raise Exception('Only an organisation administrator can reset the workspace')
        OrgWorkspace.objects.filter(organization_id=u.organization_id).delete()
        return ResetWorkspace(ok=True)


class WorkspaceMutation(graphene.ObjectType):
    save_workspace = SaveWorkspace.Field()
    reset_workspace = ResetWorkspace.Field()
