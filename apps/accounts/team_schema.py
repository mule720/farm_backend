"""Team, permissions, branches and audit — GraphQL surface for every organisation type."""
import json
import re

import graphene
from django.db.models import Count
from django.utils import timezone
from graphene_django import DjangoObjectType

from . import rbac
from .models import Organization, Profile, Branch, AccessAuditLog


def _user(info):
    u = info.context.user
    if u.is_anonymous:
        raise Exception('Not authenticated')
    return u


# ─── Types ────────────────────────────────────────────────────────────────────

class RoleDefType(graphene.ObjectType):
    id = graphene.String()
    label = graphene.String()
    description = graphene.String()
    default_permissions = graphene.JSONString()


class ModuleDefType(graphene.ObjectType):
    id = graphene.String()
    label = graphene.String()
    group = graphene.String()


class RoleCatalogueType(graphene.ObjectType):
    org_type = graphene.String()
    roles = graphene.List(RoleDefType)
    modules = graphene.List(ModuleDefType)
    actions = graphene.List(graphene.String)
    branch_kinds = graphene.List(graphene.List(graphene.String))


class BranchType(DjangoObjectType):
    member_count = graphene.Int()
    kind_display = graphene.String()

    class Meta:
        model = Branch
        fields = ['id', 'name', 'code', 'kind', 'province', 'district', 'address', 'phone', 'is_headquarters', 'is_active', 'created_at']
        convert_choices_to_enum = False

    def resolve_member_count(self, info):
        return self.members.filter(is_active=True).count()

    def resolve_kind_display(self, info):
        return self.get_kind_display()


class TeamMemberType(DjangoObjectType):
    permissions = graphene.JSONString(description='Effective module→actions matrix')
    has_override = graphene.Boolean()
    branch = graphene.Field(BranchType)
    role_label = graphene.String()

    class Meta:
        model = Profile
        fields = ['id', 'email', 'full_name', 'role', 'phone', 'is_active', 'is_org_admin', 'created_at', 'last_login']
        convert_choices_to_enum = False

    def resolve_permissions(self, info):
        return rbac.effective_matrix(self)

    def resolve_has_override(self, info):
        p = (self.preferences or {}).get('permissions') if isinstance(self.preferences, dict) else None
        return bool(p)

    def resolve_role_label(self, info):
        return dict((r, l) for r, l, _ in rbac.roles_for(rbac.org_type_of(self))).get(self.role, self.role)


class AccessAuditLogType(DjangoObjectType):
    actor_name = graphene.String()
    target_name = graphene.String()

    class Meta:
        model = AccessAuditLog
        fields = ['id', 'action', 'detail', 'created_at']

    def resolve_actor_name(self, info):
        return self.actor.full_name if self.actor else 'system'

    def resolve_target_name(self, info):
        return self.target.full_name if self.target else None


# ─── Queries ──────────────────────────────────────────────────────────────────

class TeamQuery(graphene.ObjectType):
    role_catalogue = graphene.Field(RoleCatalogueType, description='Roles, modules and defaults for the caller\'s organisation type')
    team_members = graphene.List(TeamMemberType, include_inactive=graphene.Boolean())
    branches = graphene.List(BranchType, include_inactive=graphene.Boolean())
    access_audit_log = graphene.List(AccessAuditLogType, limit=graphene.Int())
    my_permissions = graphene.JSONString()

    def resolve_role_catalogue(self, info):
        u = _user(info)
        t = rbac.org_type_of(u)
        return RoleCatalogueType(
            org_type=t,
            roles=[RoleDefType(id=r, label=l, description=d, default_permissions=rbac.default_matrix(r, t)) for r, l, d in rbac.roles_for(t)],
            modules=[ModuleDefType(id=m, label=l, group=g) for m, l, g in rbac.modules_for(t)],
            actions=list(rbac.ACTIONS),
            branch_kinds=[[k, l] for k, l in Branch.kinds_for(t)],
        )

    def resolve_team_members(self, info, include_inactive=False):
        u = _user(info)
        rbac.require_module(u, 'team', 'view') if not rbac.is_org_admin(u) else None
        qs = Profile.objects.filter(organization=u.organization).select_related('branch').order_by('-is_org_admin', 'full_name')
        if not include_inactive:
            qs = qs.filter(is_active=True)
        return qs

    def resolve_branches(self, info, include_inactive=False):
        u = _user(info)
        qs = Branch.objects.filter(organization=u.organization)
        if not include_inactive:
            qs = qs.filter(is_active=True)
        return qs.order_by('-is_headquarters', 'name')

    def resolve_access_audit_log(self, info, limit=100):
        u = rbac.assert_org_admin(_user(info), 'view the access audit log')
        return AccessAuditLog.objects.filter(organization=u.organization).select_related('actor', 'target')[:max(1, min(limit, 500))]

    def resolve_my_permissions(self, info):
        return rbac.effective_matrix(_user(info))


# ─── Branch mutations ─────────────────────────────────────────────────────────

class BranchInput(graphene.InputObjectType):
    name = graphene.String()
    code = graphene.String()
    kind = graphene.String()
    province = graphene.String()
    district = graphene.String()
    address = graphene.String()
    phone = graphene.String()
    is_headquarters = graphene.Boolean()
    is_active = graphene.Boolean()


def _apply_branch(b, input, org_type):
    for f in ('name', 'code', 'province', 'district', 'address', 'phone'):
        v = input.get(f)
        if v is not None:
            setattr(b, f, v.strip())
    if input.get('kind') is not None:
        if input.kind not in dict(Branch.kinds_for(org_type)):
            raise Exception('Invalid branch kind for this organisation type')
        b.kind = input.kind
    for f in ('is_headquarters', 'is_active'):
        if input.get(f) is not None:
            setattr(b, f, input.get(f))
    if not b.name:
        raise Exception('Branch name is required')


class CreateBranch(graphene.Mutation):
    class Arguments:
        input = BranchInput(required=True)

    branch = graphene.Field(BranchType)

    def mutate(self, info, input):
        u = rbac.assert_org_admin(_user(info), 'manage branches')
        t = rbac.org_type_of(u)
        b = Branch(organization=u.organization, kind=Branch.kinds_for(t)[0][0])
        _apply_branch(b, input, t)
        if b.is_headquarters:
            Branch.objects.filter(organization=u.organization, is_headquarters=True).update(is_headquarters=False)
        b.save()
        rbac.audit(u.organization, u, 'branch_created', detail={'branch': b.name, 'kind': b.kind})
        return CreateBranch(branch=b)


class UpdateBranch(graphene.Mutation):
    class Arguments:
        id = graphene.UUID(required=True)
        input = BranchInput(required=True)

    branch = graphene.Field(BranchType)

    def mutate(self, info, id, input):
        u = rbac.assert_org_admin(_user(info), 'manage branches')
        b = Branch.objects.get(pk=id, organization=u.organization)
        _apply_branch(b, input, rbac.org_type_of(u))
        if b.is_headquarters:
            Branch.objects.filter(organization=u.organization, is_headquarters=True).exclude(pk=b.pk).update(is_headquarters=False)
        b.save()
        rbac.audit(u.organization, u, 'branch_updated', detail={'branch': b.name})
        return UpdateBranch(branch=b)


class DeleteBranch(graphene.Mutation):
    class Arguments:
        id = graphene.UUID(required=True)

    ok = graphene.Boolean()

    def mutate(self, info, id):
        u = rbac.assert_org_admin(_user(info), 'manage branches')
        b = Branch.objects.get(pk=id, organization=u.organization)
        if b.members.exists():
            raise Exception('Move or deactivate the members of this branch first')
        name = b.name
        b.delete()
        rbac.audit(u.organization, u, 'branch_deleted', detail={'branch': name})
        return DeleteBranch(ok=True)


# ─── Member mutations ─────────────────────────────────────────────────────────

class SetMemberBranch(graphene.Mutation):
    class Arguments:
        user_id = graphene.ID(required=True)
        branch_id = graphene.UUID()

    member = graphene.Field(TeamMemberType)

    def mutate(self, info, user_id, branch_id=None):
        u = rbac.assert_org_admin(_user(info))
        target = Profile.objects.get(id=user_id, organization=u.organization)
        target.branch = Branch.objects.get(pk=branch_id, organization=u.organization) if branch_id else None
        target.save(update_fields=['branch'])
        rbac.audit(u.organization, u, 'member_branch_changed', target, {'branch': target.branch.name if target.branch else None})
        return SetMemberBranch(member=target)


class SetOrgAdmin(graphene.Mutation):
    class Arguments:
        user_id = graphene.ID(required=True)
        is_admin = graphene.Boolean(required=True)

    member = graphene.Field(TeamMemberType)

    def mutate(self, info, user_id, is_admin):
        u = rbac.assert_org_admin(_user(info))
        target = Profile.objects.get(id=user_id, organization=u.organization)
        if not is_admin and target.pk == u.pk:
            raise Exception('You cannot remove your own administrator access')
        if not is_admin and target.role in rbac.ADMIN_ROLES:
            raise Exception(f'{target.role} is an administrator role; change the role instead')
        if not is_admin:
            others = Profile.objects.filter(organization=u.organization, is_active=True).exclude(pk=target.pk)
            if not any(rbac.is_org_admin(o) for o in others):
                raise Exception('An organisation must keep at least one administrator')
        target.is_org_admin = is_admin
        target.save(update_fields=['is_org_admin'])
        rbac.audit(u.organization, u, 'admin_granted' if is_admin else 'admin_revoked', target)
        return SetOrgAdmin(member=target)


class ResetMemberPermissions(graphene.Mutation):
    """Drop the per-user override so the role default applies again."""
    class Arguments:
        user_id = graphene.ID(required=True)

    member = graphene.Field(TeamMemberType)

    def mutate(self, info, user_id):
        u = rbac.assert_org_admin(_user(info))
        target = Profile.objects.get(id=user_id, organization=u.organization)
        prefs = dict(target.preferences or {})
        prefs.pop('permissions', None)
        target.preferences = prefs
        target.save(update_fields=['preferences'])
        rbac.audit(u.organization, u, 'permissions_reset', target)
        return ResetMemberPermissions(member=target)


class TeamMutation(graphene.ObjectType):
    create_branch = CreateBranch.Field()
    update_branch = UpdateBranch.Field()
    delete_branch = DeleteBranch.Field()
    set_member_branch = SetMemberBranch.Field()
    set_org_admin = SetOrgAdmin.Field()
    reset_member_permissions = ResetMemberPermissions.Field()
