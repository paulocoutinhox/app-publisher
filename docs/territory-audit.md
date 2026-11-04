# Read-only territory availability audit

`app-publisher availability CONFIG --provider apple|google|all` compares country availability in YAML with the official store APIs. It fails explicitly on mismatch, never attempts an undocumented write and does not infer the app's paid/free state.

```yaml
apple:
  territory_expectations:
    USA: true
    BRA: false

google:
  country_expectations:
    - track: production
      countries: [BR, US]
      sync_with_production: false
      rest_of_world: false
```

Apple territory IDs are App Store Connect territory resource IDs, which can differ from ISO two-letter country codes. Google uses uppercase two-letter CLDR codes for track-targeted countries. The Google API exposes country availability inside an edit. The tool creates and deletes a temporary edit for the read, without committing any changes. Availability can legitimately vary between testing tracks, so use an explicit track per expectation.

These fields are audits, not editors. Apple supports only limited pre-order territory writes through the public API. The official Google `edits.countryavailability` interface exposes GET without a corresponding write operation.
