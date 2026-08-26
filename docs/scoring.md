# Activity score

The activity score is a deterministic ranking aid for public business activity. It is not a credit score, company valuation, probability of success, or recommendation.

Current MVP formula:

    10
    + min(procurement_count × 4, 35)
    + min(subsidy_count × 3, 20)
    + min(patent_count × 2, 25)
    + min(certification_count, 10)

The result is capped at 100. Counts refer to dated signals actually stored by this service, not proof that no other activity exists. Every component can be reconstructed from the fields returned by the API.

Before using this score in production:

1. Measure source coverage and missingness.
2. Separate “no observed record” from “confirmed zero”.
3. Validate usefulness with paying customers.
4. Publish versioned formula changes.
5. Do not use the score for decisions about individuals or other high-impact decisions.
