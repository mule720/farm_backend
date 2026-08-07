import graphene
from graphene_django import DjangoObjectType
from .models import CommodityPrice, BuyerProfile, MarketListing, TradeContract, AuctionEvent
def _org(info):
    user = info.context.user
    if user.is_anonymous:
        raise Exception('Not authenticated')
    return user.organization


class CommodityPriceType(DjangoObjectType):
    class Meta:
        model = CommodityPrice
        fields = '__all__'


class BuyerProfileType(DjangoObjectType):
    class Meta:
        model = BuyerProfile
        fields = '__all__'


class MarketListingType(DjangoObjectType):
    class Meta:
        model = MarketListing
        fields = '__all__'


class TradeContractType(DjangoObjectType):
    class Meta:
        model = TradeContract
        fields = '__all__'


class AuctionEventType(DjangoObjectType):
    class Meta:
        model = AuctionEvent
        fields = '__all__'


class MarketQuery(graphene.ObjectType):
    commodity_prices = graphene.List(CommodityPriceType, commodity=graphene.String(), limit=graphene.Int())
    latest_prices = graphene.List(CommodityPriceType)
    buyer_profiles = graphene.List(BuyerProfileType)
    buyer_profile = graphene.Field(BuyerProfileType, id=graphene.UUID(required=True))
    market_listings = graphene.List(MarketListingType, status=graphene.String())
    my_listings = graphene.List(MarketListingType)
    trade_contracts = graphene.List(TradeContractType, status=graphene.String())
    trade_contract = graphene.Field(TradeContractType, id=graphene.UUID(required=True))
    auction_events = graphene.List(AuctionEventType, status=graphene.String())

    def resolve_commodity_prices(self, info, commodity=None, limit=50):
        qs = CommodityPrice.objects.filter(organization=_org(info))
        if commodity:
            qs = qs.filter(commodity__icontains=commodity)
        return qs[:limit]

    def resolve_latest_prices(self, info):
        from django.db.models import Max
        latest = CommodityPrice.objects.filter(organization=_org(info)).values('commodity').annotate(latest=Max('price_date'))
        result = []
        for item in latest:
            p = CommodityPrice.objects.filter(organization=_org(info), commodity=item['commodity'], price_date=item['latest']).first()
            if p:
                result.append(p)
        return result

    def resolve_buyer_profiles(self, info):
        return BuyerProfile.objects.filter(organization=_org(info))

    def resolve_buyer_profile(self, info, id):
        return BuyerProfile.objects.get(pk=id, organization=_org(info))

    def resolve_market_listings(self, info, status=None):
        qs = MarketListing.objects.filter(status='active') if not status else MarketListing.objects.filter(status=status)
        return qs

    def resolve_my_listings(self, info):
        return MarketListing.objects.filter(organization=_org(info))

    def resolve_trade_contracts(self, info, status=None):
        qs = TradeContract.objects.filter(organization=_org(info))
        if status:
            qs = qs.filter(status=status)
        return qs

    def resolve_trade_contract(self, info, id):
        return TradeContract.objects.get(pk=id, organization=_org(info))

    def resolve_auction_events(self, info, status=None):
        qs = AuctionEvent.objects.filter(organization=_org(info))
        if status:
            qs = qs.filter(status=status)
        return qs


class AddCommodityPrice(graphene.Mutation):
    class Arguments:
        commodity = graphene.String(required=True)
        market_name = graphene.String(required=True)
        price = graphene.Float(required=True)
        unit = graphene.String()
        currency = graphene.String()
        price_date = graphene.Date(required=True)
        source = graphene.String()

    price_record = graphene.Field(CommodityPriceType)

    def mutate(self, info, commodity, market_name, price, price_date, **kwargs):
        p = CommodityPrice.objects.create(
            organization=_org(info),
            commodity=commodity, market_name=market_name,
            price=price, price_date=price_date,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        return AddCommodityPrice(price_record=p)


class CreateBuyerProfile(graphene.Mutation):
    class Arguments:
        name = graphene.String(required=True)
        buyer_type = graphene.String()
        contact_person = graphene.String()
        phone = graphene.String()
        email = graphene.String()
        address = graphene.String()
        town = graphene.String()
        commodities_wanted = graphene.List(graphene.String)
        payment_terms = graphene.String()

    buyer = graphene.Field(BuyerProfileType)

    def mutate(self, info, name, **kwargs):
        buyer = BuyerProfile.objects.create(
            organization=_org(info), name=name,
            created_by=info.context.user,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        return CreateBuyerProfile(buyer=buyer)


class CreateListing(graphene.Mutation):
    class Arguments:
        commodity = graphene.String(required=True)
        quantity_available = graphene.Float(required=True)
        asking_price = graphene.Float(required=True)
        unit = graphene.String()
        description = graphene.String()
        available_from = graphene.Date()
        available_until = graphene.Date()
        enterprise_id = graphene.UUID()
        location = graphene.String()

    listing = graphene.Field(MarketListingType)

    def mutate(self, info, commodity, quantity_available, asking_price, **kwargs):
        listing = MarketListing.objects.create(
            organization=_org(info),
            commodity=commodity,
            quantity_available=quantity_available,
            asking_price=asking_price,
            created_by=info.context.user,
            status='active',
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        return CreateListing(listing=listing)


class UpdateListingStatus(graphene.Mutation):
    class Arguments:
        id = graphene.UUID(required=True)
        status = graphene.String(required=True)

    listing = graphene.Field(MarketListingType)

    def mutate(self, info, id, status):
        listing = MarketListing.objects.get(pk=id, organization=_org(info))
        listing.status = status
        listing.save()
        return UpdateListingStatus(listing=listing)


class CreateTradeContract(graphene.Mutation):
    class Arguments:
        commodity = graphene.String(required=True)
        quantity_agreed = graphene.Float(required=True)
        agreed_price = graphene.Float(required=True)
        buyer_id = graphene.UUID()
        listing_id = graphene.UUID()
        unit = graphene.String()
        delivery_date = graphene.Date()
        payment_terms = graphene.String()
        deposit_pct = graphene.Int()

    contract = graphene.Field(TradeContractType)

    def mutate(self, info, commodity, quantity_agreed, agreed_price, **kwargs):
        contract = TradeContract(
            organization=_org(info),
            commodity=commodity,
            quantity_agreed=quantity_agreed,
            agreed_price=agreed_price,
            created_by=info.context.user,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        contract.save()
        return CreateTradeContract(contract=contract)


class UpdateContractStatus(graphene.Mutation):
    class Arguments:
        id = graphene.UUID(required=True)
        status = graphene.String(required=True)
        quantity_delivered = graphene.Float()
        deposit_paid = graphene.Boolean()
        final_paid = graphene.Boolean()

    contract = graphene.Field(TradeContractType)

    def mutate(self, info, id, status, **kwargs):
        contract = TradeContract.objects.get(pk=id, organization=_org(info))
        contract.status = status
        for k, v in kwargs.items():
            if v is not None:
                setattr(contract, k, v)
        contract.save()
        return UpdateContractStatus(contract=contract)


class MarketMutation(graphene.ObjectType):
    add_commodity_price = AddCommodityPrice.Field()
    create_buyer_profile = CreateBuyerProfile.Field()
    create_listing = CreateListing.Field()
    update_listing_status = UpdateListingStatus.Field()
    create_trade_contract = CreateTradeContract.Field()
    update_contract_status = UpdateContractStatus.Field()
