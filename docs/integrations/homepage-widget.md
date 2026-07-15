# Homepage widget

Borg Backup UI provides a dedicated read-only endpoint for a
[Homepage](https://gethomepage.dev/) service widget. The endpoint summarizes
locally available status data and never starts Borg, a repository check, a
migration, or another background operation.

## Included status

- overall state: healthy, active, attention required, or critical
- enabled backup jobs and their latest result
- overdue backup jobs
- configured, verified, failed, and overdue restore tests
- currently running backup job names

The response does not include repository paths, user names, log output, raw
error messages, secrets, or credentials.

## Create the widget token

1. Sign in as an administrator.
2. Open **Settings > General > Homepage widget**.
3. Select **Create widget token**.
4. Copy the generated YAML before leaving the page.

The token is displayed once. It is stored with file mode `0600` and grants
access only to `GET /api/widget/summary`. It is not a general Borg Backup UI API
token.

Rotating the token invalidates the previous value immediately. Revoking it
disables external widget access until a new token is created.

## Homepage configuration

Add the generated service entry to the Homepage services configuration:

```yaml
- Borg Backup UI:
    href: http://unraid-host:8765/
    widget:
      type: customapi
      url: http://unraid-host:8765/api/widget/summary
      refreshInterval: 60000
      headers:
        X-Borg-Widget-Token: "REPLACE_WITH_WIDGET_TOKEN"
      mappings:
        - field: status.label
          label: Status
        - field: display.backups
          label: Backups
        - field: display.restore_tests
          label: Restore tests
        - field: display.active
          label: Active
```

Use an address that is reachable from the Homepage container. A refresh
interval of 60 seconds is recommended. Protect the Homepage configuration
because it contains the widget token.

## Endpoint response

The endpoint returns a versioned JSON object. Fields intended for direct
display are grouped below `display`; numeric values for later widget layouts
remain available below `backups`, `restore_tests`, and `active`.

```json
{
  "schema_version": 1,
  "status": {
    "state": "healthy",
    "label": "Healthy",
    "severity": 0
  },
  "display": {
    "backups": "11/11 successful",
    "restore_tests": "4/4 verified",
    "attention": "0",
    "active": "None"
  }
}
```

An HTTP `401` response means that the widget token is missing, invalid,
rotated, or revoked.
