// Infrastructure for the Microsoft IQ service-credit demo.
// Deploys: Foundry resource + project, model deployment, Azure AI Search,
// the role assignments the demo needs, and (optionally) a storage account
// for a Blob knowledge source.
//
// NOT deployed here (data-plane / preview steps, see infra/README.md):
// - the Foundry IQ knowledge base and document upload (Foundry portal)
// - the project MCP connection (scripts/create_connection.py)
// - the agent version (scripts/create_agent.py)

targetScope = 'resourceGroup'

@description('Short lowercase base name used to derive resource names, e.g. "contosoiq".')
@minLength(3)
@maxLength(17)
param baseName string

param location string = resourceGroup().location

@description('Object ID of the presenter (az ad signed-in-user show --query id -o tsv). Empty skips presenter role assignments.')
param principalId string = ''

@allowed(['User', 'ServicePrincipal', 'Group'])
param principalType string = 'User'

param projectName string = '${baseName}-project'

param modelName string = 'gpt-4.1-mini'
param modelVersion string = '2025-04-14'

@description('Tokens-per-minute capacity (in thousands) for the model deployment.')
param modelCapacity int = 50

@description('Embedding model for the blob knowledge source ingestion pipeline.')
param embeddingModelName string = 'text-embedding-3-small'
param embeddingModelVersion string = '1'

@description('Also deploy a storage account + container for a Blob knowledge source. Not needed for the File Search path.')
param deployStorage bool = false

@description('Disable API-key auth on the Foundry resource. Left false so demo-day portal flows stay friction-free; set true to harden.')
param disableLocalAuth bool = false

var foundryName = '${baseName}-foundry'
var searchName = '${baseName}-search'
var storageName = 'st${take(uniqueString(resourceGroup().id, baseName), 15)}'

// Built-in role definition IDs (see README prerequisites; portal may show the
// renamed Foundry role names for the Azure AI roles).
var roleIds = {
  searchIndexDataReader: '1407120a-92aa-4202-b7e9-c0e197c71c8f'
  searchIndexDataContributor: '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
  searchServiceContributor: '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
  cognitiveServicesUser: 'a97b65f3-24c7-4388-baec-2e87135dc908'
  azureAIUser: '53ca6127-db72-4b80-b1b0-d745d6d5456d'
  azureAIProjectManager: 'eadc314b-1a2d-4efa-be10-5d325db5065e'
  storageBlobDataReader: '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
  storageBlobDataContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
}

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: foundryName
  location: location
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    allowProjectManagement: true
    customSubDomainName: foundryName
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: disableLocalAuth
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: foundry
  name: projectName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: 'Microsoft IQ service-credit demo'
    description: 'Foundry IQ grounded agent with an approval-gated action.'
  }
}

resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundry
  name: modelName
  // Project and model creation both update the account; serialize them to
  // avoid Azure returning RequestConflict during an initial deployment.
  dependsOn: [project]
  sku: {
    name: 'GlobalStandard'
    capacity: modelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: modelName
      version: modelVersion
    }
  }
}

// Model deployments to one account must be created sequentially.
resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundry
  name: embeddingModelName
  dependsOn: [modelDeployment]
  sku: {
    name: 'GlobalStandard'
    capacity: 50
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: embeddingModelName
      version: embeddingModelVersion
    }
  }
}

resource search 'Microsoft.Search/searchServices@2025-05-01' = {
  name: searchName
  location: location
  sku: {
    name: 'basic'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    publicNetworkAccess: 'enabled'
    authOptions: {
      aadOrApiKey: {
        aadAuthFailureMode: 'http401WithBearerChallenge'
      }
    }
    // 'standard' avoids the free plan's monthly semantic-query cap cutting the
    // demo off mid-rehearsal; knowledge bases rely on semantic ranking.
    semanticSearch: 'standard'
  }
}

// Project managed identity reads the search index through the MCP knowledge base.
resource projectSearchReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(search.id, project.id, roleIds.searchIndexDataReader)
  scope: search
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.searchIndexDataReader)
    principalId: project.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Search managed identity calls the Foundry-hosted model for knowledge-base
// planning/synthesis.
resource searchFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, search.id, roleIds.cognitiveServicesUser)
  scope: foundry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.cognitiveServicesUser)
    principalId: search.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Presenter roles: create/test agents, manage the project connection, and
// create the knowledge base + indexes on the search service.
resource presenterAIUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(foundry.id, principalId, roleIds.azureAIUser)
  scope: foundry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.azureAIUser)
    principalId: principalId
    principalType: principalType
  }
}

resource presenterProjectManager 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(foundry.id, principalId, roleIds.azureAIProjectManager)
  scope: foundry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.azureAIProjectManager)
    principalId: principalId
    principalType: principalType
  }
}

resource presenterSearchContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(search.id, principalId, roleIds.searchServiceContributor)
  scope: search
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.searchServiceContributor)
    principalId: principalId
    principalType: principalType
  }
}

resource presenterSearchDataContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(search.id, principalId, roleIds.searchIndexDataContributor)
  scope: search
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.searchIndexDataContributor)
    principalId: principalId
    principalType: principalType
  }
}

// Optional Blob knowledge-source path.
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = if (deployStorage) {
  name: storageName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = if (deployStorage) {
  parent: storage
  name: 'default'
}

resource dataContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = if (deployStorage) {
  parent: blobService
  name: 'demo-data'
}

// Presenter uploads the demo documents to the container.
resource presenterStorageContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployStorage && !empty(principalId)) {
  name: guid(storage.id, principalId, roleIds.storageBlobDataContributor)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.storageBlobDataContributor)
    principalId: principalId
    principalType: principalType
  }
}

resource searchStorageReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployStorage) {
  name: guid(storage.id, search.id, roleIds.storageBlobDataReader)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.storageBlobDataReader)
    principalId: search.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

output foundryProjectEndpoint string = 'https://${foundryName}.services.ai.azure.com/api/projects/${projectName}'
output foundryProjectResourceId string = project.id
output modelDeploymentName string = modelDeployment.name
output embeddingDeploymentName string = embeddingDeployment.name
output searchEndpoint string = 'https://${searchName}.search.windows.net'
output searchServiceName string = search.name
output storageAccountName string = deployStorage ? storage.name : ''
