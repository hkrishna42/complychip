"""ComplyChip V3 - Notification Service"""
from __future__ import annotations

from typing import Optional

from backend.services.n8n_client import trigger_send_reminder


async def send_reminder_email(reminder: dict) -> bool:
    """Send a reminder email via n8n workflow.

    reminder should contain: recipient_email, subject, body,
    and optionally entity_id, document_id, reminder_type.
    Returns True if the workflow was triggered successfully.
    """
    try:
        result = await trigger_send_reminder(
            recipient_email=reminder.get("recipient_email", ""),
            subject=reminder.get("subject", "Compliance Reminder"),
            body=reminder.get("body", ""),
            entity_id=reminder.get("entity_id", ""),
            document_id=reminder.get("document_id", ""),
            reminder_type=reminder.get("reminder_type", "expiry"),
            organization_id=reminder.get("organization_id", ""),
        )
        return result.get("status") != "error"
    except Exception as e:
        print(f"Warning: Reminder email failed: {e}")
        return False


async def send_webhook_notification(url: str, payload: dict) -> bool:
    """Send a generic webhook notification via HTTP POST.

    Returns True if the webhook responded with a success status.
    """
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload)
            return resp.status_code < 400
    except Exception as e:
        print(f"Warning: Webhook notification failed: {e}")
        return False


async def send_batch_reminders(reminders: list) -> dict:
    """Send multiple reminder emails.

    Returns a summary dict with sent count and failures.
    """
    sent = 0
    failed = 0
    errors = []

    for reminder in reminders:
        try:
            success = await send_reminder_email(reminder)
            if success:
                sent += 1
            else:
                failed += 1
                errors.append(reminder.get("recipient_email", "unknown"))
        except Exception as e:
            failed += 1
            errors.append(f"{reminder.get('recipient_email', 'unknown')}: {e}")

    return {
        "total": len(reminders),
        "sent": sent,
        "failed": failed,
        "errors": errors[:10],  # cap error list
    }
