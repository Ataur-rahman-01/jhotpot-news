"""
b2_client.py — Backblaze B2 client via the S3-compatible API (boto3).

Environment variables (required):
    B2_KEY_ID       application key ID from Backblaze console
    B2_APP_KEY      application key secret
    B2_ENDPOINT     S3-compatible endpoint, e.g. https://s3.us-west-004.backblazeb2.com
    B2_BUCKET_NAME  bucket name, e.g. bd-news-archive

All archive files are stored under:
    archives/{folder}/{filename}
"""

from __future__ import annotations

import os
from typing import List

import boto3
from botocore.exceptions import ClientError


class B2Client:
    def __init__(self) -> None:
        key_id   = os.environ["B2_KEY_ID"]
        app_key  = os.environ["B2_APP_KEY"]
        endpoint = os.environ["B2_ENDPOINT"]
        self._bucket = os.environ["B2_BUCKET_NAME"]

        self._s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=key_id,
            aws_secret_access_key=app_key,
        )

    def _key(self, filename: str, folder: str) -> str:
        return f"archives/{folder}/{filename}"

    def upload(self, filename: str, data: bytes, folder: str) -> None:
        """Upload bytes to archives/{folder}/{filename} with gzip content type."""
        self._s3.put_object(
            Bucket=self._bucket,
            Key=self._key(filename, folder),
            Body=data,
            ContentType="application/gzip",
        )

    def download(self, filename: str, folder: str) -> bytes:
        """Download archives/{folder}/{filename} and return raw bytes."""
        response = self._s3.get_object(
            Bucket=self._bucket,
            Key=self._key(filename, folder),
        )
        return response["Body"].read()

    def list_archives(self, folder: str) -> List[str]:
        """Return filenames (not full keys) under archives/{folder}/."""
        prefix = f"archives/{folder}/"
        filenames: List[str] = []

        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                filename = key[len(prefix):]
                if filename:
                    filenames.append(filename)

        return filenames

    def file_exists(self, filename: str, folder: str) -> bool:
        """Return True if archives/{folder}/{filename} exists in the bucket."""
        try:
            self._s3.head_object(
                Bucket=self._bucket,
                Key=self._key(filename, folder),
            )
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "404":
                return False
            raise
