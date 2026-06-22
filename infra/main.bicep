targetScope = 'resourceGroup'

@minLength(1)
@maxLength(64)
@description('Name of the azd environment — used to tag resources.')
param environmentName string

@minLength(1)
@description('Primary Azure region for the resources. Defaults to the resource group location.')
param location string = resourceGroup().location

@secure()
@description('LLM API key (Anthropic). Leave empty to run in DEMO_MOCK mode without an LLM.')
param anthropicApiKey string = ''

var resourceToken = toLower(uniqueString(resourceGroup().id, environmentName))
var tags = { 'azd-env-name': environmentName }

// Deploys into the EXISTING resource group named by AZURE_RESOURCE_GROUP — this
// template does not create one (creating a resource group needs subscription-level
// permission this account doesn't have).
module resources 'resources.bicep' = {
  name: 'resources'
  params: {
    location: location
    resourceToken: resourceToken
    tags: tags
    anthropicApiKey: anthropicApiKey
  }
}

output AZURE_LOCATION string = location
output AZURE_RESOURCE_GROUP string = resourceGroup().name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = resources.outputs.AZURE_CONTAINER_REGISTRY_ENDPOINT
output WEB_URI string = resources.outputs.WEB_URI
