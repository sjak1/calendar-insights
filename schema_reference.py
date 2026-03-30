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

Known stateName values: Initialized, Submitted, Confirmed, Hold, Waitlist, Checked In

### Category & Type
| Field | Type |
|-------|------|
| category.categoryName | text (+kw) |
| category.uniqueId | text (+kw) |
| categoryType.categoryTypeName | text (+kw) |

### Location (location.data.*)
| Field | Type |
|-------|------|
| location.data.locationName | text (+kw) |
| location.data.city | text (+kw) |
| location.data.state | text (+kw) |
| location.data.country | text (+kw) |
| location.data.baseTimezone | text (+kw) |
| location.data.addressLine1 | text (+kw) |
| location.data.zipCode | text (+kw) |
| location.data.primaryEmail | text (+kw) |

### Visit Info (eventData.VISIT_INFO.data.*)
Core briefing/meeting metadata — the richest event-level section.
| Field | Type | Business meaning |
|-------|------|-----------------|
| customerName | text (+kw) | Customer / company name |
| companyName | text (+kw) | Alternate company field |
| companyWebsite | text (+kw) | |
| customerIndustry | text (+kw) | Industry vertical |
| lineOfBusiness | text (+kw) | LOB |
| region | text (+kw) | Geographic region |
| country | text (+kw) | |
| briefingManager | text (+kw) | Assigned briefing manager |
| technicalManager | text (+kw) | |
| backUpTechnicalManager | text (+kw) | |
| meetingObjective | text (+kw) | Why the meeting exists |
| visitFocus | text (+kw) | Focus area |
| visitType | text (+kw) | Visit classification |
| oracleHostName | text (+kw) | Host name |
| oracleHostEmail | text (+kw) | Host email |
| oracleHostBusinessTitle | text (+kw) | Host title |
| requesterEmail | text (+kw) | Who requested |
| organization | text (+kw) | |
| pillars | text (+kw) | Strategic pillar |
| program | text (+kw) | Program name |
| salesPlay | text (+kw) | Sales play |
| accountId | text (+kw) | CRM account ID |
| costCenter | text (+kw) | |
| isStrategicClient | boolean | |
| isComplaint | text (+kw) | |

### External Attendees (eventData.EXTERNAL_ATTENDEES.data.*)
Array of customer-side attendees.
| Field | Type | Business meaning |
|-------|------|-----------------|
| attendeeName | text (+kw) | Full name |
| firstName | text (+kw) | |
| lastName | text (+kw) | |
| businessTitle | text (+kw) | Job title |
| chiefOfficerTitle | text (+kw) | C-level title if any |
| company | text (+kw) | Company name |
| email | text (+kw) | |
| decisionMaker | boolean | Is a decision-maker? |
| influencer | boolean | Is an influencer? |
| isTechnical | boolean | Technical attendee? |
| isRemote | boolean | Attending remotely? |
| translator | boolean | |

### Internal Attendees (eventData.INTERNAL_ATTENDEES.data.*)
Array of host-side attendees.
| Field | Type |
|-------|------|
| firstName | text (+kw) |
| lastName | text (+kw) |
| businessTitle | text (+kw) |
| company | text (+kw) |
| email | text (+kw) |
| isRemote | boolean |

### Opportunity (eventData.Opportunity.data.*)
Revenue / pipeline linked to event.
| Field | Type | Business meaning |
|-------|------|-----------------|
| opportunity | text (+kw) | Opportunity name / ID |
| oppStatus | text (+kw) | Known values: Open, In Progress, Pending, On Hold, Closed Won, Closed Lost |
| opportunityRevenue | float | Current revenue |
| initialOpportunityRevenue | float | Starting revenue |
| closedOpportunityRevenue | float | Revenue at close |
| probabilityOfClose | text (+kw) | % likelihood |
| quarterOfClose | text (+kw) | Target quarter |
| isPrimary | boolean | Primary opportunity? |
| decimalField1 | float | Additional numeric |
| decimalField2 | float | Additional numeric |

### Visit Summary (eventData.VISIT_SUMMARY.data.*)
Post-visit wrap-up.
| Field | Type |
|-------|------|
| summary | text (+kw) |
| customerVisitObjective | text (+kw) |
| desiredOutcome | text (+kw) |
| businessCase | text (+kw) |
| competitors | text (+kw) |
| customerInitiative | text (+kw) |
| anySensitiveIssues | text (+kw) |
| closedRevenue | long |
| oppRevenue | text (+kw) |
| primaryOppId | text (+kw) |
| secondaryOppId | text (+kw) |

### Create Request (eventData.CREATE_REQUEST.data.*)
Initial request metadata.
| Field | Type |
|-------|------|
| customerName | text (+kw) |
| meetingType | text (+kw) |
| visitType | text (+kw) |
| briefingManager | text (+kw) |
| noOfAttendees | long |
| duration | long |
| opportunity | text (+kw) |
| secondaryOpportunity | text (+kw) |
| region | text (+kw) |
| accountId | text (+kw) |

### Virtual Connection (eventData.VIRTUAL_CONNECTION.data.*)
Virtual/hybrid meeting setup.
| Field | Type |
|-------|------|
| meetingPlatform | text (+kw) |
| bridge | text (+kw) |
| bridgePlatform | text (+kw) |
| joinUrl | text (+kw) |
| hostUrl | text (+kw) |
| meetingId | text (+kw) |
| expectedNoOfAttendees | long |
| noOfPanelists | long |
| room | text (+kw) |
| webinar | text (+kw) |
| webinarPlatform | text (+kw) |

### Catering (eventData.CATERING.data.*)
| Field | Type |
|-------|------|
| cateringType | text (+kw) |
| dietaryRestrictions | text (+kw) |
| noOfAttendees | long |
| notes | text (+kw) |

### Documents (eventData.DOCUMENT.data.*)
| Field | Type |
|-------|------|
| documentName | text (+kw) |
| documentType | text (+kw) |
| fileName | text (+kw) |
| fileType | text (+kw) |
| fileSize | text (+kw) |
| uploadedAt | text (+kw) |
| comments | text (+kw) |

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
| activityDays.activities.activityInfo.topic_presenter.data.presenter.email | text (+kw) | Presenter email |
| activityDays.activities.activityInfo.topic_presenter.data.presenterStatus | text (+kw) | Confirmed/pending |
| activityDays.activities.activityInfo.CATERING.data.cateringType | text (+kw) | |
| activityDays.activities.activityInfo.CATERING.data.noOfAttendees | long | |

---

## OpenSearch Index: activities (2,329 docs)

Each document is ONE activity/session. Use this index for **per-activity questions** (topics without speakers, room utilization, presenter lookups, catering per session). Links to parent event via `eventId`.

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
| Field | Type |
|-------|------|
| customerName | text (+kw) |
| industry | text (+kw) |
| lineOfBusiness | text (+kw) |
| region | text (+kw) |
| country | text (+kw) |
| meetingType | text (+kw) |
| meetingFocus | text (+kw) |
| meetingDetails | text (+kw) |
| numberOfAttendees | long |
| salesRepFirstName | text (+kw) |
| salesRepLastName | text (+kw) |
| salesRepEmail | text (+kw) |
| tier | text (+kw) |
| isCLevelAttendee | boolean |

### Catering (activityInfo.CATERING.data.*)
| Field | Type |
|-------|------|
| cateringType | text (+kw) |
| dietaryRestrictions | text (+kw) |
| noOfAttendees | long |
| notes | text (+kw) |

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

## Index Selection Guide
- **Event-level questions** (attendees, opportunities, status, location, category) → use `events` index
- **Activity-level questions** (topics without speakers, presenter lookups, room assignments, catering per session, per-activity scheduling) → use `activities` index with `index: "activities"`
- **Cross-reference** → query activities index, use `eventId` to look up parent event details from events index if needed
""".strip()
