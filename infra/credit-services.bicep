// Optional integration resources. Deploy to a dedicated demo resource group.
param location string = resourceGroup().location
@description('Globally unique, 6-50 characters')
param serviceBusName string
@description('Globally unique, 3-24 lowercase letters and digits')
param functionStorageName string
param identityName string = 'iq-demo-web-identity'
param queueName string = 'approved-credit-requests'
param workspaceName string = 'contoso-credit-logs'
param appInsightsName string = 'contoso-credit-insights'

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: identityName
  location: location
}
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: functionStorageName
  location: location
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: { minimumTlsVersion: 'TLS1_2', allowBlobPublicAccess: false }
}
resource bus 'Microsoft.ServiceBus/namespaces@2024-01-01' = {
  name: serviceBusName
  location: location
  sku: { name: 'Standard', tier: 'Standard' }
  properties: { minimumTlsVersion: '1.2' }
}
resource queue 'Microsoft.ServiceBus/namespaces/queues@2024-01-01' = {
  parent: bus
  name: queueName
  properties: {
    maxDeliveryCount: 10
    requiresDuplicateDetection: false
  }
}
resource sender 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(queue.id, identity.id, '69a216fc-b8fb-44d8-bc22-1f3c2cd27a39')
  scope: queue
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '69a216fc-b8fb-44d8-bc22-1f3c2cd27a39')
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}
resource receiver 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(queue.id, identity.id, '4f6d3b9b-027b-4f4c-9142-0e5a2a2247e0')
  scope: queue
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4f6d3b9b-027b-4f4c-9142-0e5a2a2247e0')
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}
resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: workspaceName
  location: location
  properties: { sku: { name: 'PerGB2018' }, retentionInDays: 30 }
}
resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: { Application_Type: 'web', WorkspaceResourceId: workspace.id }
}

output identityId string = identity.id
output identityClientId string = identity.properties.clientId
output identityPrincipalId string = identity.properties.principalId
output serviceBusHost string = '${bus.name}.servicebus.windows.net'
output queueName string = queue.name
output storageName string = storage.name
output appInsightsName string = insights.name
