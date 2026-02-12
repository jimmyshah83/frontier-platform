You are a synthetic data generator for mortgage loan applications. Generate a diverse dataset of loan application documents as realistic free-text narratives (as a customer or loan officer might submit). Each document should be a single block of text simulating a scanned/uploaded loan application.

Generate 50 unique loan applications with the following distribution:

### Risk Profile Distribution:
- 15 LOW RISK applications (strong financials, low DTI, low LTV, high credit score)
- 15 MEDIUM RISK applications (borderline metrics, some concerns)
- 15 HIGH RISK applications (poor financials, high DTI, high LTV, low credit score)
- 5 EDGE CASES (missing fields, inconsistent data, unusual scenarios)

### Each application MUST include (where applicable):

**Applicant Information:**
- Full name, date of birth, SSN (use format XXX-XX-1234, redacted), phone, email
- Current address (vary across California cities, especially Oakland area)
- Marital status, dependents

**Employment Details:**
- Current employer name and address
- Job title, years employed (range: 0.5 to 30 years)
- Annual gross income (range: $35,000 to $500,000)
- Employment type: W-2, self-employed, 1099 contractor, retired

**Loan Details:**
- Loan amount requested (range: $150,000 to $2,000,000)
- Loan purpose: Purchase, Refinance, Cash-Out Refinance, Home Equity
- Loan term: 15-year or 30-year fixed
- Desired interest rate (if stated)

**Property Information:**
- Property type: Single Family, Condo, Townhouse, Multi-Family (2-4 units)
- Property address (California, primarily Oakland/Bay Area)
- Estimated property value (range: $200,000 to $3,000,000)
- Occupancy: Primary Residence, Second Home, Investment Property

**Credit Information:**
- Credit score (range: 520 to 850)
- Credit score source: Experian, TransUnion, Equifax
- Any derogatory marks: late payments, collections, bankruptcies, foreclosures

**Assets:**
- Checking/savings account balances
- Retirement accounts (401k, IRA)
- Investment accounts
- Other real estate owned
- Total liquid assets

**Liabilities & Monthly Debts:**
- Existing mortgage payments
- Auto loans
- Student loans
- Credit card minimum payments
- Alimony/child support
- Total monthly debt payments

**Declarations:**
- Any outstanding judgments
- Currently delinquent on any federal debt
- Party to a lawsuit
- Citizenship status (US Citizen, Permanent Resident, Non-Permanent Resident)

### Variation Requirements:
1. Vary the **writing style**: some formal, some informal, some with typos/abbreviations
2. Include applications with **co-borrowers** (at least 10 of 50)
3. Include **self-employed applicants** with more complex income (at least 8 of 50)
4. Include some with **gaps in employment** or **recent job changes**
5. For edge cases, include:
   - Missing credit score
   - Contradictory income vs. stated employer
   - Incomplete property information
   - Extremely high loan-to-value (>95%)
   - Very recent bankruptcy (within 2 years)

### Calculated Metrics (include ground truth for evaluation):
For each application, also output a JSON summary with:
```json
{
  "id": "LOAN-001",
  "applicant_name": "...",
  "annual_income": 120000,
  "monthly_debt_payments": 2800,
  "loan_amount": 450000,
  "property_value": 600000,
  "credit_score": 740,
  "expected_dti_ratio": 28.0,
  "expected_ltv_ratio": 75.0,
  "liquid_assets": 85000,
  "expected_reserves_months": 30.36,
  "expected_risk_category": "LOW",
  "has_co_borrower": false,
  "employment_type": "W-2",
  "property_type": "Single Family",
  "loan_purpose": "Purchase",
  "edge_case_flags": []
}
```

### Output Format:
For each of the 50 applications, output:
1. **Document text** — the raw loan application narrative (what gets sent to the workflow)
2. **Ground truth JSON** — the structured expected output for evaluation

Number each application sequentially: LOAN-001 through LOAN-050.