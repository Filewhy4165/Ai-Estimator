"""Stripe billing routes for AI-Estimator SaaS.

Provides:
- POST /billing/checkout   — Create a Stripe Checkout Session
- POST /billing/portal     — Create a Stripe Customer Portal session
- POST /billing/webhook    — Stripe webhook handler (no auth, signature-verified)
- GET  /billing/subscription — Current subscription status and plan details
- GET  /billing/usage      — Usage stats for the current billing period
- log_usage() helper       — Insert usage_logs rows for metering

All endpoints (except webhook) require authentication via ``get_current_user``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from service.auth import get_current_user
from service.config import settings
from service.db_pg import (
    PgDatabase,
    SubscriptionRecord,
    UsageLogRecord,
    UserRecord,
    get_db,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])

# ──────────────────────────────────────────────────────────────────────
# Stripe SDK configuration
# ──────────────────────────────────────────────────────────────────────

stripe.api_key = settings.stripe_secret_key

# ──────────────────────────────────────────────────────────────────────
# Plan definitions
# ──────────────────────────────────────────────────────────────────────

PLAN_LIMITS: dict[str, dict[str, Any]] = {
    "free": {
        "name": "Free",
        "price_monthly": 0,
        "jobs_per_month": 5,
        "max_pages_per_job": 50,
        "priority_processing": False,
        "custom_models": False,
        "sso": False,
        "dedicated_support": False,
    },
    "pro": {
        "name": "Pro",
        "price_monthly": 49,
        "jobs_per_month": None,       # unlimited
        "max_pages_per_job": 500,
        "priority_processing": True,
        "custom_models": False,
        "sso": False,
        "dedicated_support": False,
    },
    "enterprise": {
        "name": "Enterprise",
        "price_monthly": None,        # custom pricing
        "jobs_per_month": None,       # unlimited
        "max_pages_per_job": None,    # unlimited
        "priority_processing": True,
        "custom_models": True,
        "sso": True,
        "dedicated_support": True,
    },
}

PRICE_ID_TO_PLAN: dict[str, str] = {
    settings.stripe_price_pro: "pro",
    settings.stripe_price_enterprise: "enterprise",
}

# ──────────────────────────────────────────────────────────────────────
# Pydantic schemas
# ──────────────────────────────────────────────────────────────────────


class CheckoutRequest(BaseModel):
    """Request body for creating a Stripe Checkout Session."""

    plan: str = Field(..., pattern=r"^(pro|enterprise)$",
                      description="Plan to subscribe to: 'pro' or 'enterprise'")
    success_url: str = Field(
        default="",
        description="URL to redirect after successful checkout. "
                    "{CHECKOUT_SESSION_ID} placeholder supported.",
    )
    cancel_url: str = Field(
        default="",
        description="URL to redirect if the customer cancels checkout.",
    )


class CheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str


class PortalRequest(BaseModel):
    """Request body for creating a Stripe Customer Portal session."""

    return_url: str = Field(
        default="",
        description="URL to return to after the portal session ends.",
    )


class PortalResponse(BaseModel):
    portal_url: str


class PlanDetail(BaseModel):
    """Plan feature details returned in subscription info."""

    name: str
    jobs_per_month: int | None
    max_pages_per_job: int | None
    priority_processing: bool
    custom_models: bool
    sso: bool
    dedicated_support: bool


class SubscriptionInfo(BaseModel):
    """Current subscription and plan details for the authenticated user."""

    plan: str
    plan_detail: PlanDetail
    status: str | None = None
    stripe_subscription_id: str | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None


class UsageStats(BaseModel):
    """Usage statistics for the current billing period."""

    jobs_created: int
    pages_processed: int
    period_start: datetime | None = None
    period_end: datetime | None = None
    jobs_limit: int | None = None
    pages_limit_per_job: int | None = None


# ──────────────────────────────────────────────────────────────────────
# Usage tracking helper
# ──────────────────────────────────────────────────────────────────────


async def log_usage(
    db: PgDatabase,
    user_id: uuid.UUID,
    endpoint: str,
    pages_processed: int = 0,
) -> UsageLogRecord:
    """Insert a usage log entry for metering and analytics.

    This is designed to be called from other route handlers (e.g. job
    creation, document processing) to record per-request consumption.

    Args:
        db: Active PgDatabase instance.
        user_id: The user who consumed the resource.
        endpoint: Identifier for the endpoint/action (e.g. "POST /v1/jobs").
        pages_processed: Number of pages consumed in this request.

    Returns:
        The created UsageLogRecord.
    """
    rec = UsageLogRecord(
        user_id=user_id,
        endpoint=endpoint,
        pages_processed=pages_processed,
    )
    return await db.create_usage_log(rec)


# ──────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────


def _get_price_id_for_plan(plan: str) -> str:
    """Return the Stripe Price ID for the given plan slug."""
    if plan == "pro":
        return settings.stripe_price_pro
    if plan == "enterprise":
        return settings.stripe_price_enterprise
    raise ValueError(f"Unknown plan: {plan}")


def _resolve_plan_from_price_id(price_id: str) -> str:
    """Map a Stripe Price ID back to a plan slug.  Defaults to 'pro'."""
    return PRICE_ID_TO_PLAN.get(price_id, "pro")


def _default_success_url() -> str:
    return settings.cors_origins.split(",")[0].strip() + "/billing?success=true"


def _default_cancel_url() -> str:
    return settings.cors_origins.split(",")[0].strip() + "/billing?canceled=true"


def _default_return_url() -> str:
    return settings.cors_origins.split(",")[0].strip() + "/billing"


# ──────────────────────────────────────────────────────────────────────
# POST /billing/checkout
# ──────────────────────────────────────────────────────────────────────


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout_session(
    body: CheckoutRequest,
    user: Annotated[UserRecord, Depends(get_current_user)],
    db: Annotated[PgDatabase, Depends(get_db)],
) -> CheckoutResponse:
    """Create a Stripe Checkout Session for the given plan.

    The user must be authenticated.  Their ``user_id`` and ``email`` are
    passed to Stripe as metadata so that the webhook can correlate the
    session back to the local user record.
    """
    price_id = _get_price_id_for_plan(body.plan)

    # Ensure the user has a Stripe Customer record; reuse if one exists.
    customer_id = user.stripe_customer_id
    if not customer_id:
        try:
            customer = stripe.Customer.create(
                email=user.email,
                metadata={"user_id": str(user.id)},
            )
            customer_id = customer.id
            await db.update_user(user.id, stripe_customer_id=customer_id)
        except stripe.error.StripeError as exc:
            logger.exception("Failed to create Stripe customer for user %s", user.id)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Stripe customer creation failed: {exc}",
            )

    success_url = body.success_url or _default_success_url()
    cancel_url = body.cancel_url or _default_cancel_url()

    try:
        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "user_id": str(user.id),
                "email": user.email,
                "plan": body.plan,
            },
            subscription_data={
                "metadata": {
                    "user_id": str(user.id),
                    "plan": body.plan,
                },
            },
        )
    except stripe.error.StripeError as exc:
        logger.exception("Failed to create Checkout Session for user %s", user.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Stripe checkout creation failed: {exc}",
        )

    return CheckoutResponse(checkout_url=session.url, session_id=session.id)


# ──────────────────────────────────────────────────────────────────────
# POST /billing/portal
# ──────────────────────────────────────────────────────────────────────


@router.post("/portal", response_model=PortalResponse)
async def create_portal_session(
    body: PortalRequest,
    user: Annotated[UserRecord, Depends(get_current_user)],
) -> PortalResponse:
    """Create a Stripe Customer Portal session for managing the subscription.

    Allows the customer to upgrade, cancel, or update payment method.
    """
    if not user.stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No Stripe customer record found. Subscribe to a plan first.",
        )

    return_url = body.return_url or _default_return_url()

    try:
        session = stripe.billing_portal.Session.create(
            customer=user.stripe_customer_id,
            return_url=return_url,
        )
    except stripe.error.StripeError as exc:
        logger.exception(
            "Failed to create Portal session for customer %s",
            user.stripe_customer_id,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Stripe portal creation failed: {exc}",
        )

    return PortalResponse(portal_url=session.url)


# ──────────────────────────────────────────────────────────────────────
# POST /billing/webhook
# ──────────────────────────────────────────────────────────────────────


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def stripe_webhook(
    request: Request,
    db: Annotated[PgDatabase, Depends(get_db)],
) -> dict[str, str]:
    """Handle Stripe webhook events.

    **No authentication** — Stripe signs the payload with the
    ``stripe-signature`` header which is verified against
    ``STRIPE_WEBHOOK_SECRET``.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    if not settings.stripe_webhook_secret:
        logger.error("STRIPE_WEBHOOK_SECRET is not configured — rejecting webhook")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook secret not configured",
        )

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret,
        )
    except stripe.error.SignatureVerificationError:
        logger.warning("Stripe webhook signature verification failed")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid signature",
        )
    except Exception as exc:
        logger.exception("Unexpected error constructing Stripe webhook event")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Webhook construction failed: {exc}",
        )

    event_type = event.get("type", "")
    logger.info("Stripe webhook received: %s", event_type)

    try:
        if event_type == "checkout.session.completed":
            await _handle_checkout_completed(event, db)
        elif event_type == "customer.subscription.updated":
            await _handle_subscription_updated(event, db)
        elif event_type == "customer.subscription.deleted":
            await _handle_subscription_deleted(event, db)
        elif event_type == "invoice.payment_failed":
            await _handle_payment_failed(event, db)
        elif event_type == "customer.created":
            await _handle_customer_created(event, db)
        else:
            logger.info("Unhandled Stripe event type: %s", event_type)
    except Exception:
        logger.exception("Error processing Stripe webhook event: %s", event_type)
        # Still return 200 so Stripe doesn't retry indefinitely for app errors
        # that are not signature-related.
        return {"status": "error", "detail": "Internal processing error"}

    return {"status": "ok"}


# ──────────────────────────────────────────────────────────────────────
# Webhook event handlers
# ──────────────────────────────────────────────────────────────────────


async def _handle_checkout_completed(
    event: dict[str, Any], db: PgDatabase,
) -> None:
    """Activate the subscription after a successful checkout."""
    session_data = event["data"]["object"]
    user_id_str = session_data.get("metadata", {}).get("user_id")
    if not user_id_str:
        # Fallback: try to find user by customer ID
        customer_id = session_data.get("customer")
        if customer_id:
            user = await db.get_user_by_stripe_customer_id(customer_id)
            if user:
                user_id_str = str(user.id)

    if not user_id_str:
        logger.error(
            "checkout.session.completed — no user_id in metadata or customer lookup: %s",
            session_data.get("id"),
        )
        return

    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        logger.error("Invalid user_id in checkout metadata: %s", user_id_str)
        return

    subscription_id = session_data.get("subscription")
    if not subscription_id:
        logger.error("checkout.session.completed — no subscription ID in session")
        return

    # Retrieve the full subscription from Stripe for price/period details
    try:
        stripe_sub = stripe.Subscription.retrieve(subscription_id)
    except stripe.error.StripeError:
        logger.exception("Failed to retrieve Stripe subscription %s", subscription_id)
        return

    price_id = stripe_sub["items"]["data"][0]["price"]["id"] if stripe_sub["items"]["data"] else ""
    plan = _resolve_plan_from_price_id(price_id)

    period_start = datetime.fromtimestamp(stripe_sub["current_period_start"], tz=timezone.utc)
    period_end = datetime.fromtimestamp(stripe_sub["current_period_end"], tz=timezone.utc)

    # Upsert subscription record
    existing_sub = await db.get_subscription_by_stripe_id(subscription_id)
    if existing_sub is None:
        rec = SubscriptionRecord(
            user_id=user_id,
            stripe_subscription_id=subscription_id,
            stripe_price_id=price_id,
            status="active",
            current_period_start=period_start,
            current_period_end=period_end,
        )
        await db.create_subscription(rec)
    else:
        await db.update_subscription(
            existing_sub.id,
            stripe_price_id=price_id,
            status="active",
            current_period_start=period_start,
            current_period_end=period_end,
        )

    # Update user plan
    await db.update_user(user_id, plan=plan)
    logger.info("Subscription activated: user=%s plan=%s sub=%s", user_id, plan, subscription_id)


async def _handle_subscription_updated(
    event: dict[str, Any], db: PgDatabase,
) -> None:
    """Sync subscription status when Stripe reports an update."""
    sub_data = event["data"]["object"]
    subscription_id = sub_data.get("id")
    if not subscription_id:
        return

    stripe_status = sub_data.get("status", "active")
    price_id = ""
    items = sub_data.get("items", {}).get("data", [])
    if items:
        price_id = items[0]["price"]["id"]

    period_start = None
    period_end = None
    if sub_data.get("current_period_start"):
        period_start = datetime.fromtimestamp(sub_data["current_period_start"], tz=timezone.utc)
    if sub_data.get("current_period_end"):
        period_end = datetime.fromtimestamp(sub_data["current_period_end"], tz=timezone.utc)

    existing_sub = await db.get_subscription_by_stripe_id(subscription_id)
    if existing_sub is None:
        logger.warning("subscription.updated — unknown subscription: %s", subscription_id)
        return

    # Map Stripe status to our DB status
    mapped_status = _map_stripe_status(stripe_status)

    update_fields: dict[str, Any] = {"status": mapped_status}
    if price_id:
        update_fields["stripe_price_id"] = price_id
    if period_start:
        update_fields["current_period_start"] = period_start
    if period_end:
        update_fields["current_period_end"] = period_end

    await db.update_subscription(existing_sub.id, **update_fields)

    # Update user plan if the price changed
    if price_id:
        new_plan = _resolve_plan_from_price_id(price_id)
        await db.update_user(existing_sub.user_id, plan=new_plan)

    logger.info(
        "Subscription updated: sub=%s status=%s price=%s",
        subscription_id, mapped_status, price_id,
    )


async def _handle_subscription_deleted(
    event: dict[str, Any], db: PgDatabase,
) -> None:
    """Downgrade user to free plan when subscription is canceled/deleted."""
    sub_data = event["data"]["object"]
    subscription_id = sub_data.get("id")
    if not subscription_id:
        return

    existing_sub = await db.get_subscription_by_stripe_id(subscription_id)
    if existing_sub is None:
        logger.warning("subscription.deleted — unknown subscription: %s", subscription_id)
        return

    # Mark subscription as canceled
    await db.update_subscription(existing_sub.id, status="canceled")

    # Downgrade the user to free
    await db.update_user(existing_sub.user_id, plan="free")
    logger.info("Subscription deleted: user=%s downgraded to free", existing_sub.user_id)


async def _handle_payment_failed(
    event: dict[str, Any], db: PgDatabase,
) -> None:
    """Mark the subscription as past_due when an invoice payment fails."""
    invoice_data = event["data"]["object"]
    subscription_id = invoice_data.get("subscription")
    if not subscription_id:
        return

    existing_sub = await db.get_subscription_by_stripe_id(subscription_id)
    if existing_sub is None:
        logger.warning("invoice.payment_failed — unknown subscription: %s", subscription_id)
        return

    await db.update_subscription(existing_sub.id, status="past_due")
    logger.info("Payment failed: sub=%s marked as past_due", subscription_id)


async def _handle_customer_created(
    event: dict[str, Any], db: PgDatabase,
) -> None:
    """Store stripe_customer_id on the user when a new Customer is created in Stripe."""
    customer_data = event["data"]["object"]
    customer_id = customer_data.get("id")
    if not customer_id:
        return

    # Try to find user by email
    email = customer_data.get("email")
    if not email:
        logger.warning("customer.created — no email on customer %s", customer_id)
        return

    user = await db.get_user_by_email(email)
    if user is None:
        logger.warning("customer.created — no user found for email %s", email)
        return

    # Only update if not already set (avoid overwriting)
    if user.stripe_customer_id and user.stripe_customer_id != customer_id:
        logger.warning(
            "customer.created — user %s already has stripe_customer_id=%s, not overwriting with %s",
            user.id, user.stripe_customer_id, customer_id,
        )
        return

    await db.update_user(user.id, stripe_customer_id=customer_id)
    logger.info("Customer created: stored stripe_customer_id=%s for user=%s", customer_id, user.id)


def _map_stripe_status(stripe_status: str) -> str:
    """Map Stripe subscription status to our DB status enum."""
    # Stripe statuses: active, past_due, canceled, unpaid, trialing, etc.
    # Our DB statuses: active, past_due, canceled
    mapping = {
        "active": "active",
        "trialing": "active",
        "past_due": "past_due",
        "canceled": "canceled",
        "unpaid": "past_due",
        "incomplete": "past_due",
        "incomplete_expired": "canceled",
        "paused": "past_due",
    }
    return mapping.get(stripe_status, "past_due")


# ──────────────────────────────────────────────────────────────────────
# GET /billing/subscription
# ──────────────────────────────────────────────────────────────────────


@router.get("/subscription", response_model=SubscriptionInfo)
async def get_subscription(
    user: Annotated[UserRecord, Depends(get_current_user)],
    db: Annotated[PgDatabase, Depends(get_db)],
) -> SubscriptionInfo:
    """Return the current subscription status and plan details for the authenticated user."""
    plan_slug = user.plan
    plan_limits = PLAN_LIMITS.get(plan_slug, PLAN_LIMITS["free"])

    # Find the active subscription record (if any)
    subs = await db.list_subscriptions_for_user(user.id, status="active")
    active_sub = subs[0] if subs else None

    return SubscriptionInfo(
        plan=plan_slug,
        plan_detail=PlanDetail(
            name=plan_limits["name"],
            jobs_per_month=plan_limits["jobs_per_month"],
            max_pages_per_job=plan_limits["max_pages_per_job"],
            priority_processing=plan_limits["priority_processing"],
            custom_models=plan_limits["custom_models"],
            sso=plan_limits["sso"],
            dedicated_support=plan_limits["dedicated_support"],
        ),
        status=active_sub.status if active_sub else None,
        stripe_subscription_id=active_sub.stripe_subscription_id if active_sub else None,
        current_period_start=active_sub.current_period_start if active_sub else None,
        current_period_end=active_sub.current_period_end if active_sub else None,
    )


# ──────────────────────────────────────────────────────────────────────
# GET /billing/usage
# ──────────────────────────────────────────────────────────────────────


@router.get("/usage", response_model=UsageStats)
async def get_usage(
    user: Annotated[UserRecord, Depends(get_current_user)],
    db: Annotated[PgDatabase, Depends(get_db)],
) -> UsageStats:
    """Return usage statistics for the current billing period.

    Jobs created and pages processed are counted from the start of the
    current subscription period (or the start of the current calendar
    month for free-tier users).
    """
    plan_slug = user.plan
    plan_limits = PLAN_LIMITS.get(plan_slug, PLAN_LIMITS["free"])

    # Determine the period start
    subs = await db.list_subscriptions_for_user(user.id, status="active")
    active_sub = subs[0] if subs else None

    if active_sub and active_sub.current_period_start:
        period_start = active_sub.current_period_start
        period_end = active_sub.current_period_end
    else:
        # Free-tier: current calendar month
        now = datetime.now(timezone.utc)
        period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # End of month
        if now.month == 12:
            period_end = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            period_end = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)

    # Count jobs created by filtering on the job creation endpoint
    jobs_created = await db.count_usage_for_user_by_endpoint(
        user.id, endpoint="POST /v1/jobs", since=period_start,
    )
    pages_total = await db.sum_pages_processed_for_user(user.id, since=period_start)

    return UsageStats(
        jobs_created=jobs_created,
        pages_processed=pages_total,
        period_start=period_start,
        period_end=period_end,
        jobs_limit=plan_limits["jobs_per_month"],
        pages_limit_per_job=plan_limits["max_pages_per_job"],
    )
