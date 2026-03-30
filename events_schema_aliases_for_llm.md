# OpenSearch events index — flattened schema for LLM (aliases only)

Use only these fields. Never invent paths. In DSL, use the **path** (right side).

## FIELD TYPES

| type    | use for |
|---------|--------|
| keyword | exact match filter (term, terms), aggregations, sort |
| text    | full-text search (match, match_phrase) |
| date    | range queries (range with gte/lte) |
| long    | numeric filters, aggregations |
| boolean | true/false filter |

---

## ACTIVITY FIELDS (activites.*)

| alias | path | type |
|-------|------|------|
| event_id | activites.eventId.keyword | keyword |
| activity_id | activites.activityId.keyword | keyword |
| activity_day_id | activites.activityDayId.keyword | keyword |
| activity_status | activites.status.stateName.keyword | keyword |
| activity_status_code | activites.status.stateCode.keyword | keyword |
| start_time | activites.startTime.client.clientZoneDate | date |
| end_time | activites.endTime.client.clientZoneDate | date |
| duration | activites.duration | long |
| recurrence | activites.recurrence | boolean |
| resource_id | activites.resourceId.keyword | keyword |
| resource_name | activites.resource.data.name.keyword | keyword |
| resource_capacity | activites.resource.data.capacity | long |
| resource_tags | activites.resource.data.tags.keyword | keyword |
| presenter_name | activites.activityInfo.topic_presenter.data.presenter.presenterName.keyword | keyword |
| presenter_email | activites.activityInfo.topic_presenter.data.presenter.primaryEmail.keyword | keyword |
| presenter_first_name | activites.activityInfo.topic_presenter.data.presenter.firstName.keyword | keyword |
| presenter_last_name | activites.activityInfo.topic_presenter.data.presenter.lastName.keyword | keyword |
| presenter_status | activites.activityInfo.topic_presenter.data.presenterStatus.keyword | keyword |
| topic_name | activites.activityInfo.topic.data.topic.textField1.keyword | keyword |
| topic_description | activites.activityInfo.topic.data.topic.textField2 | text |
| catering_type | activites.activityInfo.CATERING.data.cateringType.keyword | keyword |
| attendees | activites.activityInfo.CATERING.data.noOfAttendees | long |

---

## EVENT-LEVEL FIELDS (for event-level queries)

| alias | path | type |
|-------|------|------|
| event_name | eventName.keyword | keyword |
| event_id_top | eventId.keyword | keyword |
| status | status.stateName.keyword | keyword |
| category_name | category.categoryName.keyword | keyword |
| location_name | location.data.locationName.keyword | keyword |
| location_country | location.data.country.keyword | keyword |
| event_start_time | startTime | long |
| event_duration_days | duration | long |
| timezone | timezone | keyword |
| is_active | isActive | boolean |
| line_of_business | eventData.VISIT_INFO.data.lineOfBusiness.keyword | keyword |
| region | eventData.VISIT_INFO.data.region.keyword | keyword |
| customer_industry | eventData.VISIT_INFO.data.customerIndustry.keyword | keyword |
| visit_focus | eventData.VISIT_INFO.data.visitFocus.keyword | keyword |
| sales_play | eventData.VISIT_INFO.data.salesPlay.keyword | keyword |
| customer_name | eventData.VISIT_INFO.data.customerName.keyword | keyword |
| opportunity_revenue | eventData.Opportunity.data.opportunityRevenue | long |
| external_attendee_last_name | eventData.EXTERNAL_ATTENDEES.data.lastName | text |

Note: event_start_time is epoch ms (long). For "today" / date ranges use script filter or range with epoch ms. Do not use date strings for startTime.
