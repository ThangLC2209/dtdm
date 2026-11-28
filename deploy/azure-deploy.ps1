# Triển khai Chứng từ số lên Azure (Container Apps + Azure SQL + Blob + Service Bus + Key Vault).
#
# Yêu cầu trên máy chạy script:
#   - Azure CLI (az) đã đăng nhập:  az login
#   - Tài khoản có quyền Owner (hoặc Contributor + User Access Administrator) trên subscription
#   - Tùy chọn: go-sqlcmd (winget install sqlcmd) để tự cấp quyền SQL cho managed identity
#
# Ví dụ:
#   .\deploy\azure-deploy.ps1 -SubscriptionId <id> -ResourceGroup rg-chungtu -AdminEmails "admin@congty.vn"
#
# Chạy lại script an toàn: tài nguyên đã có sẽ được giữ, Container App được cập nhật image mới.
param(
  [Parameter(Mandatory = $true)][string]$SubscriptionId,
  [Parameter(Mandatory = $true)][string]$ResourceGroup,
  [Parameter(Mandatory = $true)][string]$AdminEmails,
  [string]$Location = "southeastasia",
  # Tiền tố tên tài nguyên: chữ thường và số, 3-12 ký tự; mặc định sinh từ subscription + RG
  [string]$Prefix = "",
  [ValidateSet("password", "entra")][string]$AuthMode = "password",
  # Chỉ cần khi AuthMode = entra (App registration single-tenant)
  [string]$EntraClientId = "",
  [SecureString]$EntraClientSecret,
  [string]$ImageTag = (Get-Date -Format "yyyyMMddHHmmss")
)
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

function Invoke-Az {
  # az là lệnh ngoài: PowerShell không tự dừng khi lỗi nên phải kiểm tra mã thoát
  $output = & az @args
  if ($LASTEXITCODE -ne 0) { throw "Lệnh thất bại: az $($args -join ' ')" }
  return $output
}

function Test-Az {
  & az @args 2>$null | Out-Null
  return $LASTEXITCODE -eq 0
}

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }

if ($AuthMode -eq "entra" -and (-not $EntraClientId -or -not $EntraClientSecret)) {
  throw "AuthMode=entra cần -EntraClientId và -EntraClientSecret."
}

# ------------------------------------------------------------------ chuẩn bị
Step "Chọn subscription và cài extension"
Invoke-Az account set --subscription $SubscriptionId | Out-Null
Invoke-Az extension add --name containerapp --upgrade --only-show-errors | Out-Null
foreach ($ns in "Microsoft.App", "Microsoft.OperationalInsights", "Microsoft.ContainerRegistry",
                "Microsoft.Sql", "Microsoft.Storage", "Microsoft.ServiceBus", "Microsoft.KeyVault",
                "Microsoft.ManagedIdentity") {
  Invoke-Az provider register --namespace $ns --wait | Out-Null
}
$TenantId = Invoke-Az account show --query tenantId -o tsv
$Me = Invoke-Az ad signed-in-user show --query "{id:id, upn:userPrincipalName}" -o json | ConvertFrom-Json

if (-not $Prefix) {
  $hash = [System.BitConverter]::ToString(
    [System.Security.Cryptography.SHA256]::Create().ComputeHash(
      [System.Text.Encoding]::UTF8.GetBytes("$SubscriptionId/$ResourceGroup"))).Replace("-", "").ToLower()
  $Prefix = "chungtu" + $hash.Substring(0, 5)
}
$Names = @{
  Acr        = "${Prefix}acr"
  Identity   = "$Prefix-id"
  Storage    = "${Prefix}st"
  ServiceBus = "$Prefix-sb"
  Queue      = "chungtu-events"
  SqlServer  = "$Prefix-sql"
  SqlDb      = "chungtu"
  KeyVault   = "$Prefix-kv"
  Env        = "$Prefix-env"
  Web        = "$Prefix-web"
  Worker     = "$Prefix-worker"
}
Write-Host "Tiền tố tài nguyên: $Prefix"

Step "Resource Group"
Invoke-Az group create --name $ResourceGroup --location $Location -o none

# ------------------------------------------------------------------ danh tính
Step "Managed identity dùng chung cho web và worker"
Invoke-Az identity create --name $Names.Identity --resource-group $ResourceGroup --location $Location -o none
$Identity = Invoke-Az identity show --name $Names.Identity --resource-group $ResourceGroup `
  --query "{id:id, clientId:clientId, principalId:principalId}" -o json | ConvertFrom-Json

function Grant-Role($role, $scope, $principalId, $type = "ServicePrincipal") {
  $exists = Invoke-Az role assignment list --assignee $principalId --role $role --scope $scope --query "length(@)" -o tsv
  if ($exists -eq "0") {
    Invoke-Az role assignment create --assignee-object-id $principalId --assignee-principal-type $type `
      --role $role --scope $scope -o none
  }
}

# ------------------------------------------------------------------ registry + image
Step "Azure Container Registry và build image (build trên Azure, không cần Docker máy local)"
if (-not (Test-Az acr show --name $Names.Acr --resource-group $ResourceGroup)) {
  Invoke-Az acr create --name $Names.Acr --resource-group $ResourceGroup --location $Location --sku Basic `
    --admin-enabled false -o none
}
$AcrId = Invoke-Az acr show --name $Names.Acr --query id -o tsv
$AcrServer = Invoke-Az acr show --name $Names.Acr --query loginServer -o tsv
Grant-Role "AcrPull" $AcrId $Identity.principalId
$Image = "$AcrServer/chungtu:$ImageTag"
Invoke-Az acr build --registry $Names.Acr --image "chungtu:$ImageTag" --file "$RepoRoot/Dockerfile" $RepoRoot -o none

# ------------------------------------------------------------------ storage
Step "Storage Account và container riêng tư"
if (-not (Test-Az storage account show --name $Names.Storage --resource-group $ResourceGroup)) {
  Invoke-Az storage account create --name $Names.Storage --resource-group $ResourceGroup --location $Location `
    --sku Standard_ZRS --kind StorageV2 --https-only true --min-tls-version TLS1_2 `
    --allow-blob-public-access false --allow-shared-key-access false -o none
}
$StorageId = Invoke-Az storage account show --name $Names.Storage --resource-group $ResourceGroup --query id -o tsv
Invoke-Az storage account blob-service-properties update --account-name $Names.Storage --resource-group $ResourceGroup `
  --enable-delete-retention true --delete-retention-days 30 --enable-versioning true -o none
Grant-Role "Storage Blob Data Contributor" $StorageId $Identity.principalId
# Người chạy script cần quyền dữ liệu để tạo container (shared key đã tắt)
Grant-Role "Storage Blob Data Contributor" $StorageId $Me.id "User"
Start-Sleep -Seconds 30
Invoke-Az storage container create --name documents --account-name $Names.Storage --auth-mode login `
  --public-access off -o none

# ------------------------------------------------------------------ service bus
Step "Service Bus namespace và queue"
if (-not (Test-Az servicebus namespace show --name $Names.ServiceBus --resource-group $ResourceGroup)) {
  Invoke-Az servicebus namespace create --name $Names.ServiceBus --resource-group $ResourceGroup `
    --location $Location --sku Basic --disable-local-auth true -o none
}
if (-not (Test-Az servicebus queue show --name $Names.Queue --namespace-name $Names.ServiceBus --resource-group $ResourceGroup)) {
  Invoke-Az servicebus queue create --name $Names.Queue --namespace-name $Names.ServiceBus `
    --resource-group $ResourceGroup --max-delivery-count 10 -o none
}
$SbId = Invoke-Az servicebus namespace show --name $Names.ServiceBus --resource-group $ResourceGroup --query id -o tsv
Grant-Role "Azure Service Bus Data Sender" $SbId $Identity.principalId
Grant-Role "Azure Service Bus Data Receiver" $SbId $Identity.principalId

# ------------------------------------------------------------------ azure sql
Step "Azure SQL (chỉ xác thực Microsoft Entra, không mật khẩu SQL)"
if (-not (Test-Az sql server show --name $Names.SqlServer --resource-group $ResourceGroup)) {
  Invoke-Az sql server create --name $Names.SqlServer --resource-group $ResourceGroup --location $Location `
    --enable-ad-only-auth --external-admin-principal-type User `
    --external-admin-name $Me.upn --external-admin-sid $Me.id --minimal-tls-version 1.2 -o none
}
# Cho phép dịch vụ Azure (Container Apps) kết nối; truy cập vẫn cần token Entra hợp lệ
Invoke-Az sql server firewall-rule create --server $Names.SqlServer --resource-group $ResourceGroup `
  --name AllowAzureServices --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0 -o none
if (-not (Test-Az sql db show --name $Names.SqlDb --server $Names.SqlServer --resource-group $ResourceGroup)) {
  Invoke-Az sql db create --name $Names.SqlDb --server $Names.SqlServer --resource-group $ResourceGroup `
    --edition GeneralPurpose --compute-model Serverless --family Gen5 --capacity 1 `
    --auto-pause-delay 60 --backup-storage-redundancy Local -o none
}
$SqlHost = "$($Names.SqlServer).database.windows.net"
$Odbc = "Driver={ODBC Driver 18 for SQL Server};Server=tcp:$SqlHost,1433;Database=$($Names.SqlDb);" +
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;" +
        "Authentication=ActiveDirectoryMsi;UID=$($Identity.clientId)"
$SqlUrl = "mssql+pyodbc:///?odbc_connect=" + [uri]::EscapeDataString($Odbc)

$GrantSql = @"
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'$($Names.Identity)')
  CREATE USER [$($Names.Identity)] FROM EXTERNAL PROVIDER;
ALTER ROLE db_datareader ADD MEMBER [$($Names.Identity)];
ALTER ROLE db_datawriter ADD MEMBER [$($Names.Identity)];
ALTER ROLE db_ddladmin ADD MEMBER [$($Names.Identity)];
"@
$SqlGranted = $false
if (Get-Command sqlcmd -ErrorAction SilentlyContinue) {
  $myIp = (Invoke-RestMethod -Uri "https://api.ipify.org")
  Invoke-Az sql server firewall-rule create --server $Names.SqlServer --resource-group $ResourceGroup `
    --name DeployClient --start-ip-address $myIp --end-ip-address $myIp -o none
  & sqlcmd -S $SqlHost -d $Names.SqlDb --authentication-method ActiveDirectoryDefault -Q $GrantSql
  if ($LASTEXITCODE -eq 0) { $SqlGranted = $true }
  Invoke-Az sql server firewall-rule delete --server $Names.SqlServer --resource-group $ResourceGroup `
    --name DeployClient -o none
}

# ------------------------------------------------------------------ key vault
Step "Key Vault và secret"
if (-not (Test-Az keyvault show --name $Names.KeyVault --resource-group $ResourceGroup)) {
  Invoke-Az keyvault create --name $Names.KeyVault --resource-group $ResourceGroup --location $Location `
    --enable-rbac-authorization true --retention-days 30 -o none
}
$KvId = Invoke-Az keyvault show --name $Names.KeyVault --query id -o tsv
$KvUri = Invoke-Az keyvault show --name $Names.KeyVault --query properties.vaultUri -o tsv
Grant-Role "Key Vault Secrets Officer" $KvId $Me.id "User"
Grant-Role "Key Vault Secrets User" $KvId $Identity.principalId
Start-Sleep -Seconds 30  # chờ phân quyền có hiệu lực

if (-not (Test-Az keyvault secret show --vault-name $Names.KeyVault --name secret-key)) {
  $bytes = New-Object byte[] 48
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $secretKey = [Convert]::ToBase64String($bytes)
  Invoke-Az keyvault secret set --vault-name $Names.KeyVault --name secret-key --value $secretKey -o none
}
$Secrets = @("secret-key=keyvaultref:${KvUri}secrets/secret-key,identityref:$($Identity.id)")
if ($AuthMode -eq "entra") {
  $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($EntraClientSecret))
  Invoke-Az keyvault secret set --vault-name $Names.KeyVault --name entra-client-secret --value $plain -o none
  $Secrets += "entra-client-secret=keyvaultref:${KvUri}secrets/entra-client-secret,identityref:$($Identity.id)"
}

# ------------------------------------------------------------------ container apps
Step "Container Apps Environment (kèm Log Analytics)"
if (-not (Test-Az containerapp env show --name $Names.Env --resource-group $ResourceGroup)) {
  Invoke-Az containerapp env create --name $Names.Env --resource-group $ResourceGroup --location $Location -o none
}

$EnvVars = @(
  "BACKEND=azure",
  "AUTH_MODE=$AuthMode",
  "ADMIN_EMAILS=$AdminEmails",
  "SECRET_KEY=secretref:secret-key",
  "AZURE_MANAGED_IDENTITY_CLIENT_ID=$($Identity.clientId)",
  "AZURE_SQL_URL=$SqlUrl",
  "AZURE_STORAGE_ACCOUNT_URL=https://$($Names.Storage).blob.core.windows.net",
  "AZURE_STORAGE_CONTAINER=documents",
  "AZURE_SERVICEBUS_NAMESPACE=$($Names.ServiceBus)",
  "AZURE_SERVICEBUS_QUEUE=$($Names.Queue)"
)
if ($AuthMode -eq "entra") {
  $EnvVars += "AZURE_TENANT_ID=$TenantId", "AZURE_CLIENT_ID=$EntraClientId",
              "AZURE_CLIENT_SECRET=secretref:entra-client-secret"
}

function Deploy-App($name, [string[]]$extraCreateArgs, [string[]]$command) {
  $vars = $EnvVars
  if ($name -eq $Names.Web -and $AuthMode -eq "entra") {
    $fqdnNow = & az containerapp show --name $name --resource-group $ResourceGroup `
      --query properties.configuration.ingress.fqdn -o tsv 2>$null
    if ($fqdnNow) { $vars += "AZURE_REDIRECT_URI=https://$fqdnNow/auth/callback" }
  }
  if (Test-Az containerapp show --name $name --resource-group $ResourceGroup) {
    Invoke-Az containerapp secret set --name $name --resource-group $ResourceGroup --secrets @Secrets -o none
    $updateArgs = @("containerapp", "update", "--name", $name, "--resource-group", $ResourceGroup,
                    "--image", $Image, "--set-env-vars") + $vars + @("-o", "none")
    if ($command) { $updateArgs += @("--command") + $command }
    Invoke-Az @updateArgs
  } else {
    $createArgs = @("containerapp", "create", "--name", $name, "--resource-group", $ResourceGroup,
                    "--environment", $Names.Env, "--image", $Image,
                    "--user-assigned", $Identity.id, "--registry-server", $AcrServer,
                    "--registry-identity", $Identity.id, "--cpu", "0.5", "--memory", "1.0Gi",
                    "--secrets") + $Secrets + @("--env-vars") + $vars + $extraCreateArgs + @("-o", "none")
    if ($command) { $createArgs += @("--command") + $command }
    Invoke-Az @createArgs
  }
}

Step "Web app"
Deploy-App $Names.Web @("--ingress", "external", "--target-port", "8080", "--transport", "auto",
                        "--min-replicas", "1", "--max-replicas", "3") $null
$Fqdn = Invoke-Az containerapp show --name $Names.Web --resource-group $ResourceGroup `
  --query properties.configuration.ingress.fqdn -o tsv
if ($AuthMode -eq "entra") {
  # Lần đầu chưa biết FQDN: cập nhật redirect URI sau khi app đã có địa chỉ
  Invoke-Az containerapp update --name $Names.Web --resource-group $ResourceGroup `
    --set-env-vars "AZURE_REDIRECT_URI=https://$Fqdn/auth/callback" -o none
}

Step "Worker Service Bus (không mở ingress)"
Deploy-App $Names.Worker @("--min-replicas", "1", "--max-replicas", "1") @("python", "-m", "app.servicebus_worker")

# ------------------------------------------------------------------ kết quả
Write-Host "`nHoàn tất triển khai." -ForegroundColor Green
Write-Host "Địa chỉ ứng dụng: https://$Fqdn"
if (-not $SqlGranted) {
  Write-Host "`nBƯỚC BẮT BUỘC CÒN LẠI: cấp quyền Azure SQL cho managed identity." -ForegroundColor Yellow
  Write-Host "Azure Portal > SQL database '$($Names.SqlDb)' > Query editor (đăng nhập bằng $($Me.upn)), chạy:"
  Write-Host $GrantSql
  Write-Host "Sau đó khởi động lại: az containerapp revision restart (hoặc chạy lại script này)."
}
if ($AuthMode -eq "password") {
  Write-Host "`nVào https://$Fqdn/register và đăng ký bằng email quản trị ($AdminEmails) NGAY để nhận quyền quản trị."
} else {
  Write-Host "`nThêm Redirect URI vào App registration: https://$Fqdn/auth/callback"
}
