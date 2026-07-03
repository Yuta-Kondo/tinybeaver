from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "contact@example.com")
VAPID_CLAIMS = {"sub": f"mailto:{CONTACT_EMAIL}"}


def send_push_to_all(title: str, body: str, url: str = "/") -> None:
    if not VAPID_PRIVATE_KEY:
        return
    from .memory import delete_push_subscription, list_push_subscriptions
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        logger.warning("pywebpush not installed; skipping push")
        return

    subs = list_push_subscriptions()
    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub["endpoint"],
                    "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
                },
                data=json.dumps({"title": title, "body": body, "url": url}),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS,
            )
        except WebPushException as e:
            status = getattr(e.response, "status_code", None) if e.response else None
            if status in (404, 410):
                delete_push_subscription(sub["endpoint"])
            else:
                logger.warning("Push failed for %s: %s", sub["endpoint"][:40], e)
        except Exception as e:
            logger.warning("Push error: %s", e)
