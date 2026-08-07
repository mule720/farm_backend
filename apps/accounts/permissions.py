from rest_framework.permissions import BasePermission

ROLE_HIERARCHY = {
    'saas_admin': 10,
    'director': 9,
    'production_manager': 8,
    'finance_manager': 7,
    'sales_manager': 7,
    'supervisor': 6,
    'vet_officer': 5,
    'farmhand': 4,
    'driver': 3,
}


def has_min_role(user, min_role):
    return ROLE_HIERARCHY.get(user.role, 0) >= ROLE_HIERARCHY.get(min_role, 0)


class IsSaasAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == 'saas_admin'


class IsDirectorOrAbove(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and has_min_role(request.user, 'director')


class IsManagerOrAbove(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and has_min_role(request.user, 'production_manager')


class IsSupervisorOrAbove(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and has_min_role(request.user, 'supervisor')


class IsSameOrganization(BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.user.role == 'saas_admin':
            return True
        org_id = getattr(obj, 'organization_id', None) or getattr(getattr(obj, 'organization', None), 'id', None)
        return org_id == request.user.organization_id
