# Provenance and data sourcing

The initial dataset is intended to be generated synthetically from `config/generator_config.yaml`. No public or proprietary supplier dataset is bundled at bootstrap.

If public datasets are added later, record for each source: dataset name, publisher, canonical URL, retrieval date, licence/terms, fields reused, transformations, and whether records are synthetic, anonymized, or public. Do not add confidential supplier, pricing, shipment, or employee data without explicit authorization.

The configured random seed (`20261022`) is intended to make synthetic generation reproducible.

## Synthetic master data generated for the challenge

The current starter sample tables (`suppliers.csv`, `purchase_orders.csv`, `po_lines.csv`, `items.csv`, `actors.csv`, `carriers.csv`, and `warehouses.csv`) are entirely synthetic and generated locally by `src/supplier_ack/generators/`. No public or supplier-proprietary data is used. All names, contact details, locations, carrier names, item names, prices, supplier reliability values, and lead times are fictional simulation inputs. The `.test` email domain is reserved for non-production examples. The generator seed, scale, counts, and summary statistics are recorded in `data/samples/generation_summary.json` for reproducibility.
