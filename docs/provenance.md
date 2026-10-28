# Provenance and lawful use

## Data status

All supplier acknowledgement workflow records in this repository are fully synthetic. No external datasets are used. Supplier, employee/actor, carrier, warehouse, and contact names and contact details are synthetic placeholders; they do not identify real people or companies. Prices, order quantities, delivery dates, reliability scores, decisions, events, and operational outcomes are generated for software testing only. No confidential, personal, customer, or production information is included.

## Schema inspiration

The schema uses common procurement and supply-chain concepts such as purchase orders, line items, supplier acknowledgements, promise dates, change requests, approval history, inventory projections, production allocations, notifications, and append-only event logs. These are general business concepts modeled independently for this project. No proprietary schema, vendor data dictionary, or private implementation has been copied.

## External data policy

If external data were used, we would record:

- source URL;
- dataset name and version;
- retrieval date;
- license and terms of use;
- attribution requirements;
- transformations performed; and
- fields discarded and the reason for discarding them.

Only legally redistributable data would be considered. License and terms would be reviewed before use, attribution would be retained where required, and confidential or personal information would not be included. At present, this section describes a future process only; no external data was used to create the included data.

## Reproducibility and integrity

The configured seed, scale, configuration snapshot, generator version, dependency versions, per-table row counts, generation timestamp, and file SHA-256 checksums are recorded in `data/generated/manifest.json`. The repository validation suite includes a scan for common API-key, access-token, and private-key signatures in tracked files. A passing scan is a heuristic check, not a substitute for credential-management practices or a guarantee against every possible secret format.
