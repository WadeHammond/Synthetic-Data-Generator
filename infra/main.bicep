targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('Name of the azd environment — used to name the resource group and tag resources.')
param environmentName string

@minLength(1)
@description('Primary Azure region for all resources (e.g. eastus).')
param location string

@secure()
@description('LLM API key (Anthropic). Leave empty to run in DEMO_MOCK mode without an LLM.')
param anthropicApiKey string = ''

var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var tags = { 'azd-env-name': environmentName }

resource rg 'Microsoft.Resources/resourceGroups@2022-09-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module resources 'resources.bicep' = {
  name: 'resources'
  scope: rg
  params: {
    location: location
    resourceToken: resourceToken
    tags: tags
    anthropicApiKey: anthropicApiKey
  }
}

output AZURE_LOCATION string = location
output AZURE_RESOURCE_GROUP string = rg.name
// azd reads this to know which registry to push the built image to.
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = resources.outputs.AZURE_CONTAINER_REGISTRY_ENDPOINT
output WEB_URI string = resources.outputs.WEB_URI
