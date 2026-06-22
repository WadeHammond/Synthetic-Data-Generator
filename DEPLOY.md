# Deploying to Azure

This project deploys to **Azure Container Apps** with the Azure Developer CLI (`azd`),
following the same pattern as the AIDA app:

| Concern | Resource |
|---|---|
| Web app | Azure Container Apps (single replica, external ingress on port 8000) |
| Image build/registry | Azure Container Registry (built remotely via ACR Tasks — no local Docker needed) |
| Image pull auth | User-assigned managed identity with `AcrPull` |
| Secrets | Container App secret (`ANTHROPIC_API_KEY`) — see "Key Vault" note below |
| Observability | Log Analytics workspace + Application Insights |

Files involved: [`azure.yaml`](azure.yaml), [`Dockerfile`](Dockerfile),
[`.dockerignore`](.dockerignore), and [`infra/`](infra/) (Bicep).

## One-time setup

```powershell
azd auth login                      # browser sign-in to Azure
azd env new synthdata               # create an environment
azd env set ANTHROPIC_API_KEY "sk-ant-..."   # optional; omit to run in DEMO_MOCK mode
```

## Deploy

```powershell
azd up                              # provisions infra, builds image in ACR, deploys
```

`azd up` prints the app URL (the `WEB_URI` output). Subsequent code changes redeploy with:

```powershell
azd deploy                          # rebuild + roll out a new revision
azd down                            # tear everything down
```

## Continuous deployment

[`.github/workflows/azure-dev.yml`](.github/workflows/azure-dev.yml) deploys on every push
to `main` via OIDC federated credentials. Configure it once with:

```powershell
azd pipeline config
```

That creates the Azure app registration, sets the federated trust, and populates the
`AZURE_*` repo variables the workflow reads. Add `ANTHROPIC_API_KEY` as a repo **secret**.

## Notes / adaptations from the AIDA reference

- **Storage is ephemeral.** AIDA mounts a volume for its files; this app writes DuckDB
  databases under `/app/files/duckdb`, which the app regenerates on demand. Uploaded
  datasets do **not** survive a revision restart. To persist them, add an Azure Files
  share to `infra/resources.bicep` (managed-environment storage) and a `volumeMounts`
  entry on the container, mounting it at `/app/files/duckdb`.
- **Secrets via Container App, not Key Vault.** AIDA targets Key Vault; here the LLM key
  is stored as a Container App secret (encrypted at rest). To move it to Key Vault,
  add a vault to the Bicep, grant the identity `Key Vault Secrets User`, and change the
  secret to a `keyVaultUrl` + `identity` reference.
- **No Blob Storage.** AIDA's `AIDA_FILE_STORAGE_MODE=blob` has no equivalent in this
  app's code, so Blob Storage is intentionally omitted.
