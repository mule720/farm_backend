"""Export & trade documents — GraphQL surface (folded into MarketQuery/MarketMutation)."""
import graphene
from decimal import Decimal
from graphene_django import DjangoObjectType

from .models import ExportDocument, TradeContract, BuyerProfile
from .schema import _org, TradeContractType
from apps.accounts import rbac


class ExportDocumentType(DjangoObjectType):
    doc_type_display = graphene.String()
    status_display = graphene.String()
    contract_id = graphene.UUID()

    class Meta:
        model = ExportDocument
        fields = ['id', 'contract', 'doc_type', 'doc_number', 'issuing_authority', 'commodity', 'quantity', 'unit',
                  'destination_country', 'status', 'issue_date', 'expiry_date', 'document_url', 'notes', 'created_at', 'updated_at']
        convert_choices_to_enum = False

    def resolve_doc_type_display(self, info):
        return self.get_doc_type_display()

    def resolve_status_display(self, info):
        return self.get_status_display()

    def resolve_contract_id(self, info):
        return self.contract_id


class ExportChecklistItemType(graphene.ObjectType):
    doc_type = graphene.String()
    label = graphene.String()
    required = graphene.Boolean()
    document = graphene.Field(ExportDocumentType)


# Which documents a consignment normally needs, by commodity family
_CHECKLIST = {
    'plant': ['invoice', 'packing_list', 'phytosanitary', 'coo', 'customs'],
    'animal': ['invoice', 'packing_list', 'health_cert', 'coo', 'customs'],
}
_ANIMAL_WORDS = ('cattle', 'goat', 'sheep', 'pig', 'pork', 'beef', 'chicken', 'poultry', 'broiler', 'egg', 'fish', 'tilapia',
                 'bream', 'honey', 'milk', 'dairy', 'hide', 'skin', 'livestock', 'day-old', 'chick')


def checklist_for(contract):
    fam = 'animal' if any(w in (contract.commodity or '').lower() for w in _ANIMAL_WORDS) else 'plant'
    types = list(_CHECKLIST[fam])
    if contract.buyer and (contract.buyer.country or 'Zambia').lower() in ('zambia', ''):
        # Domestic sale — customs / phyto / CoO are not required
        types = [t for t in types if t in ('invoice', 'packing_list')]
    return types


class ExportQuery(graphene.ObjectType):
    export_documents = graphene.List(ExportDocumentType, contract_id=graphene.UUID(), status=graphene.String())
    export_document = graphene.Field(ExportDocumentType, id=graphene.UUID(required=True))
    export_checklist = graphene.List(ExportChecklistItemType, contract_id=graphene.UUID(required=True))

    def resolve_export_documents(self, info, contract_id=None, status=None):
        qs = ExportDocument.objects.filter(organization=_org(info)).select_related('contract')
        if contract_id:
            qs = qs.filter(contract_id=contract_id)
        if status:
            qs = qs.filter(status=status)
        return qs.order_by('-created_at')

    def resolve_export_document(self, info, id):
        return ExportDocument.objects.get(pk=id, organization=_org(info))

    def resolve_export_checklist(self, info, contract_id):
        org = _org(info)
        contract = TradeContract.objects.select_related('buyer').get(pk=contract_id, organization=org)
        docs = {d.doc_type: d for d in ExportDocument.objects.filter(organization=org, contract=contract).order_by('created_at')}
        labels = dict(ExportDocument.DOC_TYPE_CHOICES)
        required = checklist_for(contract)
        out = [ExportChecklistItemType(doc_type=t, label=labels[t], required=True, document=docs.get(t)) for t in required]
        out += [ExportChecklistItemType(doc_type=t, label=labels[t], required=False, document=d)
                for t, d in docs.items() if t not in required]
        return out


class ExportDocumentInput(graphene.InputObjectType):
    contract_id = graphene.UUID()
    doc_type = graphene.String()
    doc_number = graphene.String()
    issuing_authority = graphene.String()
    commodity = graphene.String()
    quantity = graphene.Float()
    unit = graphene.String()
    destination_country = graphene.String()
    status = graphene.String()
    issue_date = graphene.Date()
    expiry_date = graphene.Date()
    notes = graphene.String()


def _apply(doc, input):
    for f in ('doc_number', 'issuing_authority', 'commodity', 'unit', 'destination_country', 'notes'):
        v = input.get(f)
        if v is not None:
            setattr(doc, f, v.strip())
    if input.get('quantity') is not None:
        if input.quantity < 0:
            raise Exception('Quantity cannot be negative')
        doc.quantity = Decimal(str(input.quantity))  # floats are not accepted by the Decimal scalar on the way back out
    if input.get('doc_type') is not None:
        if input.doc_type not in dict(ExportDocument.DOC_TYPE_CHOICES):
            raise Exception('Invalid document type')
        doc.doc_type = input.doc_type
    if input.get('status') is not None:
        if input.status not in dict(ExportDocument.STATUS_CHOICES):
            raise Exception('Invalid status')
        doc.status = input.status
    for f in ('issue_date', 'expiry_date'):
        if input.get(f) is not None:
            setattr(doc, f, input.get(f))
    if doc.issue_date and doc.expiry_date and doc.expiry_date < doc.issue_date:
        raise Exception('Expiry date must be after issue date')


class CreateExportDocument(graphene.Mutation):
    """Create a document, pre-filled from its contract; optionally render the PDF immediately."""
    class Arguments:
        input = ExportDocumentInput(required=True)
        generate = graphene.Boolean()

    document = graphene.Field(ExportDocumentType)

    def mutate(self, info, input, generate=False):
        from .documents import build_export_document_pdf, next_doc_number
        rbac.require_module(info.context.user, 'export', 'create')
        org = _org(info)
        if not input.get('doc_type'):
            raise Exception('Document type is required')
        contract = None
        if input.get('contract_id'):
            contract = TradeContract.objects.select_related('buyer').filter(pk=input.contract_id, organization=org).first()
            if contract is None:
                raise Exception('Contract not found')
        doc = ExportDocument(organization=org, contract=contract, created_by=info.context.user, doc_type=input.doc_type)
        if contract:
            doc.commodity = contract.commodity
            doc.quantity = contract.quantity_agreed
            doc.unit = contract.unit
            doc.destination_country = contract.buyer.country if contract.buyer else ''
        _apply(doc, input)
        if not doc.commodity:
            raise Exception('Commodity is required')
        if not doc.doc_number:
            doc.doc_number = next_doc_number(org, doc.doc_type)
        doc.save()
        if generate:
            build_export_document_pdf(doc)
        return CreateExportDocument(document=doc)


class UpdateExportDocument(graphene.Mutation):
    class Arguments:
        id = graphene.UUID(required=True)
        input = ExportDocumentInput(required=True)
        regenerate = graphene.Boolean()

    document = graphene.Field(ExportDocumentType)

    def mutate(self, info, id, input, regenerate=False):
        from .documents import build_export_document_pdf
        rbac.require_module(info.context.user, 'export', 'edit')
        doc = ExportDocument.objects.select_related('contract', 'contract__buyer').get(pk=id, organization=_org(info))
        if input.get('contract_id') is not None:
            doc.contract = TradeContract.objects.get(pk=input.contract_id, organization=doc.organization)
        _apply(doc, input)
        doc.save()
        if regenerate:
            build_export_document_pdf(doc)
        return UpdateExportDocument(document=doc)


class GenerateExportDocumentPdf(graphene.Mutation):
    class Arguments:
        id = graphene.UUID(required=True)

    document = graphene.Field(ExportDocumentType)
    url = graphene.String()

    def mutate(self, info, id):
        from .documents import build_export_document_pdf
        doc = ExportDocument.objects.select_related('organization', 'contract', 'contract__buyer').get(pk=id, organization=_org(info))
        url = build_export_document_pdf(doc)
        return GenerateExportDocumentPdf(document=doc, url=url)


class GenerateContractPdf(graphene.Mutation):
    class Arguments:
        id = graphene.UUID(required=True)

    url = graphene.String()

    def mutate(self, info, id):
        from .documents import build_contract_pdf
        contract = TradeContract.objects.select_related('organization', 'buyer').get(pk=id, organization=_org(info))
        return GenerateContractPdf(url=build_contract_pdf(contract))


class GenerateExportPack(graphene.Mutation):
    """Create every missing required document for a contract and render all PDFs."""
    class Arguments:
        contract_id = graphene.UUID(required=True)

    documents = graphene.List(ExportDocumentType)
    created = graphene.Int()

    def mutate(self, info, contract_id):
        from .documents import build_export_document_pdf, next_doc_number
        rbac.require_module(info.context.user, 'export', 'create')
        org = _org(info)
        contract = TradeContract.objects.select_related('buyer').get(pk=contract_id, organization=org)
        existing = {d.doc_type: d for d in ExportDocument.objects.filter(organization=org, contract=contract)}
        created = 0
        for t in checklist_for(contract):
            if t not in existing:
                existing[t] = ExportDocument.objects.create(
                    organization=org, contract=contract, created_by=info.context.user, doc_type=t,
                    doc_number=next_doc_number(org, t), commodity=contract.commodity, quantity=contract.quantity_agreed,
                    unit=contract.unit, destination_country=contract.buyer.country if contract.buyer else '')
                created += 1
        for d in existing.values():
            build_export_document_pdf(d)
        return GenerateExportPack(documents=list(existing.values()), created=created)


class DeleteExportDocument(graphene.Mutation):
    class Arguments:
        id = graphene.UUID(required=True)

    ok = graphene.Boolean()

    def mutate(self, info, id):
        rbac.require_module(info.context.user, 'export', 'delete')
        n, _ = ExportDocument.objects.filter(pk=id, organization=_org(info)).delete()
        return DeleteExportDocument(ok=bool(n))


class UpdateTradeContract(graphene.Mutation):
    class Arguments:
        id = graphene.UUID(required=True)
        buyer_id = graphene.UUID()
        commodity = graphene.String()
        quantity_agreed = graphene.Float()
        agreed_price = graphene.Float()
        unit = graphene.String()
        currency = graphene.String()
        delivery_date = graphene.Date()
        delivery_address = graphene.String()
        payment_terms = graphene.String()
        deposit_pct = graphene.Int()
        terms_and_conditions = graphene.String()
        notes = graphene.String()

    contract = graphene.Field(TradeContractType)

    def mutate(self, info, id, **kwargs):
        org = _org(info)
        c = TradeContract.objects.get(pk=id, organization=org)
        if kwargs.get('buyer_id') is not None:
            c.buyer = BuyerProfile.objects.get(pk=kwargs.pop('buyer_id'), organization=org)
        for k, v in kwargs.items():
            if v is not None:
                setattr(c, k, Decimal(str(v)) if isinstance(v, float) else v)
        c.save()
        return UpdateTradeContract(contract=c)


class ExportMutation(graphene.ObjectType):
    create_export_document = CreateExportDocument.Field()
    update_export_document = UpdateExportDocument.Field()
    generate_export_document_pdf = GenerateExportDocumentPdf.Field()
    generate_contract_pdf = GenerateContractPdf.Field()
    generate_export_pack = GenerateExportPack.Field()
    delete_export_document = DeleteExportDocument.Field()
    update_trade_contract = UpdateTradeContract.Field()
