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
    "namespace": "mainsequence.examples",
    "namespace_source": "MSM_AUTO_REGISTER_NAMESPACE",
    "default_namespace": "mainsequence.markets",
    "auto_register_enabled": true,
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
      "value": "mainsequence.examples",
      "source": "MSM_AUTO_REGISTER_NAMESPACE",
      "description": "Runtime MetaTables and DataNodes resolve against this namespace."
    },
    {
      "key": "runtime_bootstrap",
      "label": "Runtime bootstrap",
      "value": "startup_attachment",
      "source": "apps/v1 runtime bootstrap",
      "description": "The API attaches markets and pricing runtime tables during application startup when auto-registration namespace is configured."
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

When `MSM_AUTO_REGISTER_NAMESPACE` is not set, `runtime.namespace` falls back to
`mainsequence.markets`, `runtime.namespace_source` is `default`, and
`runtime.auto_register_enabled` is `false`.
