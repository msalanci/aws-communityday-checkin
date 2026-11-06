# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

"""Print requests for the print laptop: their ID, and sending them to the SQS print queue.

The print ID is uuid5(nonce, secret): a retry with the same nonce gives the same ID, which the
print laptop prints only once, and a nonce reused for another ticket gives another ID.
"""

import json
import uuid
from typing import Any


def print_id(nonce: str, secret: str) -> str:
    """Work out a print request's ID.

    Args:
        nonce: The phone's nonce, a UUID.
        secret: The ticket secret.

    Returns:
        The ID, a UUID in lowercase text.
    """
    return str(uuid.uuid5(uuid.UUID(nonce), secret))


def send(client: Any, queue_url: str, request_id: str, first_name: str, last_name: str) -> bool:
    """Send one print request.

    Args:
        client: The SQS client; boto3 retries a failed send itself.
        queue_url: The print queue's URL.
        request_id: The print ID.
        first_name: The attendee's first name, cleaned.
        last_name: The attendee's last name, cleaned.

    Returns:
        True when SQS accepted it; False when sending failed after boto3's retries.
    """
    from botocore.exceptions import BotoCoreError, ClientError

    body = json.dumps({"print_id": request_id, "first_name": first_name, "last_name": last_name}, ensure_ascii=False)
    try:
        client.send_message(QueueUrl=queue_url, MessageBody=body)
    except (BotoCoreError, ClientError):
        return False
    return True
