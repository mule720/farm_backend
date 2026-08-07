"""Celery tasks for async report generation."""
from config.celery import app as celery_app
from .exporters import build_report


@celery_app.task(bind=True, max_retries=3)
def generate_report_task(self, report_id: str):
    from .models import Report
    try:
        report = Report.objects.get(id=report_id)
        report.status = 'processing'
        report.save(update_fields=['status'])
        file_url = build_report(report)
        report.file_url = file_url
        report.status = 'ready'
        report.save(update_fields=['file_url', 'status'])
    except Exception as exc:
        report = Report.objects.filter(id=report_id).first()
        if report:
            report.status = 'failed'
            report.save(update_fields=['status'])
        raise self.retry(exc=exc, countdown=30)
