"""
Security smoke tests for AGRINUXES farming backend.

Covers the most critical security fixes:
  1. Market listings requires authentication
  2. Video call join scoped to participants only (cross-org blocked)
  3. Payroll approval requires director/finance_manager role
  4. Stock transaction is atomic (both transaction record and stock level commit)
  5. ActivateUser mutation requires authentication
"""
import json
from django.test import TestCase, RequestFactory
from graphene_django.views import GraphQLView
from graphql_jwt.shortcuts import get_token

from apps.accounts.models import Organization, Profile
from apps.inventory.models import InventoryItem, InventoryTransaction
from apps.video_calls.models import VideoCall
from apps.labor.models import PayrollRun

from config.schema import schema


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _gql(user, query, variables=None):
    """Execute a GraphQL query/mutation as *user* (or None for anonymous)."""
    factory = RequestFactory()
    body = {"query": query}
    if variables:
        body["variables"] = variables
    request = factory.post(
        "/graphql/",
        data=json.dumps(body),
        content_type="application/json",
    )
    if user is not None:
        # Attach user directly so graphql_jwt middleware resolves it
        request.user = user
    else:
        from django.contrib.auth.models import AnonymousUser
        request.user = AnonymousUser()

    # Execute via graphene schema directly (skips HTTP middleware complexity)
    result = schema.execute(
        query,
        variable_values=variables or {},
        context_value=request,
    )
    return result


def _make_org_and_users(org_name, slug):
    """Return (org, director, farmhand) for the given org."""
    org = Organization.objects.create(name=org_name, slug=slug)
    director = Profile.objects.create_user(
        email=f"director@{slug}.test",
        full_name=f"{org_name} Director",
        password="testpass123",
        phone=f"0911{slug[:6].replace('-','')}1",
        organization=org,
        role="director",
    )
    farmhand = Profile.objects.create_user(
        email=f"farmhand@{slug}.test",
        full_name=f"{org_name} Farmhand",
        password="testpass123",
        phone=f"0922{slug[:6].replace('-','')}2",
        organization=org,
        role="farmhand",
    )
    return org, director, farmhand


# ─── Tests ────────────────────────────────────────────────────────────────────

class MarketListingsAuthTest(TestCase):
    """Test 1 — marketListings query requires authentication."""

    QUERY = """
    query {
      marketListings {
        id
        commodity
      }
    }
    """

    def test_market_listings_requires_auth(self):
        result = _gql(None, self.QUERY)
        errors = result.errors or []
        # The resolver calls _org(info) which raises 'Not authenticated'
        # graphene surfaces this as an error in result.errors
        error_messages = [str(e) for e in errors]
        self.assertTrue(
            any("authenticated" in m.lower() or "not authenticated" in m.lower()
                for m in error_messages),
            f"Expected auth error, got: {errors!r}",
        )

    def test_market_listings_succeeds_for_authenticated_user(self):
        org, director, _ = _make_org_and_users("Farm A", "farm-a")
        result = _gql(director, self.QUERY)
        self.assertIsNone(result.errors, f"Unexpected errors: {result.errors!r}")
        self.assertIn("marketListings", result.data)


class VideoCallCrossOrgTest(TestCase):
    """Test 2 — joinVideoCall is scoped to call participants only."""

    JOIN_MUTATION = """
    mutation JoinCall($callId: String!) {
      joinVideoCall(callId: $callId) {
        success
        error
      }
    }
    """

    def setUp(self):
        self.org_a, self.director_a, _ = _make_org_and_users("Org A", "org-a")
        self.org_b, self.director_b, _ = _make_org_and_users("Org B", "org-b")

        # Create a call belonging only to org A's director (no counterpart from org B)
        self.call = VideoCall.objects.create(
            room_name="test-room-xyz",
            initiator=self.director_a,
            counterpart=None,
            status="pending",
        )

    def test_video_call_join_cross_org_blocked(self):
        """User from org B cannot join org A's call."""
        result = _gql(
            self.director_b,
            self.JOIN_MUTATION,
            {"callId": str(self.call.pk)},
        )
        self.assertIsNone(result.errors, f"Unexpected GraphQL errors: {result.errors!r}")
        data = result.data["joinVideoCall"]
        self.assertFalse(data["success"], "Expected join to fail for non-participant")
        self.assertIsNotNone(data["error"])

    def test_video_call_join_participant_allowed(self):
        """
        The initiator should be able to join their own call.

        Legitimate participant (call initiator) can join their own call.
        Bug fixed: services.py now uses user.full_name instead of user.get_full_name().
        """
        result = _gql(
            self.director_a,
            self.JOIN_MUTATION,
            {"callId": str(self.call.pk)},
        )
        self.assertIsNone(result.errors, f"Unexpected errors: {result.errors}")
        self.assertTrue(
            result.data["joinVideoCall"]["success"],
            "Initiator should be able to join their own call",
        )


class PayrollApprovalRoleTest(TestCase):
    """Test 3 — approvePayrollRun requires director or finance_manager."""

    MUTATION = """
    mutation Approve($id: UUID!) {
      approvePayrollRun(id: $id) {
        payrollRun {
          status
        }
      }
    }
    """

    def setUp(self):
        self.org, self.director, self.farmhand = _make_org_and_users("Farm B", "farm-b")
        self.finance_manager = Profile.objects.create_user(
            email="finance@farm-b.test",
            full_name="Finance Manager",
            password="testpass123",
            phone="09330000003",
            organization=self.org,
            role="finance_manager",
        )
        self.run = PayrollRun.objects.create(
            organization=self.org,
            period_start="2026-01-01",
            period_end="2026-01-31",
            status="draft",
            created_by=self.director,
        )

    def test_approve_payroll_farmhand_denied(self):
        result = _gql(self.farmhand, self.MUTATION, {"id": str(self.run.pk)})
        errors = result.errors or []
        error_messages = [str(e) for e in errors]
        self.assertTrue(
            any("permission" in m.lower() for m in error_messages),
            f"Expected permission denied for farmhand, got: {errors!r}",
        )

    def test_approve_payroll_director_succeeds(self):
        result = _gql(self.director, self.MUTATION, {"id": str(self.run.pk)})
        self.assertIsNone(result.errors, f"Unexpected errors: {result.errors!r}")
        # graphene_django converts CharField choices to uppercase enum values
        self.assertEqual(
            result.data["approvePayrollRun"]["payrollRun"]["status"].lower(),
            "approved",
        )

    def test_approve_payroll_finance_manager_succeeds(self):
        result = _gql(self.finance_manager, self.MUTATION, {"id": str(self.run.pk)})
        self.assertIsNone(result.errors, f"Unexpected errors: {result.errors!r}")
        # graphene_django converts CharField choices to uppercase enum values
        self.assertEqual(
            result.data["approvePayrollRun"]["payrollRun"]["status"].lower(),
            "approved",
        )


class InventoryAtomicTest(TestCase):
    """Test 4 — InventoryTransaction creation is atomic."""

    def setUp(self):
        self.org, self.director, _ = _make_org_and_users("Farm C", "farm-c")
        self.item = InventoryItem.objects.create(
            organization=self.org,
            name="Test Feed",
            category="feed",
            unit="kg",
            current_stock=100,
        )

    def test_inventory_transaction_atomic(self):
        """
        InventoryTransaction.save() wraps itself in transaction.atomic() and
        immediately updates InventoryItem.current_stock via an F() expression.
        Verify that both the transaction record AND the stock change commit together.
        """
        initial_stock = self.item.current_stock  # Decimal('100.000')

        txn = InventoryTransaction.objects.create(
            organization=self.org,
            item=self.item,
            transaction_type="purchase",
            quantity=50,
            recorded_by=self.director,
        )
        # InventoryTransaction.save() already does the stock update atomically —
        # no manual update needed or desired.

        # Verify the transaction record exists
        self.assertTrue(
            InventoryTransaction.objects.filter(pk=txn.pk).exists(),
            "Transaction record not found after commit",
        )

        # Verify stock level updated in the same atomic block as the txn record
        self.item.refresh_from_db()
        self.assertEqual(
            self.item.current_stock,
            initial_stock + 50,
            "Stock level was not updated atomically with the transaction record",
        )

    def test_inventory_transaction_rollback_on_failure(self):
        """If something fails inside the atomic block, neither change should persist."""
        from django.db import transaction

        initial_stock = self.item.current_stock
        initial_count = InventoryTransaction.objects.filter(organization=self.org).count()

        try:
            with transaction.atomic():
                InventoryTransaction.objects.create(
                    organization=self.org,
                    item=self.item,
                    transaction_type="usage",
                    quantity=10,
                    recorded_by=self.director,
                )
                raise ValueError("Simulated failure")
        except ValueError:
            pass

        self.item.refresh_from_db()
        self.assertEqual(self.item.current_stock, initial_stock, "Stock should be unchanged after rollback")
        self.assertEqual(
            InventoryTransaction.objects.filter(organization=self.org).count(),
            initial_count,
            "Transaction record should not exist after rollback",
        )


class ActivateUserAuthTest(TestCase):
    """Test 5 — activateUser mutation requires authentication."""

    MUTATION = """
    mutation ActivateUser($userId: ID!) {
      activateUser(userId: $userId) {
        success
      }
    }
    """

    def setUp(self):
        self.org, self.director, self.farmhand = _make_org_and_users("Farm D", "farm-d")
        # Create an inactive user to target
        self.inactive_user = Profile.objects.create_user(
            email="inactive@farm-d.test",
            full_name="Inactive User",
            password="testpass123",
            phone="09440000004",
            organization=self.org,
            role="farmhand",
            is_active=False,
        )

    def test_activate_user_requires_auth(self):
        """Anonymous caller should get an auth error, not AttributeError."""
        result = _gql(None, self.MUTATION, {"userId": str(self.inactive_user.pk)})
        errors = result.errors or []
        error_messages = [str(e) for e in errors]
        self.assertTrue(
            any("authenticated" in m.lower() or "not authenticated" in m.lower()
                for m in error_messages),
            f"Expected auth error for anonymous caller, got: {errors!r}",
        )

    def test_activate_user_farmhand_denied(self):
        """A farmhand role should not be able to activate users."""
        result = _gql(self.farmhand, self.MUTATION, {"userId": str(self.inactive_user.pk)})
        errors = result.errors or []
        error_messages = [str(e) for e in errors]
        self.assertTrue(
            any("permission" in m.lower() or "authenticated" in m.lower()
                for m in error_messages),
            f"Expected permission denied for farmhand, got: {errors!r}",
        )

    def test_activate_user_director_succeeds(self):
        """Director should be able to activate a user in their org."""
        result = _gql(self.director, self.MUTATION, {"userId": str(self.inactive_user.pk)})
        self.assertIsNone(result.errors, f"Unexpected errors: {result.errors!r}")
        self.assertTrue(result.data["activateUser"]["success"])
        self.inactive_user.refresh_from_db()
        self.assertTrue(self.inactive_user.is_active)
