import base64
import logging
from datetime import datetime, timezone

import httpx

from .models import TimestampResponse

logger = logging.getLogger(__name__)


async def obtain_timestamp(
    evidence_hash_hex: str,
    tsa_url: str = "https://freetsa.org/tsr",
) -> TimestampResponse:
    """
    Obtain an RFC 3161 timestamp token from a TSA.

    Builds a minimal DER-encoded TimeStampReq and POSTs it to the TSA.
    Returns base64-encoded DER TimeStampResp.
    """
    try:
        hash_bytes = bytes.fromhex(evidence_hash_hex)
        tsq_body = _build_timestamp_request(hash_bytes)

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                tsa_url,
                content=tsq_body,
                headers={"Content-Type": "application/timestamp-query"},
            )
            response.raise_for_status()

            tsr_bytes = response.content
            token_b64 = base64.b64encode(tsr_bytes).decode("ascii")

            return TimestampResponse(
                success=True,
                timestamp_token=token_b64,
                timestamped_at=datetime.now(timezone.utc).isoformat(),
                tsa_url=tsa_url,
            )
    except Exception as e:
        logger.error("TSA request failed: %s", e)
        return TimestampResponse(success=False, error=str(e))


def _build_timestamp_request(hash_bytes: bytes) -> bytes:
    """
    Build minimal ASN.1 DER-encoded RFC 3161 TimeStampReq.

    TimeStampReq ::= SEQUENCE {
        version        INTEGER { v1(1) },
        messageImprint MessageImprint,
        certReq        BOOLEAN TRUE
    }
    MessageImprint ::= SEQUENCE {
        hashAlgorithm  AlgorithmIdentifier (SHA-256),
        hashedMessage  OCTET STRING
    }
    """
    # SHA-256 AlgorithmIdentifier (OID 2.16.840.1.101.3.4.2.1)
    sha256_alg_id = bytes([
        0x30, 0x0D,
        0x06, 0x09,
        0x60, 0x86, 0x48, 0x01, 0x65, 0x03, 0x04, 0x02, 0x01,
        0x05, 0x00,
    ])

    hashed_message = _der_octet_string(hash_bytes)
    msg_imprint = _der_sequence(sha256_alg_id + hashed_message)
    version = bytes([0x02, 0x01, 0x01])
    cert_req = bytes([0x01, 0x01, 0xFF])

    return _der_sequence(version + msg_imprint + cert_req)


def _der_length(length: int) -> bytes:
    if length < 0x80:
        return bytes([length])
    elif length < 0x100:
        return bytes([0x81, length])
    else:
        return bytes([0x82, (length >> 8) & 0xFF, length & 0xFF])


def _der_sequence(content: bytes) -> bytes:
    return bytes([0x30]) + _der_length(len(content)) + content


def _der_octet_string(content: bytes) -> bytes:
    return bytes([0x04]) + _der_length(len(content)) + content
