"""
Compact OpenSearch schema reference for the LLM system prompt.

This distills the live index mappings down to the business-meaningful fields the
model actually needs to build correct queries. All paths below were verified
against live data (field population counts), not just the mapping.

Rules encoded here:
  • Filters / sort / aggs  → use .keyword  (e.g. status.stateName.keyword)
  • _source paths          → NO .keyword
  • startTime (events)     → epoch ms (long); activities use startTime.utcMs
  • date ranges            → include format: "epoch_millis"
  • Forbidden keys         → script_fields, scripted_metric, runtime_mappings

⚠️ SCHEMA MIGRATION NOTE (verified live):
  • events index:     rich form data moved from `eventData.{SECTION}.data.{field}`
                      → `eventFormData.{SECTION}.{field}` (arrays, `.data` dropped).
                      The old `eventData.*` tree still exists in the mapping but is
                      EMPTY — never query it.
  • activities index: `activityInfo.{SECTION}.data.{field}`
                      → `activityData.{SECTION}.{field}` (`activityInfo` is empty).
                      Room name is `resource.metaData.searchDisplayText`
                      (resource.data.name is empty).
"""

SCHEMA_REFERENCE = """
## OpenSearch Index: events (54 docs)

### Event Core (top-level — always populated)
| Field | Type | Notes |
|-------|------|-------|
| eventId | text (+kw) | Unique event ID |
| eventName | text (+kw) | Event / meeting name |
| eventNumber | text (+kw) | Human-readable booking number (e.g. CBR-20261210-4695) |
| startTime | long | **Epoch milliseconds** — primary date field for range queries |
| duration | long | Duration in minutes |
| isActive | boolean | |
| isDeleted | boolean | |
| timezone | text (+kw) | IANA timezone of event |

### Dates (startDate object — alternative to startTime)
| Field | Type |
|-------|------|
| startDate.utcMs | long |
| startDate.zoneDate | long |
| startDate.context.contextZoneDate | date |
| startDate.requested.requestedZoneDate | date |

### Status
| Field | Type |
|-------|------|
| status.stateName | text (+kw) |
| status.stateCode | text (+kw) |
| status.colorCode | text (+kw) |

Known stateName values (verified from data): Initialized, Hold, Waitlist, Confirmed
(legacy values still valid: Submitted, Cancel)

### Category & Type
| Field | Type |
|-------|------|
| category.categoryName | text (+kw) |
| category.uniqueId | text (+kw) |
| categoryType.categoryTypeName | text (+kw) |

Known categoryName values (verified from data): Customer Briefing Request,
Executive Dining Request, Non Customer Briefing Request
(legacy location-suffixed variants may also appear)

### Location (location.data.*)
| Field | Type | Notes |
|-------|------|-------|
| location.data.locationName | text (+kw) | **Prefer this for location filtering** — full location name |
| location.data.city | text (+kw) | ⚠️ Stores abbreviated names — e.g. "Redwood" not "Redwood Shores" |
| location.data.state | text (+kw) | |
| location.data.country | text (+kw) | |
| location.data.baseTimezone | text (+kw) | |
| location.data.addressLine1 | text (+kw) | |
| location.data.zipCode | text (+kw) | |

Known locationName values (verified from data): Redwood Shores, Reston, VA, Austin, TX
(legacy: Nashville, TN, Experience Center, Virtual EBC, Oracle Industry Lab - Sydney)

### Visit Info (eventFormData.VISIT_INFO.*)  ⚠️ ARRAY — `.data` segment is GONE
Core briefing/meeting metadata — the richest event-level section.
Use full dotted path, e.g. `eventFormData.VISIT_INFO.customerName`
| Field | Type | Business meaning |
|-------|------|-----------------|
| eventFormData.VISIT_INFO.customerName | text (+kw) | Customer / company name (53/54 populated) |
| eventFormData.VISIT_INFO.customerIndustry | text (+kw) | Industry vertical |
| eventFormData.VISIT_INFO.lineOfBusiness | text (+kw) | LOB |
| eventFormData.VISIT_INFO.region | text (+kw) | Geographic region |
| eventFormData.VISIT_INFO.country | text (+kw) | |
| eventFormData.VISIT_INFO.briefingManager | text (+kw) | Assigned briefing manager |
| eventFormData.VISIT_INFO.technicalManager | text (+kw) | |
| eventFormData.VISIT_INFO.meetingObjective | text (+kw) | Why the meeting exists |
| eventFormData.VISIT_INFO.visitFocus | text (+kw) | Focus area |
| eventFormData.VISIT_INFO.visitType | text (+kw) | Visit classification |
| eventFormData.VISIT_INFO.oracleHostName | text (+kw) | Host name |
| eventFormData.VISIT_INFO.oracleHostEmail | text (+kw) | Host email |
| eventFormData.VISIT_INFO.oracleHostBusinessTitle | text (+kw) | Host title |
| eventFormData.VISIT_INFO.requesterEmail | text (+kw) | Who requested |
| eventFormData.VISIT_INFO.salesPlay | text (+kw) | Sales play |
| eventFormData.VISIT_INFO.accountId | text (+kw) | CRM account ID |
| eventFormData.VISIT_INFO.tier | text (+kw) | |
| eventFormData.VISIT_INFO.isStrategicClient | boolean | (52/54 populated) |

Known visitType values (verified from data): Existing Customer, Prospect, Partner,
Community Relation, Investor Relations

### External Attendees (eventFormData.EXTERNAL_ATTENDEES.*)  ⚠️ ARRAY
Customer-side attendees. ~18/54 events have attendees loaded.
| Field | Type | Business meaning |
|-------|------|-----------------|
| eventFormData.EXTERNAL_ATTENDEES.attendeeName | text (+kw) | Full name |
| eventFormData.EXTERNAL_ATTENDEES.firstName | text (+kw) | |
| eventFormData.EXTERNAL_ATTENDEES.lastName | text (+kw) | |
| eventFormData.EXTERNAL_ATTENDEES.businessTitle | text (+kw) | Job title |
| eventFormData.EXTERNAL_ATTENDEES.chiefOfficerTitle | text (+kw) | C-level title if any |
| eventFormData.EXTERNAL_ATTENDEES.company | text (+kw) | Company name |
| eventFormData.EXTERNAL_ATTENDEES.email | text (+kw) | |
| eventFormData.EXTERNAL_ATTENDEES.decisionMaker | boolean | Is a decision-maker? |
| eventFormData.EXTERNAL_ATTENDEES.influencer | boolean | Is an influencer? |
| eventFormData.EXTERNAL_ATTENDEES.isRemote | boolean | Attending remotely? |
| eventFormData.EXTERNAL_ATTENDEES.isTechnical | boolean | |

### Internal Attendees (eventFormData.INTERNAL_ATTENDEES.*)  ⚠️ ARRAY
| Field | Type |
|-------|------|
| eventFormData.INTERNAL_ATTENDEES.firstName | text (+kw) |
| eventFormData.INTERNAL_ATTENDEES.lastName | text (+kw) |
| eventFormData.INTERNAL_ATTENDEES.businessTitle | text (+kw) |
| eventFormData.INTERNAL_ATTENDEES.company | text (+kw) |
| eventFormData.INTERNAL_ATTENDEES.email | text (+kw) |
| eventFormData.INTERNAL_ATTENDEES.isRemote | boolean |

### Opportunity (eventFormData.Opportunity.*)  ⚠️ ARRAY
Revenue / pipeline linked to event. (52/54 have opportunityRevenue)
| Field | Type | Business meaning |
|-------|------|-----------------|
| eventFormData.Opportunity.opportunity | text (+kw) | Opportunity name / ID |
| eventFormData.Opportunity.oppStatus | text (+kw) | See known values below |
| eventFormData.Opportunity.opportunityRevenue | float | Current revenue |
| eventFormData.Opportunity.initialOpportunityRevenue | float | Starting revenue |
| eventFormData.Opportunity.closedOpportunityRevenue | float | Revenue at close |
| eventFormData.Opportunity.probabilityOfClose | text (+kw) | % likelihood |
| eventFormData.Opportunity.quarterOfClose | text (+kw) | Target quarter |
| eventFormData.Opportunity.isPrimary | boolean | Primary opportunity? |

Known oppStatus values (verified from data): In Progress, Closed Won, On Hold,
Pending, Open, Closed Lost

### Visit Summary (eventFormData.VISIT_SUMMARY.*)  ⚠️ ARRAY
Post-visit wrap-up. (~15/54 populated)
| Field | Type |
|-------|------|
| eventFormData.VISIT_SUMMARY.summary | text (+kw) |
| eventFormData.VISIT_SUMMARY.customerVisitObjective | text (+kw) |
| eventFormData.VISIT_SUMMARY.desiredOutcome | text (+kw) |
| eventFormData.VISIT_SUMMARY.businessCase | text (+kw) |
| eventFormData.VISIT_SUMMARY.competitors | text (+kw) |
| eventFormData.VISIT_SUMMARY.customerInitiative | text (+kw) |

### Other event sections (eventFormData.*)  ⚠️ ARRAY
| Section | Example fields |
|---------|----------------|
| eventFormData.CATERING.* | cateringType, dietaryRestrictions, noOfAttendees, notes (sparse — ~1 event) |
| eventFormData.VIRTUAL_CONNECTION.* | meetingPlatForm, bridge, joinUrl, hostUrl, meetingId |
| eventFormData.topic.* | per-event topic rollup (prefer activities index for topics) |
| eventFormData.topic_presenter.* | per-event presenter rollup (prefer activities index) |

⚠️ Do NOT use `eventData.*` (old path) or `eventData.*.data.*` — that tree is empty.
⚠️ Per-activity topic/presenter detail is NOT populated on the events index under
   `activityDays.activities.*` — query the **activities** index instead.

---

## OpenSearch Index: activities (539 docs)

Each document is ONE activity/session. Use this index for **per-activity questions**
(topics, room utilization, presenter lookups, catering per session). Links to parent
event via `eventId`.

### Activity Core
| Field | Type | Notes |
|-------|------|-------|
| activityId | text (+kw) | Unique activity ID |
| eventId | text (+kw) | **Parent event ID** — join back to events index |
| activityType | text (+kw) | Values: TOPIC_ACTIVITY, CATERING (also legacy: Topic, catering) |
| duration | long | Minutes |
| startTime.utcMs | long | Activity start (epoch ms) |
| endTime.utcMs | long | Activity end (epoch ms) |
| activityDate.utcMs | long | Activity date (epoch ms) |
| activityDayId | text (+kw) | Day grouping ID |
| bookingId | text (+kw) | |
| createdBy | text (+kw) | |

### Activity Status
| Field | Type |
|-------|------|
| status.stateName | text (+kw) | Currently all "Confirmed" |
| status.stateCode | text (+kw) |
| status.displayText | text (+kw) |

### Resource / Room
| Field | Type | Notes |
|-------|------|-------|
| resource.metaData.searchDisplayText | text (+kw) | **Room name** — use THIS (e.g. "Glacier Room"). `resource.data.name` is empty |
| resource.uniqueId | text (+kw) | Room/resource ID |
| resourceId | text (+kw) | Room/resource ID (top-level) |
| resource.resourceType.name | text (+kw) | e.g. "Room" |

### Topic (activityData.topic.*)  ⚠️ `.data` segment is GONE
| Field | Type | Notes |
|-------|------|-------|
| activityData.topic.topic.textField1 | text (+kw) | **Topic name** (329 populated) |
| activityData.topic.topic.textField2 | text (+kw) | Topic name (alt) |
| activityData.topic.topicObjective | text (+kw) | Topic objective / notes |
| activityData.topic.optionalTopic | text (+kw) | Secondary topic |
| activityData.topic.status.stateName | text (+kw) | Topic status |

### Presenter (activityData.topic_presenter.*)  ⚠️ `.data` segment is GONE
| Field | Type | Notes |
|-------|------|-------|
| activityData.topic_presenter.presenter.primaryEmail | text (+kw) | Presenter email (317 populated) |
| activityData.topic_presenter.presenter.firstName | text (+kw) | |
| activityData.topic_presenter.presenter.lastName | text (+kw) | |
| activityData.topic_presenter.presenter.presenterName | text (+kw) | Full name |
| activityData.topic_presenter.presenter.designation | text (+kw) | Title |
| activityData.topic_presenter.presenterStatus | text (+kw) | Values: Accepted, Pending, Declined |
| activityData.topic_presenter.presenterEmail | text (+kw) | Email (flat) |
| activityData.topic_presenter.presenterTitle | text (+kw) | Title (flat) |

### Presenter Events (activityData.PRESENTER_EVENTS.*) — alternative presenter section
Same structure as topic_presenter (presenter.primaryEmail, presenter.designation,
presenterStatus, etc.). Prefer topic_presenter; fall back here if empty.

### Catering (activityData.CATERING.*)
| Field | Type |
|-------|------|
| activityData.CATERING.cateringType | text (+kw) |
| activityData.CATERING.dietaryRestrictions | text (+kw) |
| activityData.CATERING.noOfAttendees | long |
| activityData.CATERING.notes | text (+kw) |

### Visit Info per Activity (activityData.EVENTS_VISIT_INFO.*)
Section exists in mapping but is sparsely/not populated in current data — prefer
joining to the events index via `eventId` for customer/industry/C-level context.

---

## Query Rules (both indices)
- **Filters, sort, aggs** → append `.keyword` (e.g. `status.stateName.keyword`)
- **_source paths** → NO `.keyword`
- **events date field** → `startTime` is epoch milliseconds (long). Activities use `startTime.utcMs`.
- **Date ranges** → include `"format": "epoch_millis"` in range clause
- **Forbidden** → `script`, `script_fields`, `scripted_metric`, `runtime_mappings`
- **NO nested queries** → All fields are plain object/array types, NOT nested type. Use `exists`, `term`, `match` directly on the dotted path.
- **Size cap** → max 50 per request. Use `size: 0` + aggs for counts/breakdowns.
- **text (+kw)** means the field has both `text` (full-text match) and `.keyword` (exact / aggs).
- **Location filtering** → prefer `location.data.locationName` over `location.data.city`.

## Index Selection Guide
- **Event-level questions** (customer, industry, attendees, opportunities, status, location, category) → `events` index, `eventFormData.*` paths
- **Activity-level questions** (topics, presenter lookups, room assignments, catering per session) → `activities` index (`index: "activities"`), `activityData.*` paths
- **Cross-reference** → query activities index, use `eventId` to look up parent event details from events index
""".strip()
