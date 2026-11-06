# Copyright 2026 Skyfire Systems Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Tests for kyapay token verification."""

import base64
import hashlib
import hmac
import json
import time
import uuid

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from kyapay_a2a.core import protocol
from kyapay_a2a.types import KyaPayRequirements, KyaPayToken

SELLER_SERVICE_ID = "5e7f3359-9ec1-4078-bf45-401d079af1be"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _jwk(key: ec.EllipticCurvePrivateKey, kid: str) -> dict:
    numbers = key.public_key().public_numbers()
    return {
        "kty": "EC",
        "crv": "P-256",
        "use": "sig",
        "alg": "ES256",
        "kid": kid,
        "x": _b64(numbers.x.to_bytes(32, "big")),
        "y": _b64(numbers.y.to_bytes(32, "big")),
    }


def _signing_input(header: dict, claims: dict) -> str:
    return f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(claims).encode())}"


def _es256(header: dict, claims: dict, key: ec.EllipticCurvePrivateKey) -> str:
    signing_input = _signing_input({"alg": "ES256", **header}, claims)
    r, s = decode_dss_signature(key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
    return f"{signing_input}.{_b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


def _hs256(header: dict, claims: dict, secret: bytes) -> str:
    signing_input = _signing_input({"alg": "HS256", **header}, claims)
    signature = hmac.new(secret, signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64(signature)}"


def _claims(**overrides) -> dict:
    now = int(time.time())
    return {
        "iss": protocol.JWT_ISSUER,
        "aud": SELLER_SERVICE_ID,
        "sub": str(uuid.uuid4()),
        "jti": str(uuid.uuid4()),
        "iat": now - 10,
        "exp": now + 300,
        "env": "production",
        "val": 50000,
        "amt": "0.050",
        "cur": "USD",
        **overrides,
    }


HEADER = {"typ": "pay+JWT", "kid": "key-1"}
SIGNING_KEY = ec.generate_private_key(ec.SECP256R1())
ROTATED_KEY = ec.generate_private_key(ec.SECP256R1())
UNKNOWN_KEY = ec.generate_private_key(ec.SECP256R1())
JWKS = {"keys": [_jwk(SIGNING_KEY, "key-1"), _jwk(ROTATED_KEY, "key-2")]}

REQUIREMENTS = KyaPayRequirements(
    seller_service_id=SELLER_SERVICE_ID,
    token_amount="0.050",
    token_type="pay",
    description="Test Payment for API Access",
    resource="/api/test",
)


@pytest.fixture(autouse=True)
def jwks(monkeypatch):
    monkeypatch.setattr(protocol, "_get_jwks", lambda *_: JWKS)


async def _verify(token: str, audience=SELLER_SERVICE_ID):
    return await protocol.verify_token(
        KyaPayToken(token=token, token_type="pay"), REQUIREMENTS, audience=audience
    )


@pytest.mark.asyncio
async def test_accepts_a_valid_token():
    claims = _claims()

    result = await _verify(_es256(HEADER, claims, SIGNING_KEY))

    assert result.is_valid
    assert result.token_data == claims


@pytest.mark.asyncio
async def test_accepts_a_token_signed_by_any_key_in_the_jwks():
    token = _es256({**HEADER, "kid": "key-2"}, _claims(), ROTATED_KEY)

    result = await _verify(token)

    assert result.is_valid


@pytest.mark.asyncio
async def test_accepts_a_token_without_a_kid():
    token = _es256({"typ": "pay+JWT"}, _claims(), SIGNING_KEY)

    result = await _verify(token)

    assert result.is_valid


@pytest.mark.asyncio
async def test_skips_the_audience_check_when_no_audience_is_given():
    token = _es256(HEADER, _claims(aud="some-other-seller"), SIGNING_KEY)

    result = await _verify(token, audience=None)

    assert result.is_valid


def _public_key_bytes(encoding: serialization.Encoding) -> bytes:
    return SIGNING_KEY.public_key().public_bytes(
        encoding, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def _tampered() -> str:
    header, _, signature = _es256(HEADER, _claims(), SIGNING_KEY).split(".")
    return f"{header}.{_b64(json.dumps(_claims(amt='999')).encode())}.{signature}"


REJECTED = {
    "signed by a key not in the jwks": lambda: _es256(HEADER, _claims(), UNKNOWN_KEY),
    "signed with a kid that names another key": lambda: _es256(
        {**HEADER, "kid": "key-2"}, _claims(), UNKNOWN_KEY
    ),
    "HS256 keyed with the PEM public key": lambda: _hs256(
        HEADER, _claims(), _public_key_bytes(serialization.Encoding.PEM)
    ),
    "HS256 keyed with the DER public key": lambda: _hs256(
        HEADER, _claims(), _public_key_bytes(serialization.Encoding.DER)
    ),
    "alg none": lambda: f"{_signing_input({'alg': 'none', **HEADER}, _claims())}.",
    "tampered payload": _tampered,
    "wrong issuer": lambda: _es256(HEADER, _claims(iss="https://evil.example"), SIGNING_KEY),
    "wrong audience": lambda: _es256(HEADER, _claims(aud="some-other-seller"), SIGNING_KEY),
    "expired": lambda: _es256(HEADER, _claims(exp=int(time.time()) - 60), SIGNING_KEY),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("make_token", REJECTED.values(), ids=REJECTED.keys())
async def test_rejects(make_token):
    result = await _verify(make_token())

    assert not result.is_valid
    assert result.token_data is None
    assert result.invalid_reason.startswith("JWT verification failed")
