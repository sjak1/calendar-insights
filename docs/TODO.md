# TODO - Agenda Generator

## High Priority

- [ ] **Test event_id from headers changes**
  - Verify UUID → numeric ID conversion works end-to-end
  - Test with actual frontend headers (`x-cloud-eventid`)
  - Confirm priority: header event_id > LLM-extracted company_name

- [ ] **Fix document extraction for different formats**
  - Verify PDF extraction working correctly with pdfplumber
  - Test PPTX extraction from database
  - Handle edge cases (corrupted files, empty documents)
  - Add support for other formats if needed (DOCX, etc.)

- [x] **Revamp the prompt - make it generic (not Oracle-specific)**
  - ✅ Made prompt document-agnostic (doesn't assume EBD structure)
  - ✅ Changed "EBD" section → "Additional Document Context"
  - ✅ Uses conditional logic: "IF found, use it; otherwise skip"
  - ✅ No longer forces specific fields that may not exist

## Good to Have

- [ ] **Pipeline live flow visualization UI**
  - Real-time visualization of data flow through the pipeline
  - SSE/WebSocket for live updates
  - Animated nodes showing: API → LLM → Tool → DB → Output
  - Cool for demos and debugging

