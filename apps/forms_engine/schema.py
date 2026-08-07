import graphene
from graphene_django import DjangoObjectType
from .models import CustomField, Form, FormField, FormSubmission


class CustomFieldType(DjangoObjectType):
    class Meta:
        model = CustomField
        fields = ['id', 'name', 'label', 'field_type', 'is_required', 'options',
                  'formula', 'unit', 'min_value', 'max_value', 'default_value',
                  'sensor_id', 'field_order', 'is_active', 'enterprise', 'created_at']


class FormFieldType(DjangoObjectType):
    class Meta:
        model = FormField
        fields = ['id', 'label', 'field_type', 'is_required', 'options',
                  'formula', 'unit', 'field_order', 'custom_field', 'created_at']


class FormType(DjangoObjectType):
    field_count = graphene.Int()

    class Meta:
        model = Form
        fields = ['id', 'name', 'description', 'frequency', 'is_active',
                  'enterprise', 'fields', 'created_at', 'updated_at']

    def resolve_field_count(self, info):
        return self.fields.count()


class FormSubmissionType(DjangoObjectType):
    class Meta:
        model = FormSubmission
        fields = ['id', 'form', 'batch', 'enterprise', 'submitted_by',
                  'submitted_at', 'data', 'gps_lat', 'gps_lng', 'notes']


# ─── Inputs ──────────────────────────────────────────────────────────────────

class CustomFieldInput(graphene.InputObjectType):
    name = graphene.String(required=True)
    label = graphene.String(required=True)
    field_type = graphene.String(required=True)
    enterprise_id = graphene.ID()
    is_required = graphene.Boolean()
    options = graphene.JSONString()
    formula = graphene.String()
    unit = graphene.String()
    min_value = graphene.Float()
    max_value = graphene.Float()
    default_value = graphene.String()
    sensor_id = graphene.String()
    field_order = graphene.Int()


class FormInput(graphene.InputObjectType):
    name = graphene.String(required=True)
    description = graphene.String()
    frequency = graphene.String()
    enterprise_id = graphene.ID()
    is_active = graphene.Boolean()


class FormFieldInput(graphene.InputObjectType):
    label = graphene.String(required=True)
    field_type = graphene.String(required=True)
    is_required = graphene.Boolean()
    options = graphene.JSONString()
    formula = graphene.String()
    unit = graphene.String()
    field_order = graphene.Int()
    custom_field_id = graphene.ID()


class SubmitFormInput(graphene.InputObjectType):
    form_id = graphene.ID(required=True)
    data = graphene.JSONString(required=True)
    batch_id = graphene.ID()
    enterprise_id = graphene.ID()
    gps_lat = graphene.Float()
    gps_lng = graphene.Float()
    notes = graphene.String()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _org(info):
    user = info.context.user
    if user.is_anonymous:
        raise Exception('Not authenticated')
    return user.organization


# ─── Queries ──────────────────────────────────────────────────────────────────

class FormsQuery(graphene.ObjectType):
    custom_fields = graphene.List(
        CustomFieldType,
        enterprise_id=graphene.ID(),
        field_type=graphene.String(),
    )
    custom_field = graphene.Field(CustomFieldType, id=graphene.ID(required=True))

    forms = graphene.List(FormType, enterprise_id=graphene.ID(), is_active=graphene.Boolean())
    form = graphene.Field(FormType, id=graphene.ID(required=True))

    submissions = graphene.List(
        FormSubmissionType,
        form_id=graphene.ID(),
        batch_id=graphene.ID(),
        enterprise_id=graphene.ID(),
        limit=graphene.Int(),
    )
    submission = graphene.Field(FormSubmissionType, id=graphene.ID(required=True))

    def resolve_custom_fields(self, info, enterprise_id=None, field_type=None):
        org = _org(info)
        qs = CustomField.objects.filter(organization=org, is_active=True)
        if enterprise_id:
            qs = qs.filter(enterprise_id=enterprise_id)
        if field_type:
            qs = qs.filter(field_type=field_type)
        return qs

    def resolve_custom_field(self, info, id):
        org = _org(info)
        return CustomField.objects.get(id=id, organization=org)

    def resolve_forms(self, info, enterprise_id=None, is_active=None):
        org = _org(info)
        qs = Form.objects.filter(organization=org)
        if enterprise_id:
            qs = qs.filter(enterprise_id=enterprise_id)
        if is_active is not None:
            qs = qs.filter(is_active=is_active)
        return qs

    def resolve_form(self, info, id):
        org = _org(info)
        return Form.objects.get(id=id, organization=org)

    def resolve_submissions(self, info, form_id=None, batch_id=None,
                             enterprise_id=None, limit=None):
        org = _org(info)
        qs = FormSubmission.objects.filter(organization=org)
        if form_id:
            qs = qs.filter(form_id=form_id)
        if batch_id:
            qs = qs.filter(batch_id=batch_id)
        if enterprise_id:
            qs = qs.filter(enterprise_id=enterprise_id)
        if limit:
            qs = qs[:limit]
        return qs

    def resolve_submission(self, info, id):
        org = _org(info)
        return FormSubmission.objects.get(id=id, organization=org)


# ─── Mutations ────────────────────────────────────────────────────────────────

class CreateCustomField(graphene.Mutation):
    class Arguments:
        input = CustomFieldInput(required=True)

    custom_field = graphene.Field(CustomFieldType)

    def mutate(self, info, input):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        field = CustomField.objects.create(
            organization=user.organization,
            created_by=user,
            **{k: v for k, v in input.items() if v is not None and k != 'enterprise_id'},
            enterprise_id=input.get('enterprise_id'),
        )
        return CreateCustomField(custom_field=field)


class UpdateCustomField(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)
        input = CustomFieldInput(required=True)

    custom_field = graphene.Field(CustomFieldType)

    def mutate(self, info, id, input):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        field = CustomField.objects.get(id=id, organization=user.organization)
        for k, v in input.items():
            if v is not None:
                setattr(field, k, v)
        field.save()
        return UpdateCustomField(custom_field=field)


class DeleteCustomField(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)

    success = graphene.Boolean()

    def mutate(self, info, id):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        CustomField.objects.get(id=id, organization=user.organization).delete()
        return DeleteCustomField(success=True)


class CreateForm(graphene.Mutation):
    class Arguments:
        input = FormInput(required=True)

    form = graphene.Field(FormType)

    def mutate(self, info, input):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        form = Form.objects.create(
            organization=user.organization,
            created_by=user,
            name=input.name,
            description=input.get('description', ''),
            frequency=input.get('frequency', 'daily'),
            enterprise_id=input.get('enterprise_id'),
            is_active=input.get('is_active', True),
        )
        return CreateForm(form=form)


class UpdateForm(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)
        input = FormInput(required=True)

    form = graphene.Field(FormType)

    def mutate(self, info, id, input):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        form = Form.objects.get(id=id, organization=user.organization)
        for k, v in input.items():
            if v is not None:
                setattr(form, k, v)
        form.save()
        return UpdateForm(form=form)


class DeleteForm(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)

    success = graphene.Boolean()

    def mutate(self, info, id):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        Form.objects.get(id=id, organization=user.organization).delete()
        return DeleteForm(success=True)


class AddFormField(graphene.Mutation):
    class Arguments:
        form_id = graphene.ID(required=True)
        input = FormFieldInput(required=True)

    form_field = graphene.Field(FormFieldType)

    def mutate(self, info, form_id, input):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        form = Form.objects.get(id=form_id, organization=user.organization)
        ff = FormField.objects.create(
            form=form,
            organization=user.organization,
            label=input.label,
            field_type=input.field_type,
            is_required=input.get('is_required', False),
            options=input.get('options') or [],
            formula=input.get('formula', ''),
            unit=input.get('unit', ''),
            field_order=input.get('field_order', 0),
            custom_field_id=input.get('custom_field_id'),
        )
        return AddFormField(form_field=ff)


class RemoveFormField(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)

    success = graphene.Boolean()

    def mutate(self, info, id):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        FormField.objects.get(id=id, organization=user.organization).delete()
        return RemoveFormField(success=True)


class SubmitForm(graphene.Mutation):
    class Arguments:
        input = SubmitFormInput(required=True)

    submission = graphene.Field(FormSubmissionType)

    def mutate(self, info, input):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        form = Form.objects.get(id=input.form_id, organization=user.organization)
        sub = FormSubmission.objects.create(
            organization=user.organization,
            form=form,
            submitted_by=user,
            data=input.data or {},
            batch_id=input.get('batch_id'),
            enterprise_id=input.get('enterprise_id') or (form.enterprise_id),
            gps_lat=input.get('gps_lat'),
            gps_lng=input.get('gps_lng'),
            notes=input.get('notes', ''),
        )
        return SubmitForm(submission=sub)


class DeleteSubmission(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)

    success = graphene.Boolean()

    def mutate(self, info, id):
        user = info.context.user
        if user.is_anonymous:
            raise Exception('Not authenticated')
        FormSubmission.objects.get(id=id, organization=user.organization).delete()
        return DeleteSubmission(success=True)


class FormsMutation(graphene.ObjectType):
    create_custom_field = CreateCustomField.Field()
    update_custom_field = UpdateCustomField.Field()
    delete_custom_field = DeleteCustomField.Field()
    create_form = CreateForm.Field()
    update_form = UpdateForm.Field()
    delete_form = DeleteForm.Field()
    add_form_field = AddFormField.Field()
    remove_form_field = RemoveFormField.Field()
    submit_form = SubmitForm.Field()
    delete_submission = DeleteSubmission.Field()
