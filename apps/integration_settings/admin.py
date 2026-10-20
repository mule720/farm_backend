from django import forms
from django.contrib import admin

from .models import IntegrationCredential


class CredentialForm(forms.ModelForm):
    new_api_key = forms.CharField(
        label='API key', required=False, strip=True,
        widget=forms.PasswordInput(render_value=False, attrs={'autocomplete': 'new-password', 'size': 70}),
        help_text='Paste the key here and save. It is stored encrypted and never shown again. Leave empty to keep the current one.',
    )
    clear_api_key = forms.BooleanField(label='Remove the saved key', required=False)

    class Meta:
        model = IntegrationCredential
        fields = ('service', 'is_active', 'base_url', 'app_id')


@admin.register(IntegrationCredential)
class IntegrationCredentialAdmin(admin.ModelAdmin):
    form = CredentialForm
    list_display = ('service', 'is_active', 'key_status', 'updated_by', 'updated_at')
    fields = ('service', 'is_active', 'new_api_key', 'clear_api_key', 'base_url', 'app_id')

    @admin.display(description='Key')
    def key_status(self, obj):
        return IntegrationCredential.masked(obj.get_api_key()) or 'not set'

    def save_model(self, request, obj, form, change):
        if form.cleaned_data.get('clear_api_key'):
            obj.set_api_key('')
        elif form.cleaned_data.get('new_api_key'):
            obj.set_api_key(form.cleaned_data['new_api_key'])
        obj.updated_by = request.user.email
        super().save_model(request, obj, form, change)
