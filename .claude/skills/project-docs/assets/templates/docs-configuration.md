# Configuration

[One paragraph describing how configuration is loaded — environment variables, config file,
 command-line flags, or a combination. Note which takes precedence when multiple sources
 conflict.]

## Environment variables

[Cover every variable from .env.example, config.py, application.properties, or equivalent.
 Group related variables under headings if there are more than ~8 total.]

### [Group name, e.g. "Database"]

| Variable | Required | Default | Valid values | Description |
|---|---|---|---|---|
| `VAR_NAME` | Yes | — | — | [what it controls; what breaks if missing] |
| `VAR_NAME` | No | `value` | `a`, `b`, `c` | [what it controls; effect of each value] |

### [Group name, e.g. "LLM / AI Provider"]

| Variable | Required | Default | Valid values | Description |
|---|---|---|---|---|
| `VAR_NAME` | Yes | — | — | [description] |

[Repeat groups until all variables are covered.]

## Configuration file

[If the project uses a YAML/TOML/JSON/INI config file in addition to env vars, document
 its full structure here with inline comments explaining each field.]

```yaml
# [filename] — annotated example showing all supported fields

# [Section name]
[field]: [example value]  # [what it controls; valid range or options]
[field]: [example value]  # [what it controls]

# [Section name]
[nested]:
  [field]: [value]  # [description]
```

[If there is no config file (env vars only), omit this section.]

## Feature flags

[If the project has feature flags, document them here — name, default state, and what
 enabling them does. If there are no feature flags, omit this section.]

| Flag | Default | Description |
|---|---|---|
| `FLAG_NAME` | `false` | [what enabling this does; any caveats] |

## Secrets management

[Describe how secrets should be managed in production — e.g., "Use AWS Secrets Manager
 or Vault; never commit .env to version control; rotate JWT_SECRET immediately if exposed."]

[If the project has no special secrets beyond a database password or API key, keep this
 section brief — just the warning about .env and key rotation policy if there is one.]

<!-- generated-by: project-docs-skill -->
