"""Farm money ledger — GraphQL for the Finance page and automatic postings from production, sales and processing."""
from datetime import date as date_cls
from decimal import Decimal, InvalidOperation

import graphene
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.accounts import rbac
from .models import FarmTransaction

MAX_IMPORT = 2000
MAX_AMOUNT = Decimal('1000000000000')  # 1 trillion, well inside max_digits=14

# Which farm modules let a user post automatic entries of each kind (besides Finance itself)
SOURCE_MODULES = {
    'production': ['production', 'poultry', 'village-chicken', 'piggery', 'fish', 'duck', 'goat-sheep', 'horticulture', 'inventory'],
    'processing': ['production', 'inventory'],
    'sales': ['sales'],
}


def _user(info):
    u = info.context.user
    if u.is_anonymous:
        raise Exception('Not authenticated')
    if not u.organization_id:
        raise Exception('Account has no organisation')
    return u


def _can_record(user, source):
    if rbac.can(user, 'finance', 'create'):
        return True
    return any(rbac.can(user, m, 'create') or rbac.can(user, m, 'edit') for m in SOURCE_MODULES.get(source, []))


def _clean(tx_type, category, description, amount, when, cycle_ref, reference, notes):
    """Validate one transaction; return a dict of model fields or raise ValueError with a short reason."""
    if tx_type not in ('income', 'expense'):
        raise ValueError('type must be income or expense')
    allowed = FarmTransaction.INCOME_CATEGORIES if tx_type == 'income' else FarmTransaction.EXPENSE_CATEGORIES
    if category not in allowed:
        raise ValueError(f'category "{category}" is not valid for {tx_type}')
    description = (description or '').strip()
    if not description:
        raise ValueError('description is required')
    try:
        amt = Decimal(str(round(float(amount), 2)))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('amount is not a number')
    if amt <= 0 or amt >= MAX_AMOUNT:
        raise ValueError('amount must be greater than zero')
    if not isinstance(when, date_cls):
        raise ValueError('date is required')
    return dict(tx_type=tx_type, category=category, description=description[:255], amount=amt, date=when,
                cycle_ref=(cycle_ref or '')[:64], reference=(reference or '')[:100], notes=notes or '')


# ─── Types ────────────────────────────────────────────────────────────────────

class FarmTransactionType(graphene.ObjectType):
    id = graphene.String()
    type = graphene.String()
    category = graphene.String()
    description = graphene.String()
    amount = graphene.Float()
    date = graphene.Date()
    cycle_ref = graphene.String()
    reference = graphene.String()
    notes = graphene.String()
    source = graphene.String()
    created_at = graphene.DateTime()

    def resolve_id(self, info): return str(self.id)
    def resolve_type(self, info): return self.tx_type
    def resolve_amount(self, info): return float(self.amount)


class FarmTransactionInput(graphene.InputObjectType):
    id = graphene.String(description='Set to update an existing entry')
    type = graphene.String(required=True)
    category = graphene.String(required=True)
    description = graphene.String(required=True)
    amount = graphene.Float(required=True)
    date = graphene.Date(required=True)
    cycle_ref = graphene.String()
    reference = graphene.String()
    notes = graphene.String()


class AutoTransactionInput(graphene.InputObjectType):
    source_ref = graphene.String(required=True, description='Stable key — the same key is never posted twice')
    type = graphene.String(required=True)
    category = graphene.String(required=True)
    description = graphene.String(required=True)
    amount = graphene.Float(required=True)
    date = graphene.Date(required=True)
    cycle_ref = graphene.String()
    reference = graphene.String()
    notes = graphene.String()


# ─── Queries ──────────────────────────────────────────────────────────────────

class LedgerQuery(graphene.ObjectType):
    farm_transactions = graphene.List(
        FarmTransactionType, since=graphene.Date(), until=graphene.Date(), cycle_ref=graphene.String(),
        description="This organisation's income and expenses, newest first")

    def resolve_farm_transactions(self, info, since=None, until=None, cycle_ref=None):
        u = rbac.require_module(_user(info), 'finance', 'view')
        qs = FarmTransaction.objects.filter(organization_id=u.organization_id)
        if since:
            qs = qs.filter(date__gte=since)
        if until:
            qs = qs.filter(date__lte=until)
        if cycle_ref:
            qs = qs.filter(cycle_ref=cycle_ref)
        return list(qs[:10000])


# ─── Mutations ────────────────────────────────────────────────────────────────

class SaveFarmTransaction(graphene.Mutation):
    class Arguments:
        input = FarmTransactionInput(required=True)

    transaction = graphene.Field(FarmTransactionType)

    def mutate(self, info, input):
        u = _user(info)
        try:
            fields = _clean(input.type, input.category, input.description, input.amount, input.date,
                            input.get('cycle_ref'), input.get('reference'), input.get('notes'))
        except ValueError as e:
            raise Exception(str(e))
        if input.get('id'):
            rbac.require_module(u, 'finance', 'edit')
            try:
                tx = FarmTransaction.objects.get(id=input.id, organization_id=u.organization_id)
            except (FarmTransaction.DoesNotExist, ValueError, ValidationError):
                raise Exception('Transaction not found')
            for k, v in fields.items():
                setattr(tx, k, v)
            tx.save()
        else:
            rbac.require_module(u, 'finance', 'create')
            tx = FarmTransaction.objects.create(organization_id=u.organization_id, created_by=u, source='manual', **fields)
        return SaveFarmTransaction(transaction=tx)


class DeleteFarmTransaction(graphene.Mutation):
    class Arguments:
        id = graphene.String(required=True)

    ok = graphene.Boolean()

    def mutate(self, info, id):
        u = rbac.require_module(_user(info), 'finance', 'delete')
        try:
            n, _ = FarmTransaction.objects.filter(id=id, organization_id=u.organization_id).delete()
        except (ValueError, ValidationError):
            n = 0
        if not n:
            raise Exception('Transaction not found')
        return DeleteFarmTransaction(ok=True)


class PostFarmTransactions(graphene.Mutation):
    """
    Post entries automatically (from production, sales, processing) or import
    an old browser-only ledger. Idempotent: an entry whose sourceRef was posted
    before is skipped, so a retry or a second browser can never double-count.
    """
    class Arguments:
        source = graphene.String(required=True, description='production | sales | processing | import')
        items = graphene.List(graphene.NonNull(AutoTransactionInput), required=True)

    created = graphene.Int()
    duplicates = graphene.Int()
    rejected = graphene.Int()
    transactions = graphene.List(FarmTransactionType)

    def mutate(self, info, source, items):
        u = _user(info)
        if source not in FarmTransaction.SOURCES or source == 'manual':
            raise Exception('Unknown source')
        allowed = rbac.can(u, 'finance', 'create') if source == 'import' else _can_record(u, source)
        if not allowed:
            raise Exception('Permission denied: you cannot post entries to the ledger')
        if len(items) > MAX_IMPORT:
            raise Exception(f'Too many entries in one request (max {MAX_IMPORT})')
        created, dup, rejected, out = 0, 0, 0, []
        existing = set(FarmTransaction.objects.filter(
            organization_id=u.organization_id, source_ref__in=[i.source_ref for i in items if i.source_ref]
        ).values_list('source_ref', flat=True))
        for i in items:
            key = (i.source_ref or '').strip()[:120]
            if not key:
                rejected += 1
                continue
            if key in existing:
                dup += 1
                continue
            try:
                fields = _clean(i.type, i.category, i.description, i.amount, i.date, i.get('cycle_ref'), i.get('reference'), i.get('notes'))
            except ValueError:
                rejected += 1
                continue
            try:
                with transaction.atomic():
                    tx = FarmTransaction.objects.create(organization_id=u.organization_id, created_by=u, source=source, source_ref=key, **fields)
            except IntegrityError:  # raced with another browser posting the same key
                dup += 1
                continue
            existing.add(key)
            created += 1
            out.append(tx)
        return PostFarmTransactions(created=created, duplicates=dup, rejected=rejected, transactions=out)


class LedgerMutation(graphene.ObjectType):
    save_farm_transaction = SaveFarmTransaction.Field()
    delete_farm_transaction = DeleteFarmTransaction.Field()
    post_farm_transactions = PostFarmTransactions.Field()
