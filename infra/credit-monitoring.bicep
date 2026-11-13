@description('Existing Application Insights component name')
param appInsightsName string
@description('Existing Service Bus namespace name')
param serviceBusNamespaceName string
@description('Queue to monitor')
param queueName string
@description('Existing Azure Monitor action group resource ID')
param actionGroupId string
param location string = resourceGroup().location

resource insights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: appInsightsName
}
resource bus 'Microsoft.ServiceBus/namespaces@2022-10-01-preview' existing = {
  name: serviceBusNamespaceName
}

resource deadLetters 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'contoso-credit-dead-letters'
  location: 'global'
  properties: {
    description: 'At least one service credit message needs dead-letter investigation.'
    severity: 2
    enabled: true
    scopes: [bus.id]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT5M'
    autoMitigate: true
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [{
        name: 'deadLetterCount'
        criterionType: 'StaticThresholdCriterion'
        metricNamespace: 'Microsoft.ServiceBus/namespaces'
        metricName: 'DeadletteredMessages'
        dimensions: [{ name: 'EntityName', operator: 'Include', values: [queueName] }]
        operator: 'GreaterThan'
        threshold: 0
        timeAggregation: 'Maximum'
      }]
    }
    actions: [{ actionGroupId: actionGroupId }]
  }
}

var logAlerts = [
  {
    name: 'contoso-credit-stuck-requests'
    description: 'The SQL monitor found a request stuck for over ten minutes.'
    query: 'traces | where message startswith "credit_monitor_stuck "'
    aggregation: 'Count'
    operator: 'GreaterThan'
    threshold: 0
    window: 'PT10M'
  }
  {
    name: 'contoso-credit-monitor-heartbeat-missing'
    description: 'No successful SQL monitor heartbeat arrived in 30 minutes.'
    query: 'traces | where message startswith "credit_monitor_heartbeat " | summarize Heartbeats = count()'
    aggregation: 'Total'
    operator: 'LessThan'
    threshold: 1
    window: 'PT30M'
  }
]

resource logs 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = [for rule in logAlerts: {
  name: rule.name
  location: location
  kind: 'LogAlert'
  properties: {
    displayName: rule.name
    description: rule.description
    enabled: true
    severity: 2
    evaluationFrequency: 'PT5M'
    windowSize: rule.window
    scopes: [insights.id]
    criteria: {
      allOf: [union({
        query: rule.query
        timeAggregation: rule.aggregation
        operator: rule.operator
        threshold: rule.threshold
        failingPeriods: { numberOfEvaluationPeriods: 1, minFailingPeriodsToAlert: 1 }
      }, rule.name == 'contoso-credit-monitor-heartbeat-missing' ? { metricMeasureColumn: 'Heartbeats' } : {})]
    }
    actions: { actionGroups: [actionGroupId] }
    autoMitigate: true
    skipQueryValidation: false
  }
}]
