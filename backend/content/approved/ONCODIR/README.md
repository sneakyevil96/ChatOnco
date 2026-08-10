# ONCODIR LIP-01 approved FAQ v1

`faq-v1.csv` is the controlled import representation of the reviewed source
document `ONCODIR LIP-01 Chatbot Knowledge Base.docx` received on 2026-08-10.

Source document SHA-256:

`BFFCF7822D7EC83766384B3DD74B5383181302E6A7FB92EB2D9BF8E62269C8C3`

The collection contains 55 FAQ items and 66 question phrasings. Answers retain
the wording supplied in the reviewed document. Explicit slash-separated
question variants were stored as alternatives; no additional factual content
or contact detail was invented.

The source document itself is the review reference because it contains no
individual reviewer names. Its file timestamp is recorded as `reviewed_at` for
traceability. Nine medically adjacent project/risk/AI items retain the source
document as both the administrative and clinical review reference, consistent
with the confirmation that the supplied document is already reviewed.

English answers, validity end dates, and information absent from the source
remain empty. Semantic retrieval remains disabled until a separately reviewed
Romanian evaluation set is supplied and thresholds are calibrated. Therefore,
the initial deployment answers only approved exact normalized phrasings and
escalates everything else.

Validate without database changes:

`python -m app.commands.import_faqs --project ONCODIR --file content/approved/ONCODIR/faq-v1.csv`

Publication requires an active ONCODIR administrator and the explicit
`--publish` flag. Do not edit a published v1 file in place; create a new
versioned import after a content change is reviewed.
