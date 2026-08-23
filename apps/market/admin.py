from django.contrib import admin
from .models import CommodityPrice, BuyerProfile, MarketListing, TradeContract, AuctionEvent, ColdChainLog, ExportDocument
from .provider_models import (
    Provider, ProviderStaff, ProviderService,
    ProviderCertification, ProviderReview,
    EquipmentCatalog, HireBooking, VetAppointment,
)


@admin.register(Provider)
class ProviderAdmin(admin.ModelAdmin):
    list_display = ('name', 'provider_type', 'district', 'status', 'is_verified', 'avg_rating', 'review_count')
    list_filter = ('provider_type', 'status', 'is_verified', 'district')
    search_fields = ('name', 'slug', 'description', 'phone', 'email')
    readonly_fields = ('slug', 'avg_rating', 'review_count', 'booking_count', 'created_at', 'updated_at')
    actions = ['mark_verified', 'mark_active', 'mark_suspended']

    def mark_verified(self, request, qs):
        from django.utils import timezone
        qs.update(is_verified=True, status='active', verified_at=timezone.now(), verified_by=request.user)
    mark_verified.short_description = 'Mark selected providers as Verified & Active'

    def mark_active(self, request, qs):
        qs.update(status='active')

    def mark_suspended(self, request, qs):
        qs.update(status='suspended')


@admin.register(ProviderStaff)
class ProviderStaffAdmin(admin.ModelAdmin):
    list_display = ('name', 'role', 'provider', 'active', 'licence_no')
    list_filter = ('role', 'active')
    search_fields = ('name', 'email', 'phone', 'licence_no')


@admin.register(ProviderService)
class ProviderServiceAdmin(admin.ModelAdmin):
    list_display = ('name', 'provider', 'pricing_model', 'price', 'currency', 'is_available')
    list_filter = ('pricing_model', 'is_available')
    search_fields = ('name', 'description', 'provider__name')


@admin.register(ProviderCertification)
class ProviderCertificationAdmin(admin.ModelAdmin):
    list_display = ('name', 'provider', 'issuing_body', 'status', 'verified', 'expiry_date')
    list_filter = ('status', 'verified', 'issuing_body')
    search_fields = ('name', 'cert_number', 'provider__name')


@admin.register(ProviderReview)
class ProviderReviewAdmin(admin.ModelAdmin):
    list_display = ('provider', 'organization', 'rating', 'approved', 'created_at')
    list_filter = ('rating', 'approved', 'verified_purchase')
    search_fields = ('provider__name', 'title', 'body')
    actions = ['approve_reviews']

    def approve_reviews(self, request, qs):
        from django.utils import timezone
        qs.update(approved=True, approved_at=timezone.now())
        for review in qs:
            review.provider.update_rating()
    approve_reviews.short_description = 'Approve selected reviews'


@admin.register(EquipmentCatalog)
class EquipmentCatalogAdmin(admin.ModelAdmin):
    list_display = ('name', 'equipment_type', 'provider', 'daily_rate', 'per_ha_rate', 'is_available')
    list_filter = ('equipment_type', 'is_available', 'operator_included')
    search_fields = ('name', 'make', 'model', 'provider__name')


@admin.register(HireBooking)
class HireBookingAdmin(admin.ModelAdmin):
    list_display = ('booking_ref', 'provider', 'organization', 'start_date', 'end_date', 'status', 'agreed_amount')
    list_filter = ('status',)
    search_fields = ('booking_ref', 'provider__name', 'organization__name')
    readonly_fields = ('booking_ref', 'created_at', 'updated_at')


@admin.register(VetAppointment)
class VetAppointmentAdmin(admin.ModelAdmin):
    list_display = ('appt_ref', 'provider', 'organization', 'appt_type', 'appt_date', 'status', 'species', 'paid')
    list_filter = ('status', 'appt_type', 'paid')
    search_fields = ('appt_ref', 'provider__name', 'organization__name', 'species')
    readonly_fields = ('appt_ref', 'created_at', 'updated_at')
