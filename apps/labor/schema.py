import graphene
from graphene_django import DjangoObjectType
from .models import WorkerProfile, AttendanceRecord, TaskAssignment, GPSCheckIn, PayrollRun, PayrollLine, PerformanceSummary


def _org(info):
    user = info.context.user
    if user.is_anonymous:
        raise Exception('Not authenticated')
    return user.organization


class WorkerProfileType(DjangoObjectType):
    class Meta:
        model = WorkerProfile
        fields = '__all__'

    completion_rate = graphene.Float()


class AttendanceRecordType(DjangoObjectType):
    class Meta:
        model = AttendanceRecord
        fields = '__all__'


class TaskAssignmentType(DjangoObjectType):
    class Meta:
        model = TaskAssignment
        fields = '__all__'


class GPSCheckInType(DjangoObjectType):
    class Meta:
        model = GPSCheckIn
        fields = '__all__'


class PayrollRunType(DjangoObjectType):
    class Meta:
        model = PayrollRun
        fields = '__all__'


class PayrollLineType(DjangoObjectType):
    class Meta:
        model = PayrollLine
        fields = '__all__'


class PerformanceSummaryType(DjangoObjectType):
    class Meta:
        model = PerformanceSummary
        fields = '__all__'

    completion_rate_pct = graphene.Float()

    def resolve_completion_rate_pct(self, info):
        return self.completion_rate_pct


class LaborQuery(graphene.ObjectType):
    workers = graphene.List(WorkerProfileType, department=graphene.String(), is_active=graphene.Boolean())
    worker = graphene.Field(WorkerProfileType, id=graphene.UUID(required=True))
    attendance_records = graphene.List(AttendanceRecordType, worker_id=graphene.UUID(), date=graphene.Date(), limit=graphene.Int())
    todays_attendance = graphene.List(AttendanceRecordType)
    task_assignments = graphene.List(TaskAssignmentType, worker_id=graphene.UUID(), status=graphene.String(), date=graphene.Date())
    payroll_runs = graphene.List(PayrollRunType, status=graphene.String())
    payroll_run = graphene.Field(PayrollRunType, id=graphene.UUID(required=True))
    performance_summaries = graphene.List(PerformanceSummaryType, worker_id=graphene.UUID())

    def resolve_workers(self, info, department=None, is_active=None):
        qs = WorkerProfile.objects.filter(organization=_org(info))
        if department:
            qs = qs.filter(department__icontains=department)
        if is_active is not None:
            qs = qs.filter(is_active=is_active)
        return qs

    def resolve_worker(self, info, id):
        return WorkerProfile.objects.get(pk=id, organization=_org(info))

    def resolve_attendance_records(self, info, worker_id=None, date=None, limit=100):
        qs = AttendanceRecord.objects.filter(organization=_org(info))
        if worker_id:
            qs = qs.filter(worker_id=worker_id)
        if date:
            qs = qs.filter(date=date)
        return qs[:limit]

    def resolve_todays_attendance(self, info):
        from django.utils import timezone
        today = timezone.localdate()
        return AttendanceRecord.objects.filter(organization=_org(info), date=today)

    def resolve_task_assignments(self, info, worker_id=None, status=None, date=None):
        qs = TaskAssignment.objects.filter(organization=_org(info))
        if worker_id:
            qs = qs.filter(worker_id=worker_id)
        if status:
            qs = qs.filter(status=status)
        if date:
            qs = qs.filter(assigned_date=date)
        return qs

    def resolve_payroll_runs(self, info, status=None):
        qs = PayrollRun.objects.filter(organization=_org(info))
        if status:
            qs = qs.filter(status=status)
        return qs

    def resolve_payroll_run(self, info, id):
        return PayrollRun.objects.get(pk=id, organization=_org(info))

    def resolve_performance_summaries(self, info, worker_id=None):
        qs = PerformanceSummary.objects.filter(organization=_org(info))
        if worker_id:
            qs = qs.filter(worker_id=worker_id)
        return qs


class CreateWorker(graphene.Mutation):
    class Arguments:
        full_name = graphene.String(required=True)
        employee_id = graphene.String()
        department = graphene.String()
        job_title = graphene.String()
        contract_type = graphene.String()
        pay_type = graphene.String()
        daily_rate = graphene.Float()
        hourly_rate = graphene.Float()
        monthly_salary = graphene.Float()
        phone = graphene.String()
        start_date = graphene.Date()
        biometric_id = graphene.String()

    worker = graphene.Field(WorkerProfileType)

    def mutate(self, info, full_name, **kwargs):
        worker = WorkerProfile.objects.create(
            organization=_org(info), full_name=full_name,
            created_by=info.context.user,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        return CreateWorker(worker=worker)


class RecordAttendance(graphene.Mutation):
    class Arguments:
        worker_id = graphene.UUID(required=True)
        date = graphene.Date(required=True)
        status = graphene.String()
        clock_in = graphene.Time()
        clock_out = graphene.Time()
        method = graphene.String()
        location_name = graphene.String()
        clock_in_latitude = graphene.Float()
        clock_in_longitude = graphene.Float()
        piece_rate_units = graphene.Float()
        notes = graphene.String()

    record = graphene.Field(AttendanceRecordType)

    def mutate(self, info, worker_id, date, **kwargs):
        worker = WorkerProfile.objects.get(pk=worker_id, organization=_org(info))
        record, _ = AttendanceRecord.objects.update_or_create(
            organization=_org(info), worker=worker, date=date,
            defaults={k: v for k, v in kwargs.items() if v is not None},
        )
        return RecordAttendance(record=record)


class AssignTask(graphene.Mutation):
    class Arguments:
        worker_id = graphene.UUID(required=True)
        title = graphene.String(required=True)
        assigned_date = graphene.Date(required=True)
        description = graphene.String()
        priority = graphene.String()
        field_name = graphene.String()
        target_latitude = graphene.Float()
        target_longitude = graphene.Float()
        due_time = graphene.Time()
        enterprise_id = graphene.UUID()

    task = graphene.Field(TaskAssignmentType)

    def mutate(self, info, worker_id, title, assigned_date, **kwargs):
        worker = WorkerProfile.objects.get(pk=worker_id, organization=_org(info))
        task = TaskAssignment.objects.create(
            organization=_org(info), worker=worker,
            title=title, assigned_date=assigned_date,
            assigned_by=info.context.user,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        return AssignTask(task=task)


class UpdateTaskStatus(graphene.Mutation):
    class Arguments:
        id = graphene.UUID(required=True)
        status = graphene.String(required=True)
        quality_score = graphene.Int()
        piece_rate_units_completed = graphene.Float()
        notes = graphene.String()

    task = graphene.Field(TaskAssignmentType)

    def mutate(self, info, id, status, **kwargs):
        task = TaskAssignment.objects.get(pk=id, organization=_org(info))
        task.status = status
        if status == 'in_progress' and not task.started_at:
            from django.utils import timezone
            task.started_at = timezone.now()
        if status == 'done' and not task.completed_at:
            from django.utils import timezone
            task.completed_at = timezone.now()
        for k, v in kwargs.items():
            if v is not None:
                setattr(task, k, v)
        task.save()
        return UpdateTaskStatus(task=task)


class GPSVerifyTask(graphene.Mutation):
    class Arguments:
        task_id = graphene.UUID(required=True)
        worker_id = graphene.UUID(required=True)
        latitude = graphene.Float(required=True)
        longitude = graphene.Float(required=True)
        accuracy_m = graphene.Float()

    checkin = graphene.Field(GPSCheckInType)
    is_valid = graphene.Boolean()

    def mutate(self, info, task_id, worker_id, latitude, longitude, **kwargs):
        import math
        task = TaskAssignment.objects.get(pk=task_id, organization=_org(info))
        worker = WorkerProfile.objects.get(pk=worker_id, organization=_org(info))

        distance = None
        is_valid = True
        if task.target_latitude and task.target_longitude:
            # Haversine distance
            R = 6371000
            lat1, lon1 = math.radians(float(task.target_latitude)), math.radians(float(task.target_longitude))
            lat2, lon2 = math.radians(latitude), math.radians(longitude)
            dlat, dlon = lat2 - lat1, lon2 - lon1
            a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
            distance = R * 2 * math.asin(math.sqrt(a))
            is_valid = distance <= task.target_radius_m

        checkin = GPSCheckIn.objects.create(
            organization=_org(info), worker=worker, task=task,
            latitude=latitude, longitude=longitude,
            distance_from_target_m=distance,
            is_valid=is_valid,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        if is_valid:
            TaskAssignment.objects.filter(pk=task_id).update(gps_verified=True)
        return GPSVerifyTask(checkin=checkin, is_valid=is_valid)


class CreatePayrollRun(graphene.Mutation):
    class Arguments:
        period_start = graphene.Date(required=True)
        period_end = graphene.Date(required=True)
        payment_method = graphene.String()
        notes = graphene.String()

    payroll_run = graphene.Field(PayrollRunType)

    def mutate(self, info, period_start, period_end, **kwargs):
        run = PayrollRun.objects.create(
            organization=_org(info),
            period_start=period_start,
            period_end=period_end,
            created_by=info.context.user,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        return CreatePayrollRun(payroll_run=run)


class AddPayrollLine(graphene.Mutation):
    class Arguments:
        payroll_run_id = graphene.UUID(required=True)
        worker_id = graphene.UUID(required=True)
        regular_hours = graphene.Float()
        overtime_hours = graphene.Float()
        days_worked = graphene.Int()
        base_pay = graphene.Float()
        overtime_pay = graphene.Float()
        piece_rate_units = graphene.Float()
        piece_rate_pay = graphene.Float()
        bonus = graphene.Float()
        napsa_deduction = graphene.Float()
        nhima_deduction = graphene.Float()
        paye_deduction = graphene.Float()
        other_deductions = graphene.Float()
        notes = graphene.String()

    line = graphene.Field(PayrollLineType)

    def mutate(self, info, payroll_run_id, worker_id, **kwargs):
        run = PayrollRun.objects.get(pk=payroll_run_id, organization=_org(info))
        worker = WorkerProfile.objects.get(pk=worker_id, organization=_org(info))
        line = PayrollLine(
            payroll_run=run, worker=worker,
            **{k: v for k, v in kwargs.items() if v is not None},
        )
        line.save()
        return AddPayrollLine(line=line)


class ApprovePayrollRun(graphene.Mutation):
    class Arguments:
        id = graphene.UUID(required=True)
        payment_date = graphene.Date()

    payroll_run = graphene.Field(PayrollRunType)

    def mutate(self, info, id, payment_date=None):
        run = PayrollRun.objects.get(pk=id, organization=_org(info))
        run.status = 'approved'
        run.approved_by = info.context.user
        if payment_date:
            run.payment_date = payment_date
        run.save()
        return ApprovePayrollRun(payroll_run=run)


class LaborMutation(graphene.ObjectType):
    create_worker = CreateWorker.Field()
    record_attendance = RecordAttendance.Field()
    assign_task = AssignTask.Field()
    update_task_status = UpdateTaskStatus.Field()
    gps_verify_task = GPSVerifyTask.Field()
    create_payroll_run = CreatePayrollRun.Field()
    add_payroll_line = AddPayrollLine.Field()
    approve_payroll_run = ApprovePayrollRun.Field()
