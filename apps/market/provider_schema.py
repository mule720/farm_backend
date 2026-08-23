"""
GraphQL schema for marketplace providers — AgroNexus Phase 3
Queries and mutations for: Provider, ProviderService, ProviderReview,
ProviderCertification, EquipmentCatalog, HireBooking, VetAppointment.
"""
import graphene
from graphene_django import DjangoObjectType
from django.utils.text import slugify
from django.utils import timezone

from .provider_models import (
    Provider, ProviderStaff, ProviderService,
    ProviderCertification, ProviderReview,
    EquipmentCatalog, HireBooking, VetAppointment,
)


def _org(info):
    user = info.context.user
    if user.is_anonymous:
        raise Exception('Not authenticated')
    return user.organization


# ── DjangoObjectTypes ─────────────────────────────────────────────────────────

class ProviderType(DjangoObjectType):
    class Meta:
        model = Provider
        fields = '__all__'


class ProviderStaffType(DjangoObjectType):
    class Meta:
        model = ProviderStaff
        fields = '__all__'


class ProviderServiceType(DjangoObjectType):
    class Meta:
        model = ProviderService
        fields = '__all__'


class ProviderCertificationType(DjangoObjectType):
    class Meta:
        model = ProviderCertification
        fields = '__all__'


class ProviderReviewType(DjangoObjectType):
    class Meta:
        model = ProviderReview
        fields = '__all__'


class EquipmentCatalogType(DjangoObjectType):
    class Meta:
        model = EquipmentCatalog
        fields = '__all__'


class HireBookingType(DjangoObjectType):
    class Meta:
        model = HireBooking
        fields = '__all__'


class VetAppointmentType(DjangoObjectType):
    class Meta:
        model = VetAppointment
        fields = '__all__'


# ── Queries ───────────────────────────────────────────────────────────────────

class ProviderQuery(graphene.ObjectType):
    # Provider directory — open to all authenticated users (not org-scoped)
    providers = graphene.List(
        ProviderType,
        provider_type=graphene.String(),
        district=graphene.String(),
        search=graphene.String(),
        verified_only=graphene.Boolean(),
    )
    provider = graphene.Field(ProviderType, id=graphene.UUID(required=True))

    # Relational
    provider_services     = graphene.List(ProviderServiceType, provider_id=graphene.UUID(required=True))
    provider_reviews      = graphene.List(ProviderReviewType,  provider_id=graphene.UUID(required=True))
    provider_certifications = graphene.List(ProviderCertificationType, provider_id=graphene.UUID(required=True))
    provider_staff        = graphene.List(ProviderStaffType,   provider_id=graphene.UUID(required=True))
    equipment_catalog     = graphene.List(EquipmentCatalogType, provider_id=graphene.UUID(required=True))

    # Org-scoped booking/appointment queries
    my_hire_bookings    = graphene.List(HireBookingType, status=graphene.String())
    hire_booking        = graphene.Field(HireBookingType, id=graphene.UUID(required=True))
    my_vet_appointments = graphene.List(VetAppointmentType, status=graphene.String())
    vet_appointment     = graphene.Field(VetAppointmentType, id=graphene.UUID(required=True))

    # ── resolvers ─────────────────────────────────────────────────────────────

    def resolve_providers(self, info, provider_type=None, district=None, search=None, verified_only=False):
        qs = Provider.objects.filter(status='active')
        if provider_type:
            qs = qs.filter(provider_type=provider_type)
        if district:
            qs = qs.filter(
                models_q(coverage_districts__contains=district) |
                models_q(district=district)
            )
        if search:
            qs = qs.filter(
                models_q(name__icontains=search) |
                models_q(tagline__icontains=search) |
                models_q(description__icontains=search) |
                models_q(specialties__icontains=search)
            )
        if verified_only:
            qs = qs.filter(is_verified=True)
        return qs

    def resolve_provider(self, info, id):
        try:
            return Provider.objects.get(pk=id)
        except Provider.DoesNotExist:
            return None

    def resolve_provider_services(self, info, provider_id):
        return ProviderService.objects.filter(provider_id=provider_id, is_available=True)

    def resolve_provider_reviews(self, info, provider_id):
        return ProviderReview.objects.filter(provider_id=provider_id, approved=True)

    def resolve_provider_certifications(self, info, provider_id):
        return ProviderCertification.objects.filter(provider_id=provider_id)

    def resolve_provider_staff(self, info, provider_id):
        return ProviderStaff.objects.filter(provider_id=provider_id, active=True)

    def resolve_equipment_catalog(self, info, provider_id):
        return EquipmentCatalog.objects.filter(provider_id=provider_id)

    def resolve_my_hire_bookings(self, info, status=None):
        qs = HireBooking.objects.filter(organization=_org(info))
        if status:
            qs = qs.filter(status=status)
        return qs

    def resolve_hire_booking(self, info, id):
        try:
            return HireBooking.objects.get(pk=id, organization=_org(info))
        except HireBooking.DoesNotExist:
            return None

    def resolve_my_vet_appointments(self, info, status=None):
        qs = VetAppointment.objects.filter(organization=_org(info))
        if status:
            qs = qs.filter(status=status)
        return qs

    def resolve_vet_appointment(self, info, id):
        try:
            return VetAppointment.objects.get(pk=id, organization=_org(info))
        except VetAppointment.DoesNotExist:
            return None


# Fix: import Q
from django.db.models import Q as models_q


# ── Input Types ───────────────────────────────────────────────────────────────

class ProviderInput(graphene.InputObjectType):
    provider_type   = graphene.String(required=True)
    name            = graphene.String(required=True)
    tagline         = graphene.String()
    description     = graphene.String()
    phone           = graphene.String()
    email           = graphene.String()
    website         = graphene.String()
    whatsapp        = graphene.String()
    district        = graphene.String()
    town            = graphene.String()
    address         = graphene.String()
    coverage_districts = graphene.List(graphene.String)
    mobile_service  = graphene.Boolean()
    emergency_available = graphene.Boolean()
    service_hours   = graphene.String()
    tags            = graphene.List(graphene.String)
    specialties     = graphene.List(graphene.String)
    year_established = graphene.Int()
    business_reg_no = graphene.String()


class ProviderServiceInput(graphene.InputObjectType):
    provider_id     = graphene.UUID(required=True)
    name            = graphene.String(required=True)
    description     = graphene.String()
    category        = graphene.String()
    pricing_model   = graphene.String()
    price           = graphene.Float()
    price_max       = graphene.Float()
    unit_label      = graphene.String()
    lead_time_days  = graphene.Int()
    notes           = graphene.String()


class ProviderReviewInput(graphene.InputObjectType):
    provider_id     = graphene.UUID(required=True)
    rating          = graphene.Int(required=True)
    title           = graphene.String()
    body            = graphene.String()
    service_used    = graphene.String()


class HireBookingInput(graphene.InputObjectType):
    provider_id     = graphene.UUID(required=True)
    equipment_id    = graphene.UUID()
    enterprise_id   = graphene.UUID()
    start_date      = graphene.Date(required=True)
    end_date        = graphene.Date(required=True)
    hectares        = graphene.Float()
    delivery_address = graphene.String()
    notes           = graphene.String()


class VetAppointmentInput(graphene.InputObjectType):
    provider_id     = graphene.UUID(required=True)
    enterprise_id   = graphene.UUID()
    vet_officer_id  = graphene.UUID()
    appt_type       = graphene.String(required=True)
    appt_date       = graphene.Date(required=True)
    appt_time       = graphene.Time()
    species         = graphene.String()
    animal_count    = graphene.Int()
    symptoms        = graphene.String()
    notes           = graphene.String()


# ── Mutations ─────────────────────────────────────────────────────────────────

class RegisterProvider(graphene.Mutation):
    """Register a new provider business profile (starts as 'pending')."""
    class Arguments:
        input = ProviderInput(required=True)

    provider = graphene.Field(ProviderType)
    ok = graphene.Boolean()

    def mutate(self, info, input):
        org = _org(info)
        base_slug = slugify(input.name)
        slug = base_slug
        counter = 1
        while Provider.objects.filter(slug=slug).exists():
            slug = f'{base_slug}-{counter}'
            counter += 1

        provider = Provider(
            provider_type=input.provider_type,
            name=input.name,
            slug=slug,
            tagline=input.get('tagline', ''),
            description=input.get('description', ''),
            phone=input.get('phone', ''),
            email=input.get('email', ''),
            website=input.get('website', ''),
            whatsapp=input.get('whatsapp', ''),
            district=input.get('district', ''),
            town=input.get('town', ''),
            address=input.get('address', ''),
            coverage_districts=input.get('coverage_districts') or [],
            mobile_service=input.get('mobile_service', False),
            emergency_available=input.get('emergency_available', False),
            service_hours=input.get('service_hours', ''),
            tags=input.get('tags') or [],
            specialties=input.get('specialties') or [],
            year_established=input.get('year_established'),
            business_reg_no=input.get('business_reg_no', ''),
            status='pending',
            registered_by=org,
            created_by=info.context.user,
        )
        provider.save()
        return RegisterProvider(provider=provider, ok=True)


class UpdateProvider(graphene.Mutation):
    class Arguments:
        id    = graphene.UUID(required=True)
        input = ProviderInput(required=True)

    provider = graphene.Field(ProviderType)
    ok = graphene.Boolean()

    def mutate(self, info, id, input):
        try:
            provider = Provider.objects.get(pk=id, registered_by=_org(info))
        except Provider.DoesNotExist:
            raise Exception('Provider not found or access denied')

        for field in ['tagline', 'description', 'phone', 'email', 'website',
                      'whatsapp', 'district', 'town', 'address', 'service_hours',
                      'year_established', 'business_reg_no']:
            val = input.get(field)
            if val is not None:
                setattr(provider, field, val)

        for list_field in ['coverage_districts', 'tags', 'specialties']:
            val = input.get(list_field)
            if val is not None:
                setattr(provider, list_field, val)

        for bool_field in ['mobile_service', 'emergency_available']:
            val = input.get(bool_field)
            if val is not None:
                setattr(provider, bool_field, val)

        provider.save()
        return UpdateProvider(provider=provider, ok=True)


class VerifyProvider(graphene.Mutation):
    """Admin mutation — mark a provider as verified."""
    class Arguments:
        id = graphene.UUID(required=True)

    provider = graphene.Field(ProviderType)
    ok = graphene.Boolean()

    def mutate(self, info, id):
        if not info.context.user.is_staff:
            raise Exception('Only platform admins can verify providers')
        try:
            provider = Provider.objects.get(pk=id)
        except Provider.DoesNotExist:
            raise Exception('Provider not found')
        provider.is_verified = True
        provider.status = 'active'
        provider.verified_at = timezone.now()
        provider.verified_by = info.context.user
        provider.save()
        return VerifyProvider(provider=provider, ok=True)


class AddProviderService(graphene.Mutation):
    class Arguments:
        input = ProviderServiceInput(required=True)

    service = graphene.Field(ProviderServiceType)
    ok = graphene.Boolean()

    def mutate(self, info, input):
        try:
            provider = Provider.objects.get(pk=input.provider_id, registered_by=_org(info))
        except Provider.DoesNotExist:
            raise Exception('Provider not found or access denied')

        service = ProviderService(
            provider=provider,
            name=input.name,
            description=input.get('description', ''),
            category=input.get('category', ''),
            pricing_model=input.get('pricing_model', 'negotiable'),
            price=input.get('price'),
            price_max=input.get('price_max'),
            unit_label=input.get('unit_label', ''),
            lead_time_days=input.get('lead_time_days', 0),
            notes=input.get('notes', ''),
        )
        service.save()
        return AddProviderService(service=service, ok=True)


class PostProviderReview(graphene.Mutation):
    class Arguments:
        input = ProviderReviewInput(required=True)

    review = graphene.Field(ProviderReviewType)
    ok = graphene.Boolean()

    def mutate(self, info, input):
        org = _org(info)
        try:
            provider = Provider.objects.get(pk=input.provider_id)
        except Provider.DoesNotExist:
            raise Exception('Provider not found')

        review, created = ProviderReview.objects.update_or_create(
            provider=provider,
            organization=org,
            defaults=dict(
                reviewed_by=info.context.user,
                rating=max(1, min(5, input.rating)),
                title=input.get('title', ''),
                body=input.get('body', ''),
                service_used=input.get('service_used', ''),
                approved=False,  # requires admin approval
            )
        )
        return PostProviderReview(review=review, ok=True)


class ApproveReview(graphene.Mutation):
    """Admin mutation — approve a submitted review."""
    class Arguments:
        id = graphene.UUID(required=True)

    ok = graphene.Boolean()

    def mutate(self, info, id):
        if not info.context.user.is_staff:
            raise Exception('Admin only')
        try:
            review = ProviderReview.objects.get(pk=id)
        except ProviderReview.DoesNotExist:
            raise Exception('Review not found')
        review.approved = True
        review.approved_at = timezone.now()
        review.save()
        review.provider.update_rating()
        return ApproveReview(ok=True)


class CreateHireBooking(graphene.Mutation):
    class Arguments:
        input = HireBookingInput(required=True)

    booking = graphene.Field(HireBookingType)
    ok = graphene.Boolean()

    def mutate(self, info, input):
        org = _org(info)
        try:
            provider = Provider.objects.get(pk=input.provider_id)
        except Provider.DoesNotExist:
            raise Exception('Provider not found')

        equipment = None
        if input.get('equipment_id'):
            try:
                equipment = EquipmentCatalog.objects.get(pk=input.equipment_id, provider=provider)
            except EquipmentCatalog.DoesNotExist:
                raise Exception('Equipment not found')

        enterprise = None
        if input.get('enterprise_id'):
            from apps.enterprises.models import Enterprise
            try:
                enterprise = Enterprise.objects.get(pk=input.enterprise_id, organization=org)
            except Enterprise.DoesNotExist:
                pass

        booking = HireBooking(
            provider=provider,
            equipment=equipment,
            organization=org,
            enterprise=enterprise,
            requested_by=info.context.user,
            start_date=input.start_date,
            end_date=input.end_date,
            hectares=input.get('hectares'),
            delivery_address=input.get('delivery_address', ''),
            notes=input.get('notes', ''),
            status='enquiry',
        )
        booking.save()
        provider.booking_count = provider.hire_bookings.count()
        provider.save(update_fields=['booking_count'])
        return CreateHireBooking(booking=booking, ok=True)


class UpdateHireBookingStatus(graphene.Mutation):
    class Arguments:
        id     = graphene.UUID(required=True)
        status = graphene.String(required=True)
        provider_notes = graphene.String()
        quoted_amount  = graphene.Float()
        agreed_amount  = graphene.Float()

    booking = graphene.Field(HireBookingType)
    ok = graphene.Boolean()

    def mutate(self, info, id, status, provider_notes=None, quoted_amount=None, agreed_amount=None):
        try:
            booking = HireBooking.objects.get(pk=id)
        except HireBooking.DoesNotExist:
            raise Exception('Booking not found')

        booking.status = status
        if provider_notes is not None:
            booking.provider_notes = provider_notes
        if quoted_amount is not None:
            booking.quoted_amount = quoted_amount
        if agreed_amount is not None:
            booking.agreed_amount = agreed_amount
        booking.save()
        return UpdateHireBookingStatus(booking=booking, ok=True)


class BookVetAppointment(graphene.Mutation):
    class Arguments:
        input = VetAppointmentInput(required=True)

    appointment = graphene.Field(VetAppointmentType)
    ok = graphene.Boolean()

    def mutate(self, info, input):
        org = _org(info)
        try:
            provider = Provider.objects.get(pk=input.provider_id)
        except Provider.DoesNotExist:
            raise Exception('Provider not found')

        vet_officer = None
        if input.get('vet_officer_id'):
            try:
                vet_officer = ProviderStaff.objects.get(pk=input.vet_officer_id, provider=provider)
            except ProviderStaff.DoesNotExist:
                pass

        enterprise = None
        if input.get('enterprise_id'):
            from apps.enterprises.models import Enterprise
            try:
                enterprise = Enterprise.objects.get(pk=input.enterprise_id, organization=org)
            except Enterprise.DoesNotExist:
                pass

        appt = VetAppointment(
            provider=provider,
            organization=org,
            enterprise=enterprise,
            requested_by=info.context.user,
            vet_officer=vet_officer,
            appt_type=input.appt_type,
            appt_date=input.appt_date,
            appt_time=input.get('appt_time'),
            species=input.get('species', ''),
            animal_count=input.get('animal_count', 0),
            symptoms=input.get('symptoms', ''),
            notes=input.get('notes', ''),
            status='requested',
        )
        appt.save()
        provider.booking_count = provider.hire_bookings.count() + provider.vet_appointments.count()
        provider.save(update_fields=['booking_count'])
        return BookVetAppointment(appointment=appt, ok=True)


class UpdateVetAppointment(graphene.Mutation):
    """Update appointment outcome — status, diagnosis, treatment, medications."""
    class Arguments:
        id              = graphene.UUID(required=True)
        status          = graphene.String()
        diagnosis       = graphene.String()
        treatment_given = graphene.String()
        follow_up_date  = graphene.Date()
        outcome_notes   = graphene.String()
        total_amount    = graphene.Float()
        paid            = graphene.Boolean()

    appointment = graphene.Field(VetAppointmentType)
    ok = graphene.Boolean()

    def mutate(self, info, id, **kwargs):
        try:
            appt = VetAppointment.objects.get(pk=id)
        except VetAppointment.DoesNotExist:
            raise Exception('Appointment not found')

        for field in ['status', 'diagnosis', 'treatment_given', 'follow_up_date',
                      'outcome_notes', 'total_amount', 'paid']:
            val = kwargs.get(field)
            if val is not None:
                setattr(appt, field, val)
        appt.save()
        return UpdateVetAppointment(appointment=appt, ok=True)


# ── Consolidated Mutation class (merge into main schema) ─────────────────────

class ProviderMutation(graphene.ObjectType):
    register_provider         = RegisterProvider.Field()
    update_provider           = UpdateProvider.Field()
    verify_provider           = VerifyProvider.Field()
    add_provider_service      = AddProviderService.Field()
    post_provider_review      = PostProviderReview.Field()
    approve_review            = ApproveReview.Field()
    create_hire_booking       = CreateHireBooking.Field()
    update_hire_booking_status = UpdateHireBookingStatus.Field()
    book_vet_appointment      = BookVetAppointment.Field()
    update_vet_appointment    = UpdateVetAppointment.Field()
