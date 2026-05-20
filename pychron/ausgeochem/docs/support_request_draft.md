# Draft: EarthBank write access / sandbox enquiry

> **To:** support@lithodat.com
> **From:** Jake.Ross@nmt.edu
> **Subject:** EarthBank API — write access + test environment for Pychron integration

---

Hi LithoDat / EarthBank team,

I'm building a Pychron plugin that publishes ⁴⁰Ar/³⁹Ar data to EarthBank
on behalf of the New Mexico Geochronology Research Laboratory (NMGRL,
New Mexico Tech) and collaborating labs. The integration is being
developed in the open as part of the
[Pychron](https://github.com/NMGRL/pychron) project.

**What's working so far** (against `https://app.ausgeochem.org`):

- JWT auth via `/api/authenticate`
- Controlled-vocabulary resolution for `LArArMethod`, `LArArInterpretation`,
  `LAgeType`, `LAnalysisScale`, `LUncertaintyUnit`, `DecayConstant`,
  `AirRatio`, `FluxMonitor`, `materials`, and `LArArDataInterpretationTool`
  (including fuzzy author/year lookups for FluxMonitor)
- Payload builders + xlsx exporter rendering the
  `ArArDataPoint_Template2026` and `Sample.template.v2025-04-16` workbooks
  with values matching the manual HW reference uploads column-for-column

**What I'd like to confirm with you**:

1. **Write access.** My current account
   (`Jake.Ross@nmt.edu`) authenticates and reads fine but is not
   authorized for `POST /api/core/sample-with-locations`,
   `POST /api/arar/ArArDataPoint`, etc. Could you elevate this account
   (or issue a separate API account) so we can validate the live upload
   path end-to-end? Happy to scope to a single test data package if
   that's preferable.

2. **Sandbox / test environment.** Is there a non-production host
   (e.g. `sandbox.ausgeochem.org`, `test.lithosurfer.io`, internal
   staging) we can target while shaking out the integration? I couldn't
   find one mentioned in the
   [API license document](https://docs.google.com/document/d/e/2PACX-1vTyOIVPHtIUBJIuaMCkm9gG31GPEaKiIRW4GibzfgDGG-6JCh1rf8cX7CA6WYBJqUmCNST03-ORt680/pub)
   or via the swagger groups, and DNS for the obvious candidates
   doesn't resolve. If there isn't one, I'm happy to use production
   with a clearly-labeled "pychron-integration-test-*" prefix on the
   sample names and clean up afterward — just want to know the
   preferred protocol.

3. **Two-way link tables.** For `funding-2-data-points` and
   `literature-2-data-points`: should those POSTs use the same flow as
   the discipline-specific creates (resolve `fundingName` to a
   `fundingId` via `/api/core/fundings`, then POST `{ dataPointId,
   fundingId }`), or is there a richer helper endpoint I'm missing?

4. **Recommended `dataStructure` field.** When I POST
   `/api/core/data-points` linking a Sample to an `ArArDataPoint`, I'm
   sending `dataStructure: "ARARDATAPOINT"`. Is that the right enum
   value, and are there others I should be aware of for the linker
   record?

5. **Bulk-import status.** Is there an in-progress public spec for
   programmatic bulk upload of the
   `ArArDataPoint_Template2026.xlsx` workbook (as opposed to the
   per-record POST flow)? It would simplify the round-trip for labs
   that prefer the spreadsheet-and-review workflow.

Once write access is in place I can run my integration test against a
throwaway sample and share the resulting record IDs so you can verify
the payload shape is what you'd expect.

Thanks very much,

Jake Ross
Pychron maintainer · NMGRL, New Mexico Tech
Jake.Ross@nmt.edu

---

*Internal note (not part of email):* run
`python -m pychron.ausgeochem.tests.integration_test` once they grant
write perms and include the resulting record IDs in any follow-up.
