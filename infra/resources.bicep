@description('Azure region for the resources.')
param location string

@description('Unique suffix for globally-unique resource names.')
param resourceToken string

@description('Tags applied to every resource.')
param tags object

@secure()
@description('LLM API key (Anthropic). Optional.')
param anthropicApiKey string = ''

// Linux App Service plan. B1 (1.75 GB RAM) is a safe floor for pandas/data generation.
resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: 'plan-${resourceToken}'
  location: location
  tags: tags
  sku: {
    name: 'B1'
  }
  kind: 'linux'
  properties: {
    reserved: true
  }
}

// FastAPI web app. The 'azd-service-name' tag MUST match the service key ('web') in azure.yaml.
resource web 'Microsoft.Web/sites@2023-12-01' = {
  name: 'app-${resourceToken}'
  location: location
  tags: union(tags, { 'azd-service-name': 'web' })
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.12'
      // Oryx builds from requirements.txt; this command serves the FastAPI app.
      appCommandLine: 'python -m uvicorn demo_app:app --host 0.0.0.0 --port 8000'
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      appSettings: [
        {
          name: 'SCM_DO_BUILD_DURING_DEPLOYMENT'
          value: 'true'
        }
        {
          name: 'WEBSITES_PORT'
          value: '8000'
        }
        {
          name: 'ANTHROPIC_API_KEY'
          value: anthropicApiKey
        }
        // Set to '1' to run without any LLM key (returns mock summaries).
        {
          name: 'DEMO_MOCK'
          value: empty(anthropicApiKey) ? '1' : '0'
        }
      ]
    }
  }
}

output WEB_URI string = 'https://${web.properties.defaultHostName}'
