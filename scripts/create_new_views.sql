-- ============================================================================
-- NEW VIEWS FOR AI AGENT - Created for enhanced query capabilities
-- Naming convention: _FOR_AI suffix to distinguish from existing views
-- ============================================================================

-- View 1: Presenter Master Data
-- Purpose: List all active presenters with their details
-- Example queries: "List all executive presenters", "Find presenter by email"
CREATE OR REPLACE VIEW VW_PRESENTER_REPORT_FOR_AI AS
SELECT 
    p.id AS presenterId,
    p.first_name AS firstName,
    p.last_name AS lastName,
    p.first_name || ' ' || p.last_name AS fullName,
    p.primary_email AS email,
    p.designation,
    p.work_phone_number AS phone,
    DECODE(trim(p.is_executive), '1', 'Yes', 'No') AS isExecutive,
    DECODE(trim(p.is_active), '1', 'Yes', 'No') AS isActive,
    p.location_id AS locationId
FROM M_PRESENTER p
WHERE p.is_active = '1'
ORDER BY p.last_name, p.first_name;

-- View 2: Event-Presenter Relationships
-- Purpose: Show which presenters were assigned to which events
-- Example queries: "Who presented at event X?", "Show presenter history for this month"
CREATE OR REPLACE VIEW VW_EVENT_PRESENTER_REPORT_FOR_AI AS
SELECT 
    to_char(req_master.id) AS eventId,
    req_master.TEXT_FIELD_1 AS customerName,
    req_master.TEXT_FIELD_2 AS primaryOpportunity,
    to_number(req_master.START_DATE.utcMs) AS startDateMs,
    req_master.START_DATE AS startDate,
    rap.first_name AS presenterFirstName,
    rap.last_name AS presenterLastName,
    rap.first_name || ' ' || rap.last_name AS presenterName,
    rap.primary_email AS presenterEmail,
    rap.presenter_type AS presenterType,
    rap.status AS presenterStatus,
    rap.designation AS presenterDesignation
FROM M_REQUEST_MASTER req_master
JOIN T_REQUEST_AGENDA_PRESENTER rap ON rap.request_master_id = req_master.id
WHERE req_master.category_id = 512154
ORDER BY req_master.id, rap.last_name;

-- View 3: Location Master Data
-- Purpose: List all active locations with their details
-- Example queries: "Show me all locations", "Which locations are in Austin?", "Locations with capacity > 50"
CREATE OR REPLACE VIEW VW_LOCATION_REPORT_FOR_AI AS
SELECT 
    loc.id AS locationId,
    loc.code AS locationCode,
    loc.name AS locationName,
    loc.address1 AS address,
    loc.address2 AS address2,
    loc.city,
    loc.state,
    loc.zipcode,
    loc.capacity,
    loc.contact_name AS contactName,
    loc.contact_email AS contactEmail,
    loc.contact_phone AS contactPhone,
    DECODE(trim(loc.is_assignable), '1', 'Yes', 'No') AS isAssignable,
    DECODE(trim(loc.is_private), '1', 'Yes', 'No') AS isPrivate
FROM M_LOCATION loc
WHERE loc.is_active = '1'
ORDER BY loc.city, loc.name;

-- ============================================================================
-- Verification queries (run after creating views)
-- ============================================================================

-- Check if views were created successfully
SELECT view_name FROM all_views 
WHERE owner = 'BIQ_EIQ_AURORA' 
AND view_name LIKE '%_FOR_AI'
ORDER BY view_name;

-- Test row counts
SELECT 'VW_PRESENTER_REPORT_FOR_AI' AS view_name, COUNT(*) AS row_count 
FROM VW_PRESENTER_REPORT_FOR_AI
UNION ALL
SELECT 'VW_EVENT_PRESENTER_REPORT_FOR_AI', COUNT(*) 
FROM VW_EVENT_PRESENTER_REPORT_FOR_AI
UNION ALL
SELECT 'VW_LOCATION_REPORT_FOR_AI', COUNT(*) 
FROM VW_LOCATION_REPORT_FOR_AI;

