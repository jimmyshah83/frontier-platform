# Credit Risk Assessment Data

This folder contains sample data for credit risk assessment that can be indexed in Azure AI Search and used with **Foundry IQ** to ground a Risk Assessment Agent.

## Files

| File | Description |
|------|-------------|
| `credit_risk_policies.json` | Credit risk policy rules for credit score, DTI, LTV, employment, and reserves |
| `credit_risk_scoring_model.json` | Comprehensive scoring model with weights, tiers, and compensating factors |
| `historical_cases.json` | 6 historical loan cases (approved, denied, escalated) with full context |
| `regulatory_guidelines.json` | Key regulatory requirements (QM, Fair Housing, TRID, HMDA, Fannie Mae) |
| `index_schema.json` | Azure AI Search index schema for creating the search index |

## Data Overview

### Credit Risk Policies
5 policies covering:
- **Credit Score Classification**: Score ranges and risk levels (750+: low, 580-650: high, <580: critical)
- **Debt-to-Income Ratio**: DTI thresholds (≤36%: low, 36-43%: medium, >50%: critical)
- **Loan-to-Value Ratio**: LTV guidelines with PMI requirements
- **Employment Stability**: Full-time, part-time, self-employed rules
- **Cash Reserves**: Months of reserves requirements

### Scoring Model
Weighted scoring model:
- Credit Score: 30% weight
- DTI Ratio: 25% weight
- LTV Ratio: 20% weight
- Employment Stability: 15% weight
- Cash Reserves: 10% weight

Plus compensating factors (+5 points for exceptional credit, reserves) and negative factors (-10 points for late payments).

### Historical Cases
6 cases representing different outcomes:
1. **Approved** - Strong applicant (score 87, low risk)
2. **Approved with Conditions** - Medium risk with PMI required
3. **Escalated then Approved** - Self-employed with strong compensating factors
4. **Denied** - Multiple critical risk factors
5. **Approved** - First-time buyer with gift funds
6. **Denied** - Recent bankruptcy disqualification

### Regulatory Guidelines
5 key regulations:
- Qualified Mortgage (QM) Rule
- Fair Housing Act
- TILA-RESPA Integrated Disclosure (TRID)
- Home Mortgage Disclosure Act (HMDA)
- Fannie Mae Selling Guide

## Integration with Existing Loan Data

This risk assessment data is designed to work with the loan application data in `../sample-loan-application.md`. The workflow:

1. **Document Parsing Agent** (existing): Parses loan documents using the MCP tool
2. **Risk Assessment Agent** (Foundry IQ): Evaluates parsed data against indexed policies

### Sample Loan Application Metrics

From the existing sample loan application:
- **Annual Income**: $185,000
- **Loan Amount**: $450,000
- **Property Value**: $575,000
- **Years Employed**: 4 years (full-time)
- **Total Assets**: $346,500
- **Monthly Debt**: $775

**Calculated Metrics**:
- **DTI Ratio**: ~22.5% (low risk)
- **LTV Ratio**: ~78.3% (low risk, no PMI needed)
- **Reserves**: ~8+ months (strong)

## Using with Azure AI Search

### 1. Create the Index

Use the schema in `index_schema.json` or run the loader script:

```bash
# Set environment variables
export AZURE_SEARCH_ENDPOINT="https://your-search-service.search.windows.net"
export AZURE_SEARCH_INDEX_NAME="credit-risk-assessment-index"

# Run the loader
python -m src.search.index_loader
```

### 2. Configure Foundry IQ

In Azure AI Foundry:
1. Create a new Risk Assessment Agent
2. Add Azure AI Search as a knowledge source
3. Configure the search index: `credit-risk-assessment-index`
4. Enable semantic search with configuration: `semantic-config`

### 3. Workflow Integration

The Risk Agent can receive parsed loan data and:
1. Query relevant policies based on applicant metrics
2. Find similar historical cases for precedent
3. Check regulatory compliance requirements
4. Generate a comprehensive risk assessment

## Extending the Data

To add more data:
1. Follow the existing JSON schema in each file
2. Run the index loader to update the search index
3. New documents will be available immediately for grounding

## Schema Reference

Each indexed document includes:
- `id`: Unique identifier
- `document_type`: policy, scoring_model, case, or regulation
- `category`: Risk category (e.g., credit_risk)
- `subcategory`: Specific area (e.g., credit_score, dti)
- `title`: Document title
- `content`: Full searchable content
- `risk_level`: low, medium, high, critical
- `action`: approve, review, escalate, deny
- `keywords`: Searchable tags
