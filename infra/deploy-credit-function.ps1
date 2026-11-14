<# Create and deploy a NEW Flex Consumption Function App after credit-services.bicep.
   Run from any directory in PowerShell 7 with Azure CLI signed in. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$ResourceGroup,
    [Parameter(Mandatory)] [string]$Location,
    [Parameter(Mandatory)] [string]$FunctionAppName,
    [Parameter(Mandatory)] [string]$StorageAccountName,
    [Parameter(Mandatory)] [string]$IdentityName,
    [Parameter(Mandatory)] [string]$ServiceBusName,
    [Parameter(Mandatory)] [string]$AppInsightsName,
    [Parameter(Mandatory)] [string]$SqlServer,
    [string]$SqlDatabase = 'ContosoServiceDemo',
    [string]$QueueName = 'approved-credit-requests'
)
$ErrorActionPreference = 'Stop'
function Assert-AzSuccess([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "Azure CLI failed: $Step (exit $LASTEXITCODE)" }
}

$identityJson = az identity show -g $ResourceGroup -n $IdentityName -o json
Assert-AzSuccess 'read managed identity'
$identity = $identityJson | ConvertFrom-Json
$existing = az functionapp list -g $ResourceGroup --query "[?name=='$FunctionAppName'].name" -o tsv
Assert-AzSuccess 'check existing Function Apps'
if ($existing) { throw 'Function App already exists. Review it and deploy updates explicitly; this script only creates a new app.' }

az functionapp create -g $ResourceGroup -n $FunctionAppName -s $StorageAccountName `
    --flexconsumption-location $Location --runtime python --runtime-version 3.12 `
    --functions-version 4 --app-insights $AppInsightsName -o none
Assert-AzSuccess 'create Function App'
az functionapp identity assign -g $ResourceGroup -n $FunctionAppName --identities $identity.id -o none
Assert-AzSuccess 'assign managed identity'

az functionapp config appsettings set -g $ResourceGroup -n $FunctionAppName --settings `
    "AZURE_CLIENT_ID=$($identity.clientId)" `
    "SQL_SERVER=$SqlServer" "SQL_DATABASE=$SqlDatabase" `
    "SERVICEBUS_FULLY_QUALIFIED_NAMESPACE=$ServiceBusName.servicebus.windows.net" `
    "SERVICEBUS_QUEUE_NAME=$QueueName" `
    "ServiceBus__fullyQualifiedNamespace=$ServiceBusName.servicebus.windows.net" `
    'ServiceBus__credential=managedidentity' "ServiceBus__clientId=$($identity.clientId)" -o none
Assert-AzSuccess 'configure application settings'

$repoRoot = Split-Path $PSScriptRoot -Parent
$package = Join-Path ([System.IO.Path]::GetTempPath()) ("contoso-credit-{0}.zip" -f [guid]::NewGuid().ToString('N'))
try {
    Compress-Archive -LiteralPath (Join-Path $repoRoot 'credit-processor/function_app.py'), `
        (Join-Path $repoRoot 'credit-processor/host.json'), `
        (Join-Path $repoRoot 'credit-processor/requirements.txt') -DestinationPath $package
    az functionapp deployment source config-zip -g $ResourceGroup -n $FunctionAppName `
        --src $package --build-remote true -o none
    Assert-AzSuccess 'deploy Function source'
} finally {
    if (Test-Path -LiteralPath $package) { Remove-Item -LiteralPath $package -Force }
}
Write-Host 'Function created. Check SQL grants, identity role propagation, functions and Application Insights as described in SETUP.md.'
