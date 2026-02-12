### Workflow: Risk Assessment Agent Testing: 

[Q: Extract loan data from: https://raw.githubusercontent.com/jimmyshah83/frontier-platform/main/sample-data/sample-loan-application.pdf](https://github.com/jimmyshah83/frontier-platform/tree/main)

### Here are example questions to test your Risk Assessment Agent against the indexed data:

Policy Queries:

"What is the risk level for an applicant with a credit score of 680?"
"What are the DTI requirements for loan approval?"
"What LTV ratio requires PMI?"
"What are the cash reserve requirements?"
Scoring Model Queries:

"How is the overall risk score calculated?"
"What weight does credit score have in the risk assessment?"
"What compensating factors can improve a risk score?"
Historical Case Queries:

"Show me examples of approved loans with elevated DTI"
"What happened in cases where applicants were self-employed?"
"Why would a loan with good credit still be denied?"
Regulatory Queries:

"What are the QM requirements for DTI?"
"What is the bankruptcy waiting period for Fannie Mae loans?"
"What disclosures are required under TRID?"
Combined Assessment (using sample data):

"Assess the risk for this applicant: credit score 712, DTI 38%, LTV 85%, 4 months reserves, employed 3 years"


### Sample questions for web search agent
"Find recent news articles about changes in mortgage lending regulations."
"Locate studies on the impact of credit scores on loan approval rates.":