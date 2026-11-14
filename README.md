# Bellhaven Senior Living – CRM Data Reconciliation Pipeline

## 1. Project Overview

This project automates the reconciliation of Bellhaven Senior Living facility information between its public website and an existing CRM system.

The solution extracts facility information from the website, matches locations against CRM accounts, identifies discrepancies, and generates recommendations for human review.

A local Streamlit application allows reviewers to approve or reject proposed changes. Only approved proposals are eligible for execution through the CRM API.

The pipeline is designed for daily execution, with safeguards to prevent duplicate proposals and unintended CRM updates.

**Key objectives:**
- Scrape all Bellhaven communities and their available information.
- Match website locations with existing CRM accounts.
- Identify incorrect parent relationships, outdated names, new locations, and CRM-only accounts.
- Provide evidence-based recommendations through a review application.
- Apply approved corrections through the CRM API.
- Support safe, repeatable daily execution.

## 2. Technology Stack

| Component | Technology |
|---|---|
| Programming language | Python |
| Database | PostgreSQL |
| ORM | SQLAlchemy |
| Web scraping | Requests, BeautifulSoup |
| Data matching | RapidFuzz |
| Review application | Streamlit |
| CRM integration | REST API |
| Data format | JSON, JSONB |
| Automation | GitHub Actions |
| Environment configuration | Python dotenv |

## 3. Solution Architecture

The solution consists of five main stages.

1. **Website scraping:** Extract facility names, addresses, ZIP codes, and care offerings from all community listing pages.
2. **CRM extraction:** Retrieve CRM accounts using paginated API requests.
3. **Matching and classification:** Normalize data, calculate matching scores, and classify discrepancies.
4. **Human review:** Display recommendations and supporting evidence in the Streamlit application.
5. **CRM execution:** Apply approved changes through the CRM API and record execution results.

### Pipeline workflow

```text
Bellhaven Website
       |
       v
  Web Scraper
       |
       v
Validate Website Data
       |
       v
PostgreSQL <-------- CRM REST API
       |                    |
       |              CRM Data Loader
       |                    |
       +--------------------+
                  |
                  v
          Matching Engine
                  |
                  v
            Classification
                  |
                  v
         Proposal Generation
                  |
                  v
          PostgreSQL
                  |
                  v
       Streamlit Review App
                  |
           Approve / Reject
                  |
                  v
       Approved Proposals Only
                  |
                  v
          CRM API Executor
                  |
                  v
       CRM Verification
                  |
                  v
          Execution Audit
```

## 4. Project Structure

```text
bellhaven-crm/
│
├── .github/
│   └── workflows/
│       └── daily-pipeline.yml
│
├── data/
│   ├── scraped_locations.json
│   ├── classification_results.json
│   └── scraping_errors.json
│
├── review_app/
│   └── app.py
│
├── src/
│   ├── business_rules.py
│   ├── classify_accounts.py
│   ├── crm_client.py
│   ├── database.py
│   ├── execute_approved_proposals.py
│   ├── generate_all_proposals.py
│   ├── generate_proposals.py
│   ├── load_crm_data.py
│   ├── load_website_data.py
│   ├── matching.py
│   ├── models.py
│   └── normalize.py
│
├── tests/
│   └── test_normalize.py
│
├── scraper.py
├── config.py
├── init_db.py
├── requirements.txt
├── README.md
└── .env
```

The `.env` file contains local credentials and must not be committed to version control.

## 5. Website Scraping

The scraper extracts information from the Bellhaven communities website, including:

- Community name
- Street address
- City
- State
- ZIP code
- Care offerings
- Source URL

The scraper follows pagination links to collect all community listing pages and visits individual community pages to extract details.

**Validation safeguards:**
- Checks the expected number of communities.
- Detects duplicate source URLs.
- Checks required fields.
- Records scraping failures.
- Prevents an incomplete scrape from replacing the existing validated dataset in the pipeline.

**Scraping result:** 34 community records successfully collected.

Output: `data/scraped_locations.json`

## 6. Data Matching and Classification

### Data normalization

The matching process normalizes website and CRM information before comparison.

Normalization includes:
- Converting text to a consistent case.
- Removing punctuation and unnecessary whitespace.
- Standardizing common street suffixes.
- Normalizing state names and abbreviations.
- Standardizing ZIP codes.

This helps identify equivalent values even when formatting differs.

### Matching methodology

The matching engine uses weighted similarity scoring.

| Matching attribute | Weight |
|---|---:|
| Facility name | 40% |
| Street address | 30% |
| City | 10% |
| State | 10% |
| ZIP code | 10% |
| **Total** | **100%** |

RapidFuzz is used for fuzzy text comparison. City, state, and ZIP comparisons use normalized values.

Address evidence is also checked to reduce false-positive matches.

### Classification rules

| Classification | Meaning |
|---|---|
| CONFIDENT_MATCH | Strong match with sufficient supporting evidence |
| MATCH_WRONG_PARENT | Matching CRM account has an incorrect parent |
| POSSIBLE_MATCH | Potential match requiring human verification |
| NO_CRM_ACCOUNT | No sufficiently credible existing CRM match |
| CRM_ONLY | CRM account under Bellhaven was not found in the current website listing |

The matching thresholds are:

- High confidence: score of 90 or above.
- Possible match: score of 75 or above, with sufficient address evidence.
- Lower scores or insufficient address evidence require further investigation.

These thresholds support recommendations; they do not independently authorize CRM updates.

## 7. Business Rules

### Parent account correction

The Bellhaven parent account ID is:

`0015QAPLGS3FVYEEEM`

When a facility is associated with an incorrect parent, the system checks its financial history before recommending a correction.

### Change of ownership (CHOW)

The assessment requires the original account to be preserved when both conditions are true:

- `lifetime_revenue > 0`
- `outstanding_ar > 0`

In this situation:

1. Preserve the original CRM account.
2. Create a new facility account under the Bellhaven parent.
3. Set `chow_current_account` on the original account to the new account ID.
4. Do not change the original account's parent.

### Direct re-parenting

If either lifetime revenue or outstanding AR is zero, the existing account can be re-parented directly.

The system updates the parent relationship and corrects the facility name when necessary.

### New facility accounts

When no sufficiently credible CRM match exists, the system proposes creating a new account under Bellhaven.

The website's care offerings are preserved as evidence. They are not automatically mapped to CRM care types unless the mapping is exact and unambiguous.

### CRM-only accounts

A CRM account missing from the current website listing is not automatically deactivated.

Instead, the system recommends manual review because website absence alone does not establish that a facility is closed.

### Duplicate accounts

The CRM API does not provide merge or delete functionality.

When a duplicate is confirmed, the intended procedure is:

- Preserve the surviving account.
- Set `duplicate_of_account` on the losing account to the surviving account ID.
- Set the losing account's status to `Inactive`.
- Explain the decision in the account note.

Duplicate handling requires verified evidence and reviewer approval.

## 8. PostgreSQL Database Design

The application uses PostgreSQL to store source data, CRM snapshots, proposals, execution history, and audit records.

Main tables:

| Table | Purpose |
|---|---|
| website_locations | Stores scraped website facility information |
| crm_accounts | Stores CRM account snapshots |
| proposals | Stores proposed reconciliation actions and review decisions |
| proposal_audit | Records approval, rejection, and execution events |
| pipeline_runs | Tracks pipeline execution history |

JSONB fields preserve source information, supporting evidence, recommended changes, and execution results.

SQLAlchemy provides database access and ORM functionality.

## 9. Review Application

The Streamlit review application runs locally.

It provides:

- Proposal summary metrics.
- Filters by proposal status and classification.
- Website and CRM account comparisons.
- Matching scores and supporting evidence.
- Recommended changes and business-rule explanations.
- Reviewer identification.
- Approve and reject actions.
- Proposal audit history.

**Important approval rule:** Reviewing a proposal changes its decision status in PostgreSQL. It does not immediately modify the CRM.

Only approved proposals are eligible for execution.

## 10. CRM API Execution and Safety

The CRM executor is separate from the proposal-generation pipeline.

It supports:
- Creating new facility accounts.
- Re-parenting existing accounts.
- Executing CHOW operations.
- Recording execution results.
- Verifying changes through subsequent CRM API requests.

### Execution safeguards

- Dry-run is the default behavior.
- Live execution requires an explicit `--execute` argument.
- Only Approved proposals are considered.
- Pending and Rejected proposals are never executed.
- Financial conditions are checked again before parent changes.
- Execution state is recorded to prevent unsafe retries.
- Partial CHOW operations are recorded for manual reconciliation.
- CRM changes are verified after execution.

The CRM executor must not be included in the automated daily refresh workflow.

## 11. Actual CRM Reconciliation Results

The assessment pipeline was executed, proposals were reviewed, and approved changes were applied through the CRM API.

**Completed CRM write operations: 8**

| Operation | Count | Result |
|---|---:|---|
| New facility accounts | 4 | Successful |
| CHOW operations | 2 | Successful |
| Direct re-parenting | 2 | Successful |
| **Total** | **8** | **Verified** |

### New accounts created

| Facility | New CRM account ID |
|---|---|
| Bellhaven of Kettering | 001E52772605FC687A |
| Bellhaven of Chagrin Falls | 00142EBFF13E38186A |
| Bellhaven of Carlisle | 00184531EB13F262E4 |
| Amberly Manor | 001E670D49F9D8A9F1 |

### CHOW operations

| Facility | New CRM account ID |
|---|---|
| Bellhaven of Marietta | 001D8A1822FA615FAC |
| Bellhaven of Tiffin | 0012ECA69C6B06A2BB |

For both facilities, the original accounts were preserved and their `chow_current_account` fields were updated to reference the newly created accounts.

### Direct re-parenting

- Bellhaven Crossings of Lima
- Bellhaven of Zanesville

Both existing accounts were updated under the Bellhaven parent.

### Other review decisions

- Two possible matches were approved for manual review without automatic CRM updates.
- Three CRM-only account proposals were rejected rather than automatically deactivating the accounts.
- Three proposed new facility accounts were rejected.
- Approved and rejected decisions are preserved during subsequent proposal-generation runs.

All eight write operations were recorded as successful in PostgreSQL and verified against the CRM API.

## 12. Daily Automation

The project includes a GitHub Actions workflow:

`.github/workflows/daily-pipeline.yml`

The workflow supports:
- Scheduled daily execution.
- Manual execution through GitHub Actions.
- Python dependency installation.
- Secure credentials through GitHub repository secrets.
- Pipeline execution and logs.

The daily workflow performs:

1. Website scraping and validation.
2. CRM account refresh.
3. Website data loading.
4. Classification.
5. Proposal generation.

It does not approve proposals or execute CRM updates.

### Safe rerun behavior

The proposal generator:
- Updates existing Pending proposals.
- Preserves Approved and Rejected proposals.
- Avoids generating another proposal for a previously reviewed website location or CRM-only account.
- Stops when multiple Pending proposals exist for the same business identity, requiring manual investigation.

CRM execution remains a separate, deliberate action.

**Infrastructure requirement:** GitHub Actions requires access to the PostgreSQL database. A locally running database is not accessible to a GitHub-hosted runner unless an appropriate secure network or self-hosted runner is configured.

## 13. Installation and Setup

### Prerequisites

- Python 3.11
- PostgreSQL
- Git
- CRM API access credentials

### Step 1: Clone the repository

```bash
git clone <your-repository-url>
cd bellhaven-crm
```

### Step 2: Create a virtual environment

Windows:

```bash
python -m venv venv
venv\Scripts\activate
```

### Step 3: Install dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Configure environment variables

Create a local `.env` file containing the database connection string and CRM API credentials.

Use the exact environment variable names expected by `config.py` and `crm_client.py`.

Never commit `.env` or expose CRM tokens.

### Step 5: Initialize the database

```bash
python init_db.py
```

### Step 6: Run the pipeline

```bash
python -m src.pipeline
```

### Step 7: Start the review application

```bash
streamlit run review_app/app.py
```

### Step 8: Execute approved CRM proposals

First perform a dry run:

```bash
python -m src.execute_approved_proposals
```

After reviewing the proposals and confirming the approved changes, execute them:

```bash
python -m src.execute_approved_proposals --execute
```

For a single approved proposal:

```bash
python -m src.execute_approved_proposals --execute --proposal-id <ID>
```

Never execute unreviewed proposals.

## 14. Testing and Verification

The project includes normalization tests and manual integration verification.

Examples:

```bash
python -m tests.test_normalize
```

The pipeline and executor were tested using the assessment CRM API and PostgreSQL database.

Verification included:
- Scraping 34 website communities.
- Retrieving all 127 CRM accounts using pagination.
- Loading website and CRM records into PostgreSQL.
- Running classification and proposal generation.
- Testing the executor in dry-run mode.
- Executing approved CRM changes.
- Verifying created accounts and updated parent relationships.
- Confirming successful execution records in PostgreSQL.
- Testing safe proposal-generation reruns.

## 15. Security and Design Considerations

- CRM credentials are stored outside source code.
- Database access is handled through SQLAlchemy.
- CRM requests use authenticated API calls.
- Human approval is required before CRM writes.
- CRM-only accounts are not automatically deactivated.
- Website care offerings are retained as evidence.
- Execution results and review decisions are audited.
- No LLM API key is required by the pipeline.

## 16. Conclusion

The Bellhaven CRM reconciliation solution combines web scraping, data normalization, fuzzy matching, business-rule validation, human review, and controlled CRM API execution.

The system is designed to make reconciliation repeatable while protecting existing CRM data and preventing unauthorized changes.

The completed assessment run produced eight successful CRM write operations, including new account creation, CHOW processing, and direct re-parenting. The pipeline also preserves reviewed decisions to support safe daily execution.
