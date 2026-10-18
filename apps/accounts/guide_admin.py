"""Staff-only download of the AGRINUXES user guide from the Django admin index."""
from django.contrib import admin
from django.http import FileResponse, Http404
from django.urls import path
from django.conf import settings

_FILES = {
    'pdf': ('AGRINUXES_User_Guide.pdf', 'application/pdf'),
    'docx': ('AGRINUXES_User_Guide.docx',
             'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
}


def user_guide(request, fmt):
    if fmt not in _FILES:
        raise Http404
    name, ctype = _FILES[fmt]
    f = settings.BASE_DIR / 'docs' / name
    if not f.exists():
        raise Http404
    return FileResponse(open(f, 'rb'), as_attachment=True, filename=name, content_type=ctype)


_orig_get_urls = admin.site.get_urls


def _get_urls():
    extra = [path('user-guide/<str:fmt>/', admin.site.admin_view(user_guide), name='user_guide')]
    return extra + _orig_get_urls()


admin.site.get_urls = _get_urls
