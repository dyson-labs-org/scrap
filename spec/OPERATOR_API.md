# SCRAP Operator Service API Specification

## Status: Draft

This document specifies the **Operator API** that satellite operators must implement to participate in the SCRAP ecosystem. The API enables customers to:

1. **Discover** operator capabilities and satellite pubkeys
2. **Request** signed capability tokens for satellite tasking
3. **Manage** token lifecycle (status, revocation)
4. **Query** payment channel information for settlement

---

## 1. Overview

### 1.1 Purpose

SCRAP capability tokens are issued by satellite operators and verified on-orbit by target satellites. For this to work, operators must provide an internet-accessible service where customers can:

- Obtain the operator's signing public key (trust root)
- Obtain satellite identity public keys (for onion routing encryption)
- Request capability tokens with specific constraints
- Query token status and request revocation

### 1.2 Design Principles

| Principle | Rationale |
|-----------|-----------|
| **Single standard API** | Avoid integration nightmare of per-operator custom APIs |
| **REST/JSON** | Industry standard, tooling available in every language |
| **OAuth2 authentication** | Already used by Planet, Maxar, ICEYE |
| **OGC-style conformance** | Modular, testable, extensible |
| **STAPI-compatible** | Align with emerging satellite tasking standard where possible |

### 1.3 Relationship to STAPI

This specification is designed for potential alignment with [STAPI (Sensor Tasking API)](https://github.com/stapi-spec/stapi-spec), an emerging standard for satellite data ordering. SCRAP extends STAPI concepts with:

- Cryptographic identity (operator and satellite pubkeys)
- Signed capability tokens (not just order IDs)
- Payment channel binding (Lightning Network integration)

If STAPI reaches 1.0 and gains adoption, SCRAP Operator API could become a STAPI conformance class (`/conf/scap-tokens`).

---

## 2. Conformance Classes

Following [OGC API conventions](https://ogcapi.ogc.org/common/overview.html), this specification defines modular conformance classes:

```
SCRAP Operator API Conformance Classes
│
├── /conf/core                    [REQUIRED]
│   ├── GET  /
│   ├── GET  /conformance
│   └── GET  /operator
│
├── /conf/satellites              [REQUIRED]
│   ├── GET  /satellites
│   └── GET  /satellites/{norad_id}
│
├── /conf/tokens                  [REQUIRED]
│   ├── POST /tokens
│   ├── GET  /tokens/{token_id}
│   └── GET  /tokens
│
├── /conf/token-revocation        [OPTIONAL]
│   └── DELETE /tokens/{token_id}
│
├── /conf/token-quotes            [OPTIONAL]
│   └── POST /tokens/quote
│
└── /conf/lightning               [OPTIONAL]
    ├── GET  /channels
    └── GET  /channels/{channel_id}
```

An operator's `/conformance` endpoint declares which classes are implemented:

```json
{
  "conformsTo": [
    "https://scap.dev/spec/1.0/conf/core",
    "https://scap.dev/spec/1.0/conf/satellites",
    "https://scap.dev/spec/1.0/conf/tokens",
    "https://scap.dev/spec/1.0/conf/token-revocation",
    "https://scap.dev/spec/1.0/conf/lightning"
  ]
}
```

---

## 3. Authentication

### 3.1 OAuth2 Client Credentials Flow

All endpoints except `GET /` and `GET /conformance` require authentication.

Operators MUST implement [OAuth2 Client Credentials](https://datatracker.ietf.org/doc/html/rfc6749#section-4.4) flow:

```
┌─────────────┐                              ┌─────────────┐
│   Customer  │                              │  Operator   │
│   Client    │                              │  Auth Server│
└──────┬──────┘                              └──────┬──────┘
       │                                            │
       │  POST /oauth/token                         │
       │  grant_type=client_credentials             │
       │  client_id=<customer_id>                   │
       │  client_secret=<customer_secret>           │
       │─────────────────────────────────────────────>
       │                                            │
       │  { "access_token": "eyJ...",               │
       │    "token_type": "Bearer",                 │
       │    "expires_in": 3600 }                    │
       │<─────────────────────────────────────────────
       │                                            │
       │  GET /satellites                           │
       │  Authorization: Bearer eyJ...              │
       │─────────────────────────────────────────────>
       │                                            │
```

### 3.2 Token Requirements

| Parameter | Requirement |
|-----------|-------------|
| Token lifetime | 1 hour (3600 seconds) recommended |
| Token type | Bearer |
| Refresh | Client requests new token before expiration |

### 3.3 Customer Registration

Customer registration is out of scope for this specification. Operators may implement:
- Web portal registration
- API-based registration
- Manual/contractual onboarding

Customers receive `client_id` and `client_secret` through the registration process.

---

## 4. Endpoints

### 4.1 Landing Page

```
GET /
```

Returns API metadata and links to other endpoints.

**Response** `200 OK`:
```json
{
  "title": "ESA Copernicus SCRAP Operator API",
  "description": "Capability token issuance for Sentinel constellation",
  "version": "1.0.0",
  "scap_version": "1.0",
  "links": [
    {
      "rel": "self",
      "href": "https://scap.copernicus.eu/",
      "type": "application/json"
    },
    {
      "rel": "conformance",
      "href": "https://scap.copernicus.eu/conformance",
      "type": "application/json"
    },
    {
      "rel": "operator",
      "href": "https://scap.copernicus.eu/operator",
      "type": "application/json"
    },
    {
      "rel": "satellites",
      "href": "https://scap.copernicus.eu/satellites",
      "type": "application/json"
    },
    {
      "rel": "tokens",
      "href": "https://scap.copernicus.eu/tokens",
      "type": "application/json"
    }
  ]
}
```

---

### 4.2 Conformance

```
GET /conformance
```

Returns list of conformance classes implemented by this API.

**Response** `200 OK`:
```json
{
  "conformsTo": [
    "https://scap.dev/spec/1.0/conf/core",
    "https://scap.dev/spec/1.0/conf/satellites",
    "https://scap.dev/spec/1.0/conf/tokens",
    "https://scap.dev/spec/1.0/conf/lightning"
  ]
}
```

---

### 4.3 Operator Metadata

```
GET /operator
```

Returns operator identity and cryptographic keys.

**Authentication**: Required

**Response** `200 OK`:
```json
{
  "operator_id": "ESA-COPERNICUS",
  "name": "European Space Agency - Copernicus Programme",
  "contact": {
    "email": "scap-support@copernicus.eu",
    "url": "https://copernicus.eu"
  },
  "signing_pubkey": "02a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2",
  "signing_pubkey_format": "secp256k1-compressed-hex",
  "signing_algorithm": "ES256K",
  "lightning": {
    "node_pubkey": "03f8a2b1c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2",
    "node_alias": "ESA-SCRAP-NODE",
    "network": "mainnet"
  },
  "capabilities_offered": [
    "cmd:imaging:msi",
    "cmd:imaging:sar",
    "cmd:attitude:point",
    "data:relay:*"
  ],
  "token_constraints": {
    "max_lifetime_hours": 168,
    "max_delegation_depth": 3,
    "supported_currencies": ["BTC"]
  }
}
```

**Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `operator_id` | string | Unique operator identifier (used in token `iss` field) |
| `signing_pubkey` | string | Operator's secp256k1 public key for token signatures |
| `signing_pubkey_format` | string | Always `secp256k1-compressed-hex` (33 bytes, hex-encoded) |
| `signing_algorithm` | string | Always `ES256K` (ECDSA with secp256k1) |
| `lightning.node_pubkey` | string | Operator's Lightning Network node pubkey |
| `capabilities_offered` | array | Capability types this operator can issue tokens for |
| `token_constraints` | object | Limits on tokens this operator will issue |

---

### 4.4 Satellite Catalog

```
GET /satellites
```

Returns list of satellites operated by this operator.

**Authentication**: Required

**Query Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `status` | string | Filter by status: `operational`, `commissioning`, `decommissioned` |
| `capability` | string | Filter by capability (e.g., `cmd:imaging:sar`) |
| `limit` | integer | Max results (default 100) |
| `offset` | integer | Pagination offset |

**Response** `200 OK`:
```json
{
  "satellites": [
    {
      "norad_id": 62261,
      "name": "SENTINEL-2C",
      "cospar_id": "2024-123A",
      "status": "operational",
      "identity_pubkey": "03b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5",
      "identity_pubkey_format": "secp256k1-compressed-hex",
      "capabilities": [
        "cmd:imaging:msi",
        "cmd:attitude:point",
        "data:receive:msi_l1b"
      ],
      "orbit": {
        "type": "SSO",
        "altitude_km": 786,
        "inclination_deg": 98.62,
        "ltan": "10:30"
      },
      "constraints": {
        "geographic_bounds": null,
        "max_off_nadir_deg": 30
      },
      "links": [
        {
          "rel": "self",
          "href": "https://scap.copernicus.eu/satellites/62261"
        }
      ]
    },
    {
      "norad_id": 62262,
      "name": "SENTINEL-1C",
      "cospar_id": "2024-124A",
      "status": "operational",
      "identity_pubkey": "02c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
      "identity_pubkey_format": "secp256k1-compressed-hex",
      "capabilities": [
        "cmd:imaging:sar:iw",
        "cmd:imaging:sar:ew",
        "cmd:attitude:point"
      ],
      "orbit": {
        "type": "SSO",
        "altitude_km": 693,
        "inclination_deg": 98.18,
        "ltan": "06:00"
      },
      "constraints": {
        "geographic_bounds": null,
        "max_off_nadir_deg": 45
      },
      "links": [
        {
          "rel": "self",
          "href": "https://scap.copernicus.eu/satellites/62262"
        }
      ]
    }
  ],
  "total": 2,
  "limit": 100,
  "offset": 0
}
```

---

### 4.5 Satellite Detail

```
GET /satellites/{norad_id}
```

Returns detailed information about a specific satellite.

**Authentication**: Required

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `norad_id` | integer | NORAD catalog ID |

**Response** `200 OK`:
```json
{
  "norad_id": 62261,
  "name": "SENTINEL-2C",
  "cospar_id": "2024-123A",
  "status": "operational",
  "identity_pubkey": "03b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5",
  "identity_pubkey_format": "secp256k1-compressed-hex",
  "capabilities": [
    {
      "capability": "cmd:imaging:msi",
      "description": "Multispectral Instrument imaging",
      "parameters": {
        "bands": ["B02", "B03", "B04", "B08"],
        "resolution_m": [10, 10, 10, 10],
        "swath_km": 290
      },
      "pricing": {
        "rate_sats_per_km2": 100,
        "min_area_km2": 100,
        "currency": "BTC"
      }
    },
    {
      "capability": "cmd:attitude:point",
      "description": "Off-nadir pointing",
      "parameters": {
        "max_off_nadir_deg": 30,
        "slew_rate_deg_per_sec": 1.0
      },
      "pricing": {
        "rate_sats_per_maneuver": 5000,
        "currency": "BTC"
      }
    }
  ],
  "orbit": {
    "type": "SSO",
    "altitude_km": 786,
    "inclination_deg": 98.62,
    "ltan": "10:30",
    "period_min": 100.6,
    "tle": {
      "line1": "1 62261U 24123A   25001.50000000  .00000000  00000-0  00000-0 0  9999",
      "line2": "2 62261  98.6200 123.4567 0001234  90.0000 270.0000 14.30000000000017"
    }
  },
  "ground_stations": [
    {
      "name": "Svalbard",
      "location": {"lat": 78.23, "lon": 15.39},
      "typical_contacts_per_day": 14
    },
    {
      "name": "Matera",
      "location": {"lat": 40.65, "lon": 16.70},
      "typical_contacts_per_day": 4
    }
  ],
  "links": [
    {
      "rel": "self",
      "href": "https://scap.copernicus.eu/satellites/62261"
    },
    {
      "rel": "operator",
      "href": "https://scap.copernicus.eu/operator"
    }
  ]
}
```

---

### 4.6 Request Capability Token

```
POST /tokens
```

Request a signed capability token.

**Authentication**: Required

**Request Body**:
```json
{
  "subject": "ICEYE-X14-51070",
  "subject_pubkey": "02abc123def456789...",
  "audience": "SENTINEL-2C-62261",
  "capabilities": [
    "cmd:imaging:msi",
    "cmd:attitude:point"
  ],
  "constraints": {
    "geographic_bounds": {
      "type": "Polygon",
      "coordinates": [[
        [-122.5, 37.5], [-122.0, 37.5],
        [-122.0, 38.0], [-122.5, 38.0],
        [-122.5, 37.5]
      ]]
    },
    "valid_from": "2025-01-15T00:00:00Z",
    "valid_until": "2025-01-16T00:00:00Z",
    "max_tasks": 5,
    "max_off_nadir_deg": 20
  },
  "payment": {
    "max_amount_sats": 50000,
    "channel_id": "abc123..."
  },
  "delegation": {
    "allow_delegation": true,
    "max_depth": 2,
    "allowed_delegates": ["STARLINK-*"]
  }
}
```

**Request Fields**:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `subject` | string | Yes | Commanding satellite identifier (for token `sub` field) |
| `subject_pubkey` | string | Yes | Commander's secp256k1 pubkey (compressed hex) |
| `audience` | string | Yes | Target satellite identifier (for token `aud` field) |
| `capabilities` | array | Yes | Capabilities to grant |
| `constraints` | object | No | Restrictions on token usage |
| `constraints.geographic_bounds` | GeoJSON | No | AOI restriction |
| `constraints.valid_from` | ISO8601 | No | Token `nbf` (default: now) |
| `constraints.valid_until` | ISO8601 | Yes | Token `exp` |
| `constraints.max_tasks` | integer | No | Rate limit |
| `payment` | object | No | Payment terms |
| `payment.max_amount_sats` | integer | No | Budget cap in satoshis |
| `payment.channel_id` | string | No | Lightning channel for settlement |
| `delegation` | object | No | Delegation permissions |

**Response** `201 Created`:
```json
{
  "token_id": "ESA-1705320000-a1b2c3d4e5f6789012345678abcdef01",
  "token": "omlzaWduYXR1cmVYQDBhMjM0NTY3ODlhYmNkZWYwMTIzNDU2Nzg5YWJjZGVmMDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWZncGF5bG9hZKR...",
  "token_format": "CBOR+ECDSA",
  "token_decoded": {
    "header": {
      "alg": "ES256K",
      "typ": "SAT-CAP",
      "enc": "CBOR"
    },
    "payload": {
      "iss": "ESA-COPERNICUS",
      "sub": "ICEYE-X14-51070",
      "aud": "SENTINEL-2C-62261",
      "iat": 1705320000,
      "nbf": 1705320000,
      "exp": 1705406400,
      "token_id": "ESA-1705320000-a1b2c3d4e5f6789012345678abcdef01",
      "cap": ["cmd:imaging:msi", "cmd:attitude:point"],
      "cns": {
        "geographic_bounds": { "type": "Polygon", "coordinates": [...] },
        "max_tasks": 5,
        "max_off_nadir_deg": 20
      },
      "cmd_pub": "02abc123def456789...",
      "pmt": {
        "currency": "BTC",
        "max_amount_sats": 50000,
        "channel_id": "abc123..."
      }
    }
  },
  "status": "active",
  "created_at": "2025-01-15T00:00:00Z",
  "expires_at": "2025-01-16T00:00:00Z",
  "links": [
    {
      "rel": "self",
      "href": "https://scap.copernicus.eu/tokens/ESA-1705320000-a1b2c3d4e5f6789012345678abcdef01"
    }
  ]
}
```

**Error Responses**:

| Status | Code | Description |
|--------|------|-------------|
| `400` | `invalid_request` | Malformed request body |
| `400` | `invalid_capability` | Requested capability not available for target satellite |
| `400` | `invalid_constraint` | Constraint violates operator policy |
| `400` | `invalid_subject_pubkey` | Subject pubkey is malformed |
| `401` | `unauthorized` | Missing or invalid access token |
| `403` | `forbidden` | Customer not authorized for requested capabilities |
| `404` | `satellite_not_found` | Target satellite not found |
| `422` | `constraint_conflict` | Constraints are mutually exclusive |

---

### 4.7 Get Token Status

```
GET /tokens/{token_id}
```

Returns status of a previously issued token.

**Authentication**: Required

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `token_id` | string | Token ID |

**Response** `200 OK`:
```json
{
  "token_id": "ESA-1705320000-a1b2c3d4e5f6789012345678abcdef01",
  "status": "active",
  "created_at": "2025-01-15T00:00:00Z",
  "expires_at": "2025-01-16T00:00:00Z",
  "subject": "ICEYE-X14-51070",
  "audience": "SENTINEL-2C-62261",
  "capabilities": ["cmd:imaging:msi", "cmd:attitude:point"],
  "usage": {
    "tasks_executed": 2,
    "tasks_remaining": 3,
    "amount_spent_sats": 15000,
    "amount_remaining_sats": 35000
  },
  "links": [
    {
      "rel": "self",
      "href": "https://scap.copernicus.eu/tokens/ESA-1705320000-a1b2c3d4e5f6789012345678abcdef01"
    }
  ]
}
```

**Token Status Values**:

| Status | Description |
|--------|-------------|
| `active` | Token is valid and can be used |
| `expired` | Token has passed its `exp` time |
| `revoked` | Token was revoked by operator or customer |
| `exhausted` | Token reached `max_tasks` or `max_amount` limit |

---

### 4.8 List Customer Tokens

```
GET /tokens
```

Returns list of tokens issued to the authenticated customer.

**Authentication**: Required

**Query Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `status` | string | Filter by status |
| `audience` | string | Filter by target satellite |
| `limit` | integer | Max results (default 100) |
| `offset` | integer | Pagination offset |

**Response** `200 OK`:
```json
{
  "tokens": [
    {
      "token_id": "ESA-1705320000-a1b2c3d4e5f6789012345678abcdef01",
      "status": "active",
      "audience": "SENTINEL-2C-62261",
      "capabilities": ["cmd:imaging:msi"],
      "expires_at": "2025-01-16T00:00:00Z"
    },
    {
      "token_id": "ESA-1705233600-fedcba9876543210fedcba9876543210",
      "status": "expired",
      "audience": "SENTINEL-1C-62262",
      "capabilities": ["cmd:imaging:sar:iw"],
      "expires_at": "2025-01-14T00:00:00Z"
    }
  ],
  "total": 2,
  "limit": 100,
  "offset": 0
}
```

---

### 4.9 Revoke Token

```
DELETE /tokens/{token_id}
```

Revoke a previously issued token.

**Conformance Class**: `/conf/token-revocation` (optional)

**Authentication**: Required

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `token_id` | string | Token ID |

**Response** `200 OK`:
```json
{
  "token_id": "ESA-1705320000-a1b2c3d4e5f6789012345678abcdef01",
  "status": "revoked",
  "revoked_at": "2025-01-15T12:00:00Z",
  "revoked_by": "customer"
}
```

**Notes**:
- Revocation is recorded by the operator
- Operator SHOULD propagate revocation to satellite during next ground contact
- Satellite MAY continue to accept token until revocation is received
- Revocation is best-effort, not guaranteed real-time

---

### 4.10 Token Quote (Optional)

```
POST /tokens/quote
```

Get a price quote for a capability token without issuing it.

**Conformance Class**: `/conf/token-quotes` (optional)

**Authentication**: Required

**Request Body**: Same as `POST /tokens`

**Response** `200 OK`:
```json
{
  "quote_id": "quote-abc123",
  "valid_until": "2025-01-15T01:00:00Z",
  "pricing": {
    "base_fee_sats": 1000,
    "capability_fees": [
      {"capability": "cmd:imaging:msi", "fee_sats": 5000},
      {"capability": "cmd:attitude:point", "fee_sats": 2000}
    ],
    "total_fee_sats": 8000,
    "estimated_task_cost_sats": 25000,
    "currency": "BTC"
  },
  "constraints_applied": {
    "geographic_bounds": "accepted",
    "max_tasks": "accepted",
    "max_off_nadir_deg": "reduced to 20 (satellite limit)"
  }
}
```

---

### 4.11 Lightning Channel Information

```
GET /channels
```

Returns Lightning Network channel information for payment settlement.

**Conformance Class**: `/conf/lightning` (optional)

**Authentication**: Required

**Response** `200 OK`:
```json
{
  "node_pubkey": "03f8a2b1c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2",
  "node_alias": "ESA-SCRAP-NODE",
  "network": "mainnet",
  "channels": [
    {
      "channel_id": "abc123def456",
      "remote_pubkey": "02customer_node_pubkey...",
      "capacity_sats": 1000000,
      "local_balance_sats": 600000,
      "remote_balance_sats": 400000,
      "status": "active"
    }
  ],
  "connection": {
    "host": "scap-ln.copernicus.eu",
    "port": 9735,
    "tor": "scaplnxyz123.onion:9735"
  }
}
```

---

### 4.12 Channel Detail

```
GET /channels/{channel_id}
```

Returns detailed information about a specific Lightning channel.

**Conformance Class**: `/conf/lightning` (optional)

**Authentication**: Required

**Response** `200 OK`:
```json
{
  "channel_id": "abc123def456",
  "funding_txid": "a1b2c3d4e5f6...",
  "funding_output_index": 0,
  "capacity_sats": 1000000,
  "local_balance_sats": 600000,
  "remote_balance_sats": 400000,
  "status": "active",
  "opened_at": "2025-01-01T00:00:00Z",
  "last_update": "2025-01-15T00:00:00Z",
  "pending_htlcs": []
}
```

---

## 5. Data Models

### 5.1 Common Types

#### GeoJSON Polygon
```json
{
  "type": "Polygon",
  "coordinates": [[[lon1, lat1], [lon2, lat2], [lon3, lat3], [lon1, lat1]]]
}
```

#### ISO8601 DateTime
```
"2025-01-15T00:00:00Z"
```

#### secp256k1 Public Key (Compressed Hex)
```
"02a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2"
```
33 bytes (compressed), hex-encoded to 66 characters.

### 5.2 Capability Token (SAT-CAP)

See [SCRAP.md §2](SCRAP.md#2-authorization-layer-capability-tokens) for full token specification.

The `token` field in API responses is the CBOR-encoded, ECDSA-signed token ready for upload to the commanding satellite.

---

## 6. Error Handling

### 6.1 Error Response Format

All errors return a JSON object:

```json
{
  "error": {
    "code": "invalid_request",
    "message": "The 'capabilities' field is required",
    "details": {
      "field": "capabilities",
      "reason": "missing"
    }
  }
}
```

### 6.2 Error Codes

| HTTP Status | Code | Description |
|-------------|------|-------------|
| 400 | `invalid_request` | Malformed request |
| 400 | `invalid_capability` | Unknown or unavailable capability |
| 400 | `invalid_constraint` | Constraint violates policy |
| 400 | `invalid_pubkey` | Malformed public key |
| 401 | `unauthorized` | Missing or invalid auth token |
| 403 | `forbidden` | Not authorized for operation |
| 404 | `not_found` | Resource not found |
| 409 | `conflict` | Resource state conflict |
| 422 | `unprocessable` | Valid syntax but semantic error |
| 429 | `rate_limited` | Too many requests |
| 500 | `internal_error` | Server error |
| 503 | `unavailable` | Service temporarily unavailable |

---

## 7. Security Considerations

### 7.1 Transport Security

- All endpoints MUST be served over HTTPS (TLS 1.2+)
- HSTS SHOULD be enabled
- Certificate transparency SHOULD be used

### 7.2 Key Security

- Operator signing key MUST be stored in HSM or secure enclave
- Satellite identity keys are burned in at manufacturing
- Customer `client_secret` SHOULD be rotated periodically

### 7.3 Token Security

- Tokens SHOULD have short lifetimes (24-48 hours typical)
- Revocation SHOULD be propagated to satellites promptly
- Used token IDs (`token_id`) MUST be cached on satellites to prevent replay

### 7.4 Rate Limiting

Operators SHOULD implement rate limiting:
- Per-customer request limits
- Per-satellite token issuance limits
- Global API rate limits

---

## 8. Implementation Notes

### 8.1 STAPI Alignment

If implementing alongside STAPI:

| STAPI Endpoint | SCRAP Equivalent | Notes |
|----------------|-----------------|-------|
| `GET /products` | `GET /satellites` | Satellites are "products" |
| `POST /products/{id}/opportunities` | N/A | Use TLE for pass prediction |
| `POST /products/{id}/orders` | `POST /tokens` | Tokens replace orders |
| `GET /orders/{id}` | `GET /tokens/{token_id}` | Token status |

### 8.2 Reference Implementation

A reference implementation using FastAPI (Python) is planned:
- `scap-operator-api` - Reference server
- `scap-client` - Python client library

### 8.3 OpenAPI Specification

The complete OpenAPI 3.1 specification is available at:
- `schemas/operator-api.yaml` (planned)

---

## 9. References

- [SCRAP.md](SCRAP.md) - Core protocol specification
- [STAPI Specification](https://github.com/stapi-spec/stapi-spec) - Sensor Tasking API
- [OGC API - Common](https://ogcapi.ogc.org/common/overview.html) - Conformance class patterns
- [OAuth2 Client Credentials](https://datatracker.ietf.org/doc/html/rfc6749#section-4.4) - Authentication
- [RFC 7519 - JWT](https://datatracker.ietf.org/doc/html/rfc7519) - Token format inspiration

---

## 10. Changelog

| Version | Date | Changes |
|---------|------|---------|
| 0.1 | 2025-12-29 | Initial draft |
