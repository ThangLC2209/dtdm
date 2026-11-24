# Triển khai Chứng từ số lên Azure Container Apps.
# Chạy trong PowerShell sau khi đăng nhập: az login
param(
  [Parameter(Mandatory=$true)][string]$SubscriptionId,
  [Parameter(Mandatory=$true)][string]$ResourceGroup,
  [string]$Location = "southeastasia",
  [string]$Environment = "chungtu-env",
  [string]$AppName = "chungtu-web",
  [string]$Image = ""
)
$ErrorActionPreference = "Stop"
az account set --subscription $SubscriptionId
az group create --name $ResourceGroup --location $Location | Out-Null
az containerapp env create --name $Environment --resource-group $ResourceGroup --location $Location | Out-Null
if (-not $Image) { $Image = "$AppName.azurecr.io/chungtu:latest" }
Write-Host "Đã chuẩn bị Resource Group và Container Apps Environment."
Write-Host "Bước tiếp theo cần chạy sau khi tạo Azure SQL, Storage, Service Bus và Entra App Registration:"
Write-Host "az containerapp create --name $AppName --resource-group $ResourceGroup --environment $Environment --image $Image --target-port 8080 --ingress external"
Write-Host "Đặt BACKEND=azure, AUTH_MODE=entra và các biến AZURE_* bằng Secret/Managed Identity; không ghi secret vào script."
