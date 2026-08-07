from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from graphene_django.views import GraphQLView


def health_check(request):
    """Kubernetes liveness / readiness probe endpoint."""
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path('admin/', admin.site.urls),
    # Kubernetes health probe — no auth required
    path('health/', health_check),
    # Single GraphQL endpoint — all apps exposed here
    path('graphql/', csrf_exempt(GraphQLView.as_view(graphiql=settings.DEBUG))),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
