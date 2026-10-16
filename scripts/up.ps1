# Windows (PowerShell) equivalent of `make up`.  Usage:  .\scripts\up.ps1 -LlmApiKey <key> [-LlmBaseUrl ... -LlmModel ...]
param(
  [string]$LlmApiKey = $env:LLM_API_KEY,
  [string]$LlmBaseUrl = "https://api.groq.com/openai/v1",
  [string]$LlmModel = "llama-3.3-70b-versatile"
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$svcs = "gateway", "dashboard", "woo-mcp", "demo-mcp"

if (-not (k3d cluster list 2>$null | Select-String "^platform ")) {
  k3d cluster create platform -p "8080:80@loadbalancer" --wait
}
foreach ($s in $svcs) { docker build -t "platform/${s}:dev" "services/$s"; if ($LASTEXITCODE -ne 0) { throw "build failed: $s" } }
k3d image import ($svcs | ForEach-Object { "platform/${_}:dev" }) -c platform

$setKey = @(); if ($LlmApiKey) { $setKey = @("--set", "secrets.llmApiKey=$LlmApiKey") }
helm upgrade --install platform charts/platform -n platform --create-namespace `
  -f charts/platform/values-local.yaml @setKey `
  --set gateway.llm.baseUrl=$LlmBaseUrl --set gateway.llm.model=$LlmModel --wait --timeout 20m
if ($LASTEXITCODE -ne 0) { throw "helm failed" }

function Secret($k) { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String((kubectl -n platform get secret platform-secrets -o "jsonpath={.data.$k}"))) }
"`nDashboard : http://admin.localtest.me:8080   user: admin@example.com   password: $(Secret 'dashboard-admin-password')"
"Storefront: http://shop.localtest.me:8080    WP admin: /wp-admin  user: admin  password: $(Secret 'wp-admin-password')"
