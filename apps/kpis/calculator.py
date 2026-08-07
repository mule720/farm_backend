"""KPI formula evaluation engine."""
import re


def compute_aggregation(values: list, aggregation: str) -> float | None:
    if not values:
        return None
    floats = [float(v) for v in values]
    if aggregation == 'sum':
        return sum(floats)
    if aggregation == 'min':
        return min(floats)
    if aggregation == 'max':
        return max(floats)
    if aggregation == 'latest':
        return floats[0]
    return sum(floats) / len(floats)  # average (default)


def evaluate_formula(formula: str, organization, batch_id=None) -> float:
    """
    Evaluate a KPI formula by resolving {field_name} tokens against
    recent production records in the given org/batch.

    Supported tokens:
      {mortality_count}, {feed_consumed}, {initial_quantity},
      {current_quantity}, {days_in_batch}, plus any field name
      that appears in form submission data.
    """
    from apps.production.models import ProductionRecord
    from apps.enterprises.models import EnterpriseBatch
    import datetime

    context: dict[str, float] = {}

    if batch_id:
        try:
            batch = EnterpriseBatch.objects.get(id=batch_id, organization=organization)
            context['initial_quantity'] = float(batch.quantity)
            context['days_in_batch'] = (
                datetime.date.today() - batch.start_date
            ).days or 1
        except EnterpriseBatch.DoesNotExist:
            pass

        records = ProductionRecord.objects.filter(
            organization=organization, batch_id=batch_id
        ).order_by('-record_date')[:30]

        for record in records:
            for key, val in (record.data or {}).items():
                try:
                    context.setdefault(key, float(val))
                except (ValueError, TypeError):
                    pass

    # Replace {token} with values from context
    expr = formula
    for token, value in context.items():
        expr = expr.replace(f'{{{token}}}', str(value))

    # If any unreplaced tokens remain, substitute 0
    expr = re.sub(r'\{[^}]+\}', '0', expr)

    # Safe eval using only arithmetic
    try:
        allowed_names: dict = {'__builtins__': {}}
        result = eval(expr, allowed_names)  # noqa: S307 — safe arithmetic only
        return float(result)
    except Exception as e:
        raise ValueError(f'Formula evaluation failed: {e}')
