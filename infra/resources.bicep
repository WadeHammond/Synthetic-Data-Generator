@description('Azure region for the resources.')
param location string

@description('Unique suffix for globally-unique resource names.')
param resourceToken string

@description('Tags applied to every resource.')
param tags object

@secure()
@description('LLM API key (Anthropic). Empty => the app runs in DEMO_MOCK mode.')
param anthropicApiKey string = ''

var hasKey = !empty(anthropicApiKey)
// Public placeholder image used only for the initial provision. azd builds the real
// image from the Dockerfile, pushes it to the registry below, and updates this app.
var placeholderImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

// ── Observability: Log Analytics + Application Insights ───────────────────────
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${resourceToken}'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${resourceToken}'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
  }
}

// ── Azure Container Registry ──────────────────────────────────────────────────
// Admin user enabled so the container app authenticates with username/password.
// This deliberately avoids a managed identity + AcrPull role assignment, which needs
// Microsoft.Authorization/roleAssignments/write — a permission restricted corporate
// subscriptions often withhold.
resource registry 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: 'acr${resourceToken}'
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: true
  }
}

// ── Container Apps managed environment (wired to Log Analytics) ───────────────
resource caeEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-${resourceToken}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

// ── The web app ───────────────────────────────────────────────────────────────
// The 'azd-service-name' tag MUST match the service key ('web') in azure.yaml so
// azd knows which container app to deploy the built image to.
// minReplicas == maxReplicas == 1: DuckDB is single-writer and the project files
// live on the (ephemeral) container filesystem, so we pin to one instance.
resource web 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-web-${resourceToken}'
  location: location
  tags: union(tags, { 'azd-service-name': 'web' })
  properties: {
    managedEnvironmentId: caeEnv.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
      }
      registries: [
        {
          server: registry.properties.loginServer
          username: registry.listCredentials().username
          passwordSecretRef: 'acr-password'
        }
      ]
      secrets: concat([
        {
          name: 'acr-password'
          value: registry.listCredentials().passwords[0].value
        }
      ], hasKey ? [
        {
          name: 'anthropic-api-key'
          value: anthropicApiKey
        }
      ] : [])
    }
    template: {
      containers: [
        {
          name: 'web'
          image: placeholderImage
          resources: {
            cpu: json('1.0')
            memory: '2.0Gi'
          }
          env: concat([
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              value: appInsights.properties.ConnectionString
            }
            {
              name: 'DEMO_MOCK'
              value: hasKey ? '0' : '1'
            }
          ], hasKey ? [
            {
              name: 'ANTHROPIC_API_KEY'
              secretRef: 'anthropic-api-key'
            }
          ] : [])
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
}

output AZURE_CONTAINER_REGISTRY_ENDPOINT string = registry.properties.loginServer
output WEB_URI string = 'https://${web.properties.configuration.ingress.fqdn}'
