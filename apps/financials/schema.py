import graphene
from graphene_django import DjangoObjectType
from .models import BatchFinancials, CostEntry, RevenueEntry, BreakEvenAnalysis, LoanApplication
def _org(info):
    user = info.context.user
    if user.is_anonymous:
        raise Exception('Not authenticated')
    return user.organization


class BatchFinancialsType(DjangoObjectType):
    class Meta:
        model = BatchFinancials
        fields = '__all__'

    gross_profit = graphene.Float()
    profit_margin_pct = graphene.Float()
    roi_pct = graphene.Float()

    def resolve_gross_profit(self, info):
        return self.gross_profit

    def resolve_profit_margin_pct(self, info):
        return self.profit_margin_pct

    def resolve_roi_pct(self, info):
        return self.roi_pct


class CostEntryType(DjangoObjectType):
    class Meta:
        model = CostEntry
        fields = '__all__'


class RevenueEntryType(DjangoObjectType):
    class Meta:
        model = RevenueEntry
        fields = '__all__'


class BreakEvenAnalysisType(DjangoObjectType):
    class Meta:
        model = BreakEvenAnalysis
        fields = '__all__'


class LoanApplicationType(DjangoObjectType):
    class Meta:
        model = LoanApplication
        fields = '__all__'


class FinancialsQuery(graphene.ObjectType):
    batch_financials = graphene.List(BatchFinancialsType, enterprise_id=graphene.UUID())
    batch_financial = graphene.Field(BatchFinancialsType, id=graphene.UUID(required=True))
    cost_entries = graphene.List(CostEntryType, batch_financials_id=graphene.UUID(required=True), category=graphene.String())
    revenue_entries = graphene.List(RevenueEntryType, batch_financials_id=graphene.UUID(required=True), category=graphene.String())
    breakeven_analyses = graphene.List(BreakEvenAnalysisType, batch_financials_id=graphene.UUID(required=True))
    loan_applications = graphene.List(LoanApplicationType, status=graphene.String())
    loan_application = graphene.Field(LoanApplicationType, id=graphene.UUID(required=True))

    def resolve_batch_financials(self, info, enterprise_id=None):
        qs = BatchFinancials.objects.filter(organization=_org(info))
        if enterprise_id:
            qs = qs.filter(enterprise_id=enterprise_id)
        return qs

    def resolve_batch_financial(self, info, id):
        return BatchFinancials.objects.get(pk=id, organization=_org(info))

    def resolve_cost_entries(self, info, batch_financials_id, category=None):
        qs = CostEntry.objects.filter(batch_financials_id=batch_financials_id, organization=_org(info))
        if category:
            qs = qs.filter(category=category)
        return qs

    def resolve_revenue_entries(self, info, batch_financials_id, category=None):
        qs = RevenueEntry.objects.filter(batch_financials_id=batch_financials_id, organization=_org(info))
        if category:
            qs = qs.filter(category=category)
        return qs

    def resolve_breakeven_analyses(self, info, batch_financials_id):
        return BreakEvenAnalysis.objects.filter(batch_financials_id=batch_financials_id, organization=_org(info))

    def resolve_loan_applications(self, info, status=None):
        qs = LoanApplication.objects.filter(organization=_org(info))
        if status:
            qs = qs.filter(status=status)
        return qs

    def resolve_loan_application(self, info, id):
        return LoanApplication.objects.get(pk=id, organization=_org(info))


class CreateBatchFinancials(graphene.Mutation):
    class Arguments:
        batch_name = graphene.String(required=True)
        start_date = graphene.Date(required=True)
        enterprise_id = graphene.UUID()
        batch_id = graphene.UUID()
        target_units = graphene.Float()
        notes = graphene.String()

    batch_financials = graphene.Field(BatchFinancialsType)

    def mutate(self, info, batch_name, start_date, **kwargs):
        bf = BatchFinancials.objects.create(
            organization=_org(info),
            batch_name=batch_name,
            start_date=start_date,
            created_by=info.context.user,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        return CreateBatchFinancials(batch_financials=bf)


class AddCostEntry(graphene.Mutation):
    class Arguments:
        batch_financials_id = graphene.UUID(required=True)
        category = graphene.String(required=True)
        description = graphene.String(required=True)
        entry_date = graphene.Date(required=True)
        quantity = graphene.Float()
        unit = graphene.String()
        unit_cost = graphene.Float()
        amount = graphene.Float()
        supplier = graphene.String()
        invoice_ref = graphene.String()

    entry = graphene.Field(CostEntryType)

    def mutate(self, info, batch_financials_id, category, description, entry_date, **kwargs):
        bf = BatchFinancials.objects.get(pk=batch_financials_id, organization=_org(info))
        entry = CostEntry(
            organization=_org(info),
            batch_financials=bf,
            category=category,
            description=description,
            entry_date=entry_date,
            created_by=info.context.user,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        entry.save()
        return AddCostEntry(entry=entry)


class AddRevenueEntry(graphene.Mutation):
    class Arguments:
        batch_financials_id = graphene.UUID(required=True)
        category = graphene.String(required=True)
        description = graphene.String(required=True)
        entry_date = graphene.Date(required=True)
        quantity = graphene.Float()
        unit = graphene.String()
        unit_price = graphene.Float()
        amount = graphene.Float()
        buyer = graphene.String()
        invoice_ref = graphene.String()

    entry = graphene.Field(RevenueEntryType)

    def mutate(self, info, batch_financials_id, category, description, entry_date, **kwargs):
        bf = BatchFinancials.objects.get(pk=batch_financials_id, organization=_org(info))
        entry = RevenueEntry(
            organization=_org(info),
            batch_financials=bf,
            category=category,
            description=description,
            entry_date=entry_date,
            created_by=info.context.user,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        entry.save()
        return AddRevenueEntry(entry=entry)


class RunBreakEven(graphene.Mutation):
    class Arguments:
        batch_financials_id = graphene.UUID(required=True)
        name = graphene.String(required=True)
        fixed_costs = graphene.Float(required=True)
        variable_cost_per_unit = graphene.Float(required=True)
        selling_price_per_unit = graphene.Float(required=True)
        expected_units = graphene.Float(required=True)
        notes = graphene.String()

    analysis = graphene.Field(BreakEvenAnalysisType)

    def mutate(self, info, batch_financials_id, name, fixed_costs, variable_cost_per_unit, selling_price_per_unit, expected_units, **kwargs):
        bf = BatchFinancials.objects.get(pk=batch_financials_id, organization=_org(info))
        analysis = BreakEvenAnalysis(
            organization=_org(info),
            batch_financials=bf, name=name,
            fixed_costs=fixed_costs,
            variable_cost_per_unit=variable_cost_per_unit,
            selling_price_per_unit=selling_price_per_unit,
            expected_units=expected_units,
            created_by=info.context.user,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        analysis.save()
        return RunBreakEven(analysis=analysis)


class CreateLoanApplication(graphene.Mutation):
    class Arguments:
        loan_type = graphene.String(required=True)
        lender_name = graphene.String(required=True)
        amount_requested = graphene.Float(required=True)
        purpose = graphene.String(required=True)
        interest_rate_pct = graphene.Float()
        term_months = graphene.Int()
        collateral = graphene.String()
        application_date = graphene.Date()

    loan = graphene.Field(LoanApplicationType)

    def mutate(self, info, loan_type, lender_name, amount_requested, purpose, **kwargs):
        loan = LoanApplication.objects.create(
            organization=_org(info),
            loan_type=loan_type,
            lender_name=lender_name,
            amount_requested=amount_requested,
            purpose=purpose,
            created_by=info.context.user,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        return CreateLoanApplication(loan=loan)


class UpdateLoanStatus(graphene.Mutation):
    class Arguments:
        id = graphene.UUID(required=True)
        status = graphene.String(required=True)
        amount_approved = graphene.Float()
        approval_date = graphene.Date()
        disbursement_date = graphene.Date()
        ai_credit_score = graphene.Int()
        ai_risk_assessment = graphene.String()
        ai_recommendation = graphene.String()
        notes = graphene.String()

    loan = graphene.Field(LoanApplicationType)

    def mutate(self, info, id, status, **kwargs):
        loan = LoanApplication.objects.get(pk=id, organization=_org(info))
        loan.status = status
        for k, v in kwargs.items():
            if v is not None:
                setattr(loan, k, v)
        loan.save()
        return UpdateLoanStatus(loan=loan)


class FinancialsMutation(graphene.ObjectType):
    create_batch_financials = CreateBatchFinancials.Field()
    add_cost_entry = AddCostEntry.Field()
    add_revenue_entry = AddRevenueEntry.Field()
    run_break_even = RunBreakEven.Field()
    create_loan_application = CreateLoanApplication.Field()
    update_loan_status = UpdateLoanStatus.Field()
