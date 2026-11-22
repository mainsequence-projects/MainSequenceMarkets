# Settings Route

The settings route exposes read-only app settings and runtime assumptions for
frontend clients.

```text
GET /api/v1/settings/
```

Response model: `ApiSettingsResponse`

This endpoint does not expose request identity, access tokens, refresh tokens,
or other secrets.

## Response

```json
{
  "app": {
    "name": "MainSequence Markets Public API",
    "scope": "apps/v1",
    "version": "4.3.14"
  },
  "runtime": {
    "namespace": "mainsequence.markets",
    "default_namespace": "mainsequence.markets",
    "management_mode": "platform_managed",
    "schema_mutation_allowed": false,
    "requires_migrations": true
  },
  "documentation": {
    "openapi_url": "/openapi.json",
    "swagger_url": "/docs",
    "redoc_url": "/redoc"
  },
  "assumptions": [
    {
      "key": "namespace",
      "label": "Markets namespace",
      "value": "mainsequence.markets",
      "source": "msm.settings",
      "description": "Runtime MetaTables and time-index table updaters resolve against this namespace."
    },
    {
      "key": "runtime_bootstrap",
      "label": "Runtime bootstrap",
      "value": "startup_attachment",
      "source": "apps/v1 runtime bootstrap",
      "description": "The API attaches markets and pricing runtime tables during application startup."
    },
    {
      "key": "schema_management",
      "label": "Schema management",
      "value": "migrations_required",
      "source": "apps/v1 runtime bootstrap",
      "description": "Schema mutation is not performed by this API; required MetaTable migrations must already be applied."
    }
  ]
}
```

`runtime.namespace` is always `mainsequence.markets`: Markets' own namespace cannot be
overridden.
