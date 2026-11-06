# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

"""The print queue as the print laptop reads it: receive one print request, delete it after printing.

Uses the AWS CLI profile and region from .env; that profile's IAM user may only receive,
delete and read attributes on this one SQS queue. Long polling (20 s) keeps the laptop
idle between print requests.
"""

from dataclasses import dataclass
from typing import Any

WAIT_SECONDS = 20


@dataclass(frozen=True)
class QueueMessage:
    """One print request as SQS delivered it."""

    body: str
    receipt_handle: str
    receive_count: int


class PrintQueue:
    """The SQS print queue, read one message at a time with long polling."""

    def __init__(self, profile: str, region: str, queue_url: str, client: Any = None) -> None:
        """Connect to the queue.

        Args:
            profile: The AWS CLI profile with the print laptop's access key.
            region: The queue's AWS region.
            queue_url: The queue's URL.
            client: An SQS client to use instead of creating one; for tests.

        Returns:
            None.
        """
        self._queue_url = queue_url
        if client is None:
            import boto3
            from botocore.config import Config

            client = boto3.Session(profile_name=profile, region_name=region).client(
                "sqs",
                config=Config(
                    connect_timeout=5,
                    read_timeout=WAIT_SECONDS + 10,
                    retries={"mode": "standard", "max_attempts": 3},
                ),
            )
        self._client = client

    def name(self) -> str:
        """Give the queue's name, for the console.

        Args:
            None.

        Returns:
            The last part of the queue URL.
        """
        return self._queue_url.rstrip("/").rsplit("/", 1)[-1]

    def receive(self) -> QueueMessage | None:
        """Wait up to 20 seconds for one print request.

        Args:
            None.

        Returns:
            The message, or None when none arrived.
        """
        response = self._client.receive_message(
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=WAIT_SECONDS,
            MessageSystemAttributeNames=["ApproximateReceiveCount"],
        )
        messages = response.get("Messages") or []
        if not messages:
            return None
        message = messages[0]
        count = int((message.get("Attributes") or {}).get("ApproximateReceiveCount", "1"))
        return QueueMessage(message["Body"], message["ReceiptHandle"], count)

    def delete(self, message: QueueMessage) -> None:
        """Delete a print request from the queue.

        Args:
            message: The message to delete.

        Returns:
            None.
        """
        self._client.delete_message(QueueUrl=self._queue_url, ReceiptHandle=message.receipt_handle)
