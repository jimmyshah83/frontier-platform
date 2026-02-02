# Step 2: Azure Infrastructure Setup

This document provides steps to set up the Azure resources needed for the Content Understanding MCP Server.

## Option A: Use Existing Azure AI Foundry Resource (Recommended)

If you already have an Azure AI Foundry project, Content Understanding is available via your Foundry endpoint.

### Prerequisites

1. Azure AI Foundry project created in [AI Foundry Portal](https://ai.azure.com)
2. Your Foundry endpoint (e.g., `https://your-resource.services.ai.azure.com/`)
3. GPT-4.1 or GPT-4.1-mini model deployed (required for Content Understanding)

### 1. Configure Content Understanding in Foundry

1. Go to [Content Understanding Settings](https://contentunderstanding.ai.azure.com/settings)
2. Click **"+ Add resource"**
3. Select your Foundry resource
4. Enable **"Enable autodeployment for required models"** - this deploys GPT-4.1, GPT-4.1-mini, and text-embedding-3-large

### 2. Verify Your RBAC Roles

```bash
# Find your Foundry AI Services account (look for your endpoint subdomain)
az cognitiveservices account list \
  --query "[?contains(properties.endpoint, 'services.ai.azure.com')].{name:name, rg:resourceGroup, endpoint:properties.endpoint}" \
  -o table

# Set these based on the output above
FOUNDRY_RESOURCE_GROUP="<resource-group-from-above>"
FOUNDRY_ACCOUNT_NAME="<account-name-from-above>"

FOUNDRY_ID=$(az cognitiveservices account show \
  --name $FOUNDRY_ACCOUNT_NAME \
  --resource-group $FOUNDRY_RESOURCE_GROUP \
  --query id -o tsv)

# Assign yourself Cognitive Services User role (if not already assigned)
CURRENT_USER_ID=$(az ad signed-in-user show --query id -o tsv)

az role assignment create \
  --role "Cognitive Services User" \
  --assignee $CURRENT_USER_ID \
  --scope $FOUNDRY_ID
```

### 3. Update Your .env File

```bash
# Your Foundry endpoint
AZURE_AI_SERVICES_ENDPOINT=https://your-resource.services.ai.azure.com/
```

### 4. Verify Content Understanding Access

```bash
# Test Content Understanding API
FOUNDRY_ENDPOINT="https://your-resource.services.ai.azure.com"

curl -X GET "$FOUNDRY_ENDPOINT/contentunderstanding/analyzers?api-version=2025-11-01" \
  -H "Authorization: Bearer $(az account get-access-token --resource https://cognitiveservices.azure.com --query accessToken -o tsv)"
```

You should see a list of available analyzers including `prebuilt-document`, `prebuilt-invoice`, etc.

---

## Option B: Create New Azure AI Services Resource

If you need a separate AI Services resource for Content Understanding.

### Prerequisites

1. Azure CLI installed (`brew install azure-cli` on macOS)
2. Logged in to Azure: `az login`
3. Azure Functions Core Tools: `brew install azure-functions-core-tools@4`

### 1. Set Variables

```bash
# Set your values
RESOURCE_GROUP="<RG Name>"
LOCATION="<Azure Region>"  # e.g., eastus, westus2
STORAGE_ACCOUNT="stloanproc$(openssl rand -hex 4)"
AI_SERVICES_NAME="ai-loanproc-$(openssl rand -hex 4)"
FUNCTION_APP_NAME="func-loanproc-$(openssl rand -hex 4)"

# Save for later use
echo "RESOURCE_GROUP=$RESOURCE_GROUP" >> .env.azure
echo "STORAGE_ACCOUNT=$STORAGE_ACCOUNT" >> .env.azure
echo "AI_SERVICES_NAME=$AI_SERVICES_NAME" >> .env.azure
echo "FUNCTION_APP_NAME=$FUNCTION_APP_NAME" >> .env.azure
```

### 2. Create Resource Group

```bash
az group create \
  --name $RESOURCE_GROUP \
  --location $LOCATION
```

### 3. Create Storage Account

```bash
az storage account create \
  --name $STORAGE_ACCOUNT \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION \
  --sku Standard_LRS \
  --kind StorageV2 \
  --allow-blob-public-access false

# Create container for loan documents
az storage container create \
  --name loan-documents \
  --account-name $STORAGE_ACCOUNT \
  --auth-mode login
```

### 4. Create Azure AI Services (Content Understanding)

```bash
# Create AI Services account (includes Content Understanding)
az cognitiveservices account create \
  --name $AI_SERVICES_NAME \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION \
  --kind AIServices \
  --sku S0 \
  --custom-domain $AI_SERVICES_NAME \
  --yes
```

### 5. Create Function App (Optional - for deployment)

```bash
# Create Function App (Linux, Python)
az functionapp create \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --storage-account $STORAGE_ACCOUNT \
  --consumption-plan-location $LOCATION \
  --runtime python \
  --runtime-version 3.11 \
  --functions-version 4 \
  --os-type Linux

# Enable system-assigned managed identity
az functionapp identity assign \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP
```

### 6. Assign RBAC Roles

```bash
# Get Function App's managed identity principal ID
FUNC_PRINCIPAL_ID=$(az functionapp identity show \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query principalId -o tsv)

# Get AI Services resource ID
AI_SERVICES_ID=$(az cognitiveservices account show \
  --name $AI_SERVICES_NAME \
  --resource-group $RESOURCE_GROUP \
  --query id -o tsv)

# Get Storage Account resource ID
STORAGE_ID=$(az storage account show \
  --name $STORAGE_ACCOUNT \
  --resource-group $RESOURCE_GROUP \
  --query id -o tsv)

# Assign Cognitive Services User role
az role assignment create \
  --role "Cognitive Services User" \
  --assignee $FUNC_PRINCIPAL_ID \
  --scope $AI_SERVICES_ID

# Assign Storage Blob Data Contributor role
az role assignment create \
  --role "Storage Blob Data Contributor" \
  --assignee $FUNC_PRINCIPAL_ID \
  --scope $STORAGE_ID

# Also assign roles to yourself for local development
CURRENT_USER_ID=$(az ad signed-in-user show --query id -o tsv)

az role assignment create \
  --role "Cognitive Services User" \
  --assignee $CURRENT_USER_ID \
  --scope $AI_SERVICES_ID

az role assignment create \
  --role "Storage Blob Data Contributor" \
  --assignee $CURRENT_USER_ID \
  --scope $STORAGE_ID
```

### 7. Update Local .env

```bash
# Get AI Services endpoint
AI_ENDPOINT=$(az cognitiveservices account show \
  --name $AI_SERVICES_NAME \
  --resource-group $RESOURCE_GROUP \
  --query properties.endpoint -o tsv)

# Update .env file
cat >> .env << EOF

# Azure Infrastructure (from Step 2)
AZURE_AI_SERVICES_ENDPOINT=$AI_ENDPOINT
AZURE_STORAGE_ACCOUNT_NAME=$STORAGE_ACCOUNT
AZURE_STORAGE_CONTAINER_NAME=loan-documents
EOF

echo "✅ .env updated with Azure resource endpoints"
```

### 8. Verify Setup

```bash
# Test AI Services connectivity
AI_ENDPOINT=$(az cognitiveservices account show \
  --name $AI_SERVICES_NAME \
  --resource-group $RESOURCE_GROUP \
  --query properties.endpoint -o tsv)

curl -X GET "$AI_ENDPOINT/contentunderstanding/analyzers?api-version=2025-11-01" \
  -H "Authorization: Bearer $(az account get-access-token --resource https://cognitiveservices.azure.com --query accessToken -o tsv)"
```

---

## Next Steps

After infrastructure is configured:

1. Run the local MCP server: `uv run python -m loan_processor.local_mcp_server`
2. Test with MCP Inspector: `npx @modelcontextprotocol/inspector http://127.0.0.1:8000/mcp`
3. Deploy to Azure Functions (optional): `func azure functionapp publish $FUNCTION_APP_NAME`

## Next Steps

After infrastructure is created:
1. Run the local MCP server: `uv run python -m loan_processor.mcp_server`
2. Test with MCP Inspector: `npx @modelcontextprotocol/inspector`
3. Deploy to Azure Functions: `func azure functionapp publish $FUNCTION_APP_NAME`
