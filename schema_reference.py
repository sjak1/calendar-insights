"""
Compact OpenSearch schema reference for the LLM system prompt.

This distills the full events_mapping.json (~274KB, 500+ fields) down to the
business-meaningful fields the model actually needs to build correct queries.

Rules encoded here:
  • Filters / sort / aggs  → use .keyword  (e.g. status.stateName.keyword)
  • _source paths          → NO .keyword   (e.g. eventData.VISIT_INFO.data.customerName)
  • startTime              → epoch ms (long)
  • date ranges            → include format: "epoch_millis" or "strict_date_optional_time||epoch_millis"
  • Forbidden keys         → script_fields, scripted_metric, runtime_mappings
  • All eventData.* fields → always use full dotted path in queries
"""

SCHEMA_REFERENCE = """
## OpenSearch Index: events

### Event Core
| Field | Type | Notes |
|-------|------|-------|
| eventId | text (+kw) | Unique event ID |
| eventName | text (+kw) | Event / meeting name |
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

Known stateName values (verified from data): Initialized, Submitted, Confirmed, Hold, Waitlist, Cancel

### Category & Type
| Field | Type |
|-------|------|
| category.categoryName | text (+kw) |
| category.uniqueId | text (+kw) |
| categoryType.categoryTypeName | text (+kw) |

Known categoryName values (verified from data): Customer Briefing Request, Cloud World, Mobile World Congress,
Customer Briefing Request - Reston, Customer Briefing Request - Redwood, Non Customer Briefing Request - Reston,
Non Customer Briefing Request - Austin, Executive Dining Request, Virtual Customer Briefing Request,
Non Customer Briefing Request, Non Customer Briefing Request - Redwood, Executive Dining Request - Nashville,
Executive Dining Request - Redwood

### Location (location.data.*)
| Field | Type | Notes |
|-------|------|-------|
| location.data.locationName | text (+kw) | **Prefer this for location filtering** — full location name |
| location.data.city | text (+kw) | ⚠️ Stores abbreviated names — e.g. "Redwood" not "Redwood Shores", "Reston" not "Reston, VA" |
| location.data.state | text (+kw) | |
| location.data.country | text (+kw) | |
| location.data.baseTimezone | text (+kw) | |
| location.data.addressLine1 | text (+kw) | |
| location.data.zipCode | text (+kw) | |
| location.data.primaryEmail | text (+kw) | |

Known locationName values (verified from data): Redwood Shores, Reston, VA, Austin, TX, Nashville, TN,
Experience Center, Virtual EBC, Oracle Industry Lab - Sydney

Known city values (verified from data): Redwood, Reston, Austin, Nashville, Kansas City, Sydney

Known baseTimezone values (verified from data): America/Los_Angeles, America/Chicago, America/New_York, Australia/Sydney

### Visit Info (eventData.VISIT_INFO.data.*)
Core briefing/meeting metadata — the richest event-level section.
⚠️ Always use full dotted path in queries, e.g. `eventData.VISIT_INFO.data.customerName`
| Field | Type | Business meaning |
|-------|------|-----------------|
| eventData.VISIT_INFO.data.customerName | text (+kw) | Customer / company name |
| eventData.VISIT_INFO.data.companyName | text (+kw) | Alternate company field |
| eventData.VISIT_INFO.data.companyWebsite | text (+kw) | |
| eventData.VISIT_INFO.data.customerIndustry | text (+kw) | Industry vertical |
| eventData.VISIT_INFO.data.lineOfBusiness | text (+kw) | LOB |
| eventData.VISIT_INFO.data.region | text (+kw) | Geographic region |
| eventData.VISIT_INFO.data.country | text (+kw) | |
| eventData.VISIT_INFO.data.briefingManager | text (+kw) | Assigned briefing manager |
| eventData.VISIT_INFO.data.technicalManager | text (+kw) | |
| eventData.VISIT_INFO.data.backUpTechnicalManager | text (+kw) | |
| eventData.VISIT_INFO.data.meetingObjective | text (+kw) | Why the meeting exists |
| eventData.VISIT_INFO.data.visitFocus | text (+kw) | Focus area |
| eventData.VISIT_INFO.data.visitType | text (+kw) | Visit classification |
| eventData.VISIT_INFO.data.oracleHostName | text (+kw) | Host name |
| eventData.VISIT_INFO.data.oracleHostEmail | text (+kw) | Host email |
| eventData.VISIT_INFO.data.oracleHostBusinessTitle | text (+kw) | Host title |
| eventData.VISIT_INFO.data.requesterEmail | text (+kw) | Who requested |
| eventData.VISIT_INFO.data.pillars | text (+kw) | Strategic pillar |
| eventData.VISIT_INFO.data.program | text (+kw) | Program name |
| eventData.VISIT_INFO.data.salesPlay | text (+kw) | Sales play |
| eventData.VISIT_INFO.data.accountId | text (+kw) | CRM account ID |
| eventData.VISIT_INFO.data.costCenter | text (+kw) | |
| eventData.VISIT_INFO.data.tier | text (+kw) | |
| eventData.VISIT_INFO.data.isStrategicClient | boolean | |
| eventData.VISIT_INFO.data.isComplaint | text (+kw) | |

Known visitType values (verified from data): Partner, Existing Customer, Prospect

### External Attendees (eventData.EXTERNAL_ATTENDEES.data.*)
Array of customer-side attendees.
⚠️ Always use full dotted path, e.g. `eventData.EXTERNAL_ATTENDEES.data.email`
| Field | Type | Business meaning |
|-------|------|-----------------|
| eventData.EXTERNAL_ATTENDEES.data.attendeeName | text (+kw) | Full name |
| eventData.EXTERNAL_ATTENDEES.data.firstName | text (+kw) | |
| eventData.EXTERNAL_ATTENDEES.data.lastName | text (+kw) | |
| eventData.EXTERNAL_ATTENDEES.data.businessTitle | text (+kw) | Job title |
| eventData.EXTERNAL_ATTENDEES.data.chiefOfficerTitle | text (+kw) | C-level title if any |
| eventData.EXTERNAL_ATTENDEES.data.company | text (+kw) | Company name |
| eventData.EXTERNAL_ATTENDEES.data.email | text (+kw) | |
| eventData.EXTERNAL_ATTENDEES.data.decisionMaker | boolean | Is a decision-maker? |
| eventData.EXTERNAL_ATTENDEES.data.influencer | boolean | Is an influencer? |
| eventData.EXTERNAL_ATTENDEES.data.isRemote | boolean | Attending remotely? |

### Internal Attendees (eventData.INTERNAL_ATTENDEES.data.*)
Array of host-side attendees.
⚠️ Always use full dotted path, e.g. `eventData.INTERNAL_ATTENDEES.data.email`
| Field | Type |
|-------|------|
| eventData.INTERNAL_ATTENDEES.data.firstName | text (+kw) |
| eventData.INTERNAL_ATTENDEES.data.lastName | text (+kw) |
| eventData.INTERNAL_ATTENDEES.data.businessTitle | text (+kw) |
| eventData.INTERNAL_ATTENDEES.data.company | text (+kw) |
| eventData.INTERNAL_ATTENDEES.data.email | text (+kw) |
| eventData.INTERNAL_ATTENDEES.data.isRemote | boolean |

### Opportunity (eventData.Opportunity.data.*)
Revenue / pipeline linked to event.
⚠️ Always use full dotted path, e.g. `eventData.Opportunity.data.opportunityRevenue`
| Field | Type | Business meaning |
|-------|------|-----------------|
| eventData.Opportunity.data.opportunity | text (+kw) | Opportunity name / ID |
| eventData.Opportunity.data.oppStatus | text (+kw) | Known values: Open, In Progress, Pending, On Hold, Closed Won, Closed Lost |
| eventData.Opportunity.data.opportunityRevenue | float | Current revenue |
| eventData.Opportunity.data.initialOpportunityRevenue | float | Starting revenue |
| eventData.Opportunity.data.closedOpportunityRevenue | float | Revenue at close |
| eventData.Opportunity.data.probabilityOfClose | text (+kw) | % likelihood |
| eventData.Opportunity.data.quarterOfClose | text (+kw) | Target quarter |
| eventData.Opportunity.data.isPrimary | boolean | Primary opportunity? |

### Visit Summary (eventData.VISIT_SUMMARY.data.*)
Post-visit wrap-up.
⚠️ Always use full dotted path, e.g. `eventData.VISIT_SUMMARY.data.summary`
| Field | Type |
|-------|------|
| eventData.VISIT_SUMMARY.data.summary | text (+kw) |
| eventData.VISIT_SUMMARY.data.customerVisitObjective | text (+kw) |
| eventData.VISIT_SUMMARY.data.desiredOutcome | text (+kw) |
| eventData.VISIT_SUMMARY.data.businessCase | text (+kw) |
| eventData.VISIT_SUMMARY.data.competitors | text (+kw) |
| eventData.VISIT_SUMMARY.data.customerInitiative | text (+kw) |
| eventData.VISIT_SUMMARY.data.anySensitiveIssues | text (+kw) |
| eventData.VISIT_SUMMARY.data.closedRevenue | long |
| eventData.VISIT_SUMMARY.data.oppRevenue | text (+kw) |
| eventData.VISIT_SUMMARY.data.primaryOppId | text (+kw) |
| eventData.VISIT_SUMMARY.data.secondaryOppId | text (+kw) |

### Create Request (eventData.CREATE_REQUEST.data.*)
| Field | Type |
|-------|------|
| eventData.CREATE_REQUEST.data.customerName | text (+kw) |
| eventData.CREATE_REQUEST.data.meetingType | text (+kw) |
| eventData.CREATE_REQUEST.data.visitType | text (+kw) |
| eventData.CREATE_REQUEST.data.briefingManager | text (+kw) |
| eventData.CREATE_REQUEST.data.noOfAttendees | long |
| eventData.CREATE_REQUEST.data.duration | long |
| eventData.CREATE_REQUEST.data.opportunity | text (+kw) |
| eventData.CREATE_REQUEST.data.secondaryOpportunity | text (+kw) |
| eventData.CREATE_REQUEST.data.region | text (+kw) |
| eventData.CREATE_REQUEST.data.accountId | text (+kw) |

### Virtual Connection (eventData.VIRTUAL_CONNECTION.data.*)
Virtual/hybrid meeting setup.
| Field | Type |
|-------|------|
| eventData.VIRTUAL_CONNECTION.data.meetingPlatForm | text (+kw) |
| eventData.VIRTUAL_CONNECTION.data.bridge | text (+kw) |
| eventData.VIRTUAL_CONNECTION.data.bridgePlatform | text (+kw) |
| eventData.VIRTUAL_CONNECTION.data.joinUrl | text (+kw) |
| eventData.VIRTUAL_CONNECTION.data.hostUrl | text (+kw) |
| eventData.VIRTUAL_CONNECTION.data.meetingId | text (+kw) |
| eventData.VIRTUAL_CONNECTION.data.expectedNoOfAttendees | long |
| eventData.VIRTUAL_CONNECTION.data.noOfPanelists | long |

### Catering (eventData.CATERING.data.*)
| Field | Type |
|-------|------|
| eventData.CATERING.data.cateringType | text (+kw) |
| eventData.CATERING.data.dietaryRestrictions | text (+kw) |
| eventData.CATERING.data.noOfAttendees | long |
| eventData.CATERING.data.notes | text (+kw) |

### Documents (eventData.DOCUMENT.data.*)
| Field | Type |
|-------|------|
| eventData.DOCUMENT.data.documentName | text (+kw) |
| eventData.DOCUMENT.data.documentType | text (+kw) |
| eventData.DOCUMENT.data.fileName | text (+kw) |
| eventData.DOCUMENT.data.fileType | text (+kw) |
| eventData.DOCUMENT.data.fileSize | text (+kw) |
| eventData.DOCUMENT.data.uploadedAt | text (+kw) |
| eventData.DOCUMENT.data.comments | text (+kw) |

### Activity Days (activityDays.*)
Each event has activityDays → activities (sessions/slots).
| Field | Type | Notes |
|-------|------|-------|
| activityDays.eventDateId | text (+kw) | Day identifier |
| activityDays.eventDate.utcMs | long | Day start epoch ms |
| activityDays.eventStartTime.utcMs | long | |
| activityDays.eventEndTime.utcMs | long | |
| activityDays.eventId | text (+kw) | |
| activityDays.activities.activityId | text (+kw) | Session ID |
| activityDays.activities.eventId | text (+kw) | |
| activityDays.activities.duration | long | Minutes |
| activityDays.activities.startTime.utcMs | long | Session start |
| activityDays.activities.endTime.utcMs | long | Session end |
| activityDays.activities.status.stateName | text (+kw) | |
| activityDays.activities.resourceId | text (+kw) | Room/resource ID |
| activityDays.activities.resource.data.name | text (+kw) | Room/resource name |
| activityDays.activities.resource.data.capacity | long | Room capacity |
| activityDays.activities.activityInfo.topic.data.topic.textField1 | text (+kw) | **Topic name** |
| activityDays.activities.activityInfo.topic_presenter.data.presenter.firstName | text (+kw) | Presenter first name |
| activityDays.activities.activityInfo.topic_presenter.data.presenter.lastName | text (+kw) | Presenter last name |
| activityDays.activities.activityInfo.topic_presenter.data.presenter.designation | text (+kw) | Presenter title |
| activityDays.activities.activityInfo.topic_presenter.data.presenterEmail | text (+kw) | Presenter email |
| activityDays.activities.activityInfo.topic_presenter.data.presenterStatus | text (+kw) | |
| activityDays.activities.activityInfo.CATERING.data.cateringType | text (+kw) | |
| activityDays.activities.activityInfo.CATERING.data.noOfAttendees | long | |

---

## OpenSearch Index: activities (2,329 docs)

Each document is ONE activity/session. Use this index for **per-activity questions** (topics, room utilization, presenter lookups, catering per session). Links to parent event via `eventId`.

### Activity Core
| Field | Type | Notes |
|-------|------|-------|
| activityId | text (+kw) | Unique activity ID |
| eventId | text (+kw) | **Parent event ID** — join back to events index |
| duration | long | Minutes |
| startTime.utcMs | long | Activity start (epoch ms) |
| endTime.utcMs | long | Activity end (epoch ms) |
| activityDate.utcMs | long | Activity date (epoch ms) |
| activityDayId | text (+kw) | Day grouping ID |
| createdBy | text (+kw) | |
| recurrence | boolean | |
| sendInvite | boolean | |
| bookingId | text (+kw) | |

### Activity Status
| Field | Type |
|-------|------|
| status.stateName | text (+kw) |
| status.stateCode | text (+kw) |
| status.displayText | text (+kw) |

### Resource / Room (resource.data.*)
| Field | Type |
|-------|------|
| resource.data.name | text (+kw) |
| resource.data.capacity | long |
| resource.data.baseTimezone | text (+kw) |
| resource.data.isActive | boolean |
| resource.uniqueId | text (+kw) |
| resource.resourceType.name | text (+kw) |

### Topic (activityInfo.topic.data.topic.*)
| Field | Type | Notes |
|-------|------|-------|
| activityInfo.topic.data.topic.textField1 | text (+kw) | **Topic name** |
| activityInfo.topic.data.topic.textField2 | text (+kw) | Topic description |
| activityInfo.topic.data.topic.uniqueId | text (+kw) | Topic ID |
| activityInfo.topic.status.stateName | text (+kw) | Topic status |

### Presenter (activityInfo.topic_presenter.data.*)
| Field | Type | Notes |
|-------|------|-------|
| activityInfo.topic_presenter.data.presenter.firstName | text (+kw) | |
| activityInfo.topic_presenter.data.presenter.lastName | text (+kw) | |
| activityInfo.topic_presenter.data.presenter.presenterName | text (+kw) | Full name |
| activityInfo.topic_presenter.data.presenter.primaryEmail | text (+kw) | |
| activityInfo.topic_presenter.data.presenter.designation | text (+kw) | Title |
| activityInfo.topic_presenter.data.presenterStatus | text (+kw) | Confirmed/Pending |
| activityInfo.topic_presenter.data.presenterEmail | text (+kw) | |
| activityInfo.topic_presenter.data.presenterTitle | text (+kw) | |

### Presenter Events (activityInfo.PRESENTER_EVENTS.data.*)
Alternative presenter path — same structure as topic_presenter.
| Field | Type |
|-------|------|
| activityInfo.PRESENTER_EVENTS.data.presenter.firstName | text (+kw) |
| activityInfo.PRESENTER_EVENTS.data.presenter.lastName | text (+kw) |
| activityInfo.PRESENTER_EVENTS.data.presenter.primaryEmail | text (+kw) |
| activityInfo.PRESENTER_EVENTS.data.presenter.designation | text (+kw) |
| activityInfo.PRESENTER_EVENTS.data.presenterStatus | text (+kw) |

### Visit Info per Activity (activityInfo.EVENTS_VISIT_INFO.data.*)
⚠️ Always use full dotted path, e.g. `activityInfo.EVENTS_VISIT_INFO.data.customerName`
| Field | Type |
|-------|------|
| activityInfo.EVENTS_VISIT_INFO.data.customerName | text (+kw) |
| activityInfo.EVENTS_VISIT_INFO.data.industry | text (+kw) |
| activityInfo.EVENTS_VISIT_INFO.data.lineOfBusiness | text (+kw) |
| activityInfo.EVENTS_VISIT_INFO.data.region | text (+kw) |
| activityInfo.EVENTS_VISIT_INFO.data.country | text (+kw) |
| activityInfo.EVENTS_VISIT_INFO.data.meetingType | text (+kw) |
| activityInfo.EVENTS_VISIT_INFO.data.meetingFocus | text (+kw) |
| activityInfo.EVENTS_VISIT_INFO.data.meetingDetails | text (+kw) |
| activityInfo.EVENTS_VISIT_INFO.data.numberOfAttendees | long |
| activityInfo.EVENTS_VISIT_INFO.data.salesRepFirstName | text (+kw) |
| activityInfo.EVENTS_VISIT_INFO.data.salesRepLastName | text (+kw) |
| activityInfo.EVENTS_VISIT_INFO.data.salesRepEmail | text (+kw) |
| activityInfo.EVENTS_VISIT_INFO.data.tier | text (+kw) |
| activityInfo.EVENTS_VISIT_INFO.data.isCLevelAttendee | boolean |

### Catering (activityInfo.CATERING.data.*)
| Field | Type |
|-------|------|
| activityInfo.CATERING.data.cateringType | text (+kw) |
| activityInfo.CATERING.data.dietaryRestrictions | text (+kw) |
| activityInfo.CATERING.data.noOfAttendees | long |
| activityInfo.CATERING.data.notes | text (+kw) |

---

## Query Rules (both indices)
- **Filters, sort, aggs** → append `.keyword` (e.g. `status.stateName.keyword`)
- **_source paths** → NO `.keyword` (e.g. `eventData.VISIT_INFO.data.customerName`)
- **startTime** on events index → epoch milliseconds (long). On activities index → use `startTime.utcMs`.
- **Date ranges** → include `"format": "epoch_millis"` in range clause
- **Forbidden** → `script`, `script_fields`, `scripted_metric`, `runtime_mappings`
- **NO nested queries** → All fields are plain object/array types, NOT nested type. Use `exists`, `term`, `match` directly on the dotted path.
- **Size cap** → max 50 per request. Use `size: 0` + aggs for counts/breakdowns.
- **text (+kw)** means field has both `text` type (for full-text match) and `.keyword` subfield (for exact match / aggs)
- **Location filtering** → always prefer `location.data.locationName` over `location.data.city` — city stores abbreviated names

## Index Selection Guide
- **Event-level questions** (attendees, opportunities, status, location, category) → use `events` index
- **Activity-level questions** (topics, presenter lookups, room assignments, catering per session, per-activity scheduling) → use `activities` index with `index: "activities"`
- **Cross-reference** → query activities index, use `eventId` to look up parent event details from events index if needed
""".strip()
