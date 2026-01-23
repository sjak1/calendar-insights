# EBC AI Agenda Generator - Sample Data & Input/Output Examples

## Sample Data for Each Available Field

### 1. **Company Profile & Industry Vertical**

**Field: `VW_OPERATIONS_REPORT.CUSTOMERNAME`**

```
1. HCL Technologies
2. HP
3. Lockheed Martin
4. Ford Motor
5. PayPal
6. Salesforce
7. Audi
8. AllianceIT
```

**Field: `VW_OPERATIONS_REPORT.CUSTOMERINDUSTRY`**

```
1. Retail
2. Health Care
3. Construction & Engineering
4. Insurance
5. Oil and Gas
6. Natural Resources
7. Media & Entertainment
8. Financial Services
9. Healthcare
10. Travel & Transportation
```

**Field: `VW_OPERATIONS_REPORT.ACCOUNTTYPE`**

```
1. Analyst||Current Customer
2. ["Global 500"]
3. ["Lead Account","Customer - Channel","Partner | EVP meetings"]
4. ["New Business Prospect","Customer - Direct"]
5. ["Leaders Circle | Executive Summit","Partner | EVP meetings","Entreprise"]
6. ["Prospect"]
```

**Field: `VW_OPERATIONS_REPORT.LINEOFBUSINESS`**

```
1. LAD
2. GBU - Oracle Health
3. N/A
4. EMEA
5. GBU - other
```

---

### 2. **Meeting Objectives**

**Field: `VW_OPERATIONS_REPORT.MEETINGOBJECTIVE`**

```
1. HP meeting objective
2. Ford Motor meeting objective
3. Salesforce meeting objective
4. HCL Technologies meeting objective
5. Lockheed Martin meeting objective
6. PayPal meeting objective
```

**Note**: These appear to be placeholder values. Actual detailed objectives may be stored elsewhere or need to be captured during request intake.

---

### 3. **EBD (Executive Briefing Document) Details**

**Field: `t_request_agenda_details.is_ebd_included`**

```
MISSING - No data found (all NULL values in sample)
```

**Status**: ⚠️ Field exists in schema but contains no data. EBD content location needs verification.

---

### 4. **Visit Focus**

**Field: `VW_OPERATIONS_REPORT.VISITFOCUS`**

```
1. Corporate Strategy
2. Oracle Playbook (formerly O@O)
3. OCI Topics only - CEC Request
4. Internet of Things
5. Hardware
6. Consulting
7. Customer Success Services (CSS)
8. Analytics
```

---

### 5. **Sales Plays**

**Field: `VW_OPERATIONS_REPORT.SALESPLAY`**

```
1. Other - Siebel to CX Cloud
2. ["Revenue Transformation","Marketing and Sales Unification"]
3. ["Service Automation","Other - Siebel to CX Cloud","Marketing and Sales Unification"]
4. ["Revenue Transformation","Other - Siebel to CX Cloud","Service Automation"]
5. ["Service Automation"]
6. ["Revenue Transformation","Service Automation"]
7. ["Marketing and Sales Unification","Other - Siebel to CX Cloud"]
```

**Note**: Can be single string or JSON array format. Parsing logic required.

---

### 6. **Strategic Themes/Pillars**

**Field: `VW_OPERATIONS_REPORT.PILLARS`**

```
1. ["GIU - Retail","Apps - Customer Experience"]
2. Apps - Financial Excellence
3. ["Apps - Empowered Workforce","GIU - Food & Beverage"]
4. ["Apps - Financial Excellence"]
5. ["GIU - Food & Beverage","GIU - Health Sciences"]
6. ["Tech - AI and Application Innovation","Compete","GIU - Financial Services"]
7. ["GIU - Food & Beverage"]
8. ["Tech - AI and Application Innovation"]
```

**Note**: Can be single string or JSON array format. Parsing logic required.

---

### 7. **Attendee Title Levels & Mix**

**Field: `VW_ATTENDEE_REPORT.BUSINESSTITLE`**

```
1. Data Scientist
2. Senior Sales Manager
3. Business Analyst
4. Senior Software Engineer
5. Enterprise Architect
6. Technical Architect
7. Program Manager
8. Customer Success Manager
9. Senior Product Manager
10. Product Manager
11. Principal Engineer
12. Senior Data Analyst
13. IT Business Analyst
14. Machine Learning Engineer
15. Product Owner
16. Lead Software Engineer
```

**Field: `VW_ATTENDEE_REPORT.CHIEFOFFICERTITLE`**

```
1. None (most common)
2. COO - Chief Operating Officer
3. CMO - Chief Marketing Officer
4. CRO - Chief Risk Officer
5. CISO - Chief Information Security Officer
6. CHRO - Chief Human Resources Officer
7. Chief Administrative Officer
8. Chief Architect
9. Chief Data Officer
```

**Field: `VW_ATTENDEE_REPORT.DECISIONMAKER`**

```
1. Yes
2. No
```

**Field: `VW_ATTENDEE_REPORT.INFLUENCER`**

```
1. Yes
2. No
```

**Field: `VW_ATTENDEE_REPORT.ISTECHNICAL`**

```
1. Yes
2. No
```

**Field: `VW_ATTENDEE_REPORT.ATTENDEETYPE`**

```
1. Internal
2. External
```

**Field: `VW_ATTENDEE_REPORT.ISREMOTE`**

```
1. Yes (Remote)
2. No (In-Person)
```

---

### 8. **Previous Meetings for Same Company**

**Example: HP (10 total meetings)**

```
Meeting 1:
  Event ID: 731318038271
  Date: 2026-01-22
  Visit Focus: Hardware
  Sales Play: ["Revenue Transformation","Marketing and Sales Unification"]
  Pillars: ["GIU - Retail","Apps - Customer Experience"]
  Objective: HP meeting objective

Meeting 2:
  Event ID: 731318038424
  Date: 2025-12-17
  Visit Focus: Customer Success Services (CSS)
  Sales Play: ["Service Automation"]
  Pillars: ["Tech - AI and Application Innovation"]
  Objective: HP meeting objective
```

**Companies with Multiple Meetings:**

```
1. Audi: 22 meetings (Dec 2026)
2. AllianceIT: 13 meetings (Dec 2025 - Dec 2026)
3. Salesforce: 12 meetings (Dec 2025)
4. HP: 10 meetings (Dec 2025 - Jan 2026)
5. Ford Motor: 9 meetings (Dec 2025 - Dec 2026)
```

---

### 9. **Historical Agenda Items**

**Field: `t_request_agenda.text_field_2`**

```
MISSING - Limited data found. Most values are NULL or contain minimal text (e.g., "Ms", "Mr")
```

**Status**: ⚠️ Agenda structure data appears to be stored differently or in other fields. May need to check:

- `t_request_agenda` other fields
- `t_request_agenda_details` custom fields
- External agenda management system

---

## Complete Input Example

### **Input: EBC Engagement Request for HP**

```json
{
  "event_id": "731318038271",
  "customer_profile": {
    "company_name": "HP",
    "industry": "Health Care",
    "account_type": ["Global 500"],
    "line_of_business": "LAD"
  },
  "meeting_details": {
    "meeting_objective": "HP meeting objective",
    "visit_focus": "Hardware",
    "form_type": "Redwood Visit Information",
    "is_ebd_included": null
  },
  "sales_strategy": {
    "sales_plays": [
      "Revenue Transformation",
      "Marketing and Sales Unification"
    ],
    "pillars": ["GIU - Retail", "Apps - Customer Experience"]
  },
  "attendees": [
    {
      "name": "Stella Green",
      "title": "Program Manager",
      "c_level": null,
      "decision_maker": false,
      "influencer": false,
      "technical": false,
      "type": "Internal",
      "remote": true
    },
    {
      "name": "Toni Ortiz",
      "title": "Machine Learning Engineer",
      "c_level": null,
      "decision_maker": false,
      "influencer": false,
      "technical": false,
      "type": "Internal",
      "remote": false
    },
    {
      "name": "Sarah Silva",
      "title": "Senior Software Engineer",
      "c_level": "Chief Architect",
      "decision_maker": false,
      "influencer": true,
      "technical": true,
      "type": "External",
      "remote": true
    },
    {
      "name": "Brennan Hamilton",
      "title": "Lead Software Engineer",
      "c_level": "Chief Data Officer",
      "decision_maker": true,
      "influencer": false,
      "technical": true,
      "type": "External",
      "remote": false
    }
  ],
  "previous_meetings": [
    {
      "event_id": "731318038271",
      "date": "2026-01-22",
      "visit_focus": "Hardware",
      "sales_plays": [
        "Revenue Transformation",
        "Marketing and Sales Unification"
      ],
      "pillars": ["GIU - Retail", "Apps - Customer Experience"]
    },
    {
      "event_id": "731318038424",
      "date": "2025-12-17",
      "visit_focus": "Customer Success Services (CSS)",
      "sales_plays": ["Service Automation"],
      "pillars": ["Tech - AI and Application Innovation"]
    }
  ],
  "similar_briefings": [
    {
      "company": "Lockheed Martin",
      "industry": "Retail",
      "visit_focus": "Corporate Strategy",
      "sales_plays": ["Revenue Transformation", "Service Automation"],
      "pillars": ["Apps - Empowered Workforce", "GIU - Food & Beverage"]
    }
  ]
}
```

---

## Expected Output: AI-Generated Agenda

Based on the problem statement requirements, the AI should generate a **sample agenda** that is:

1. **Tailored to the customer's company profile and industry vertical**
2. **Aligned with meeting objectives and EBD details** (if available)
3. **Incorporates selected sales plays and strategic themes**
4. **Appropriate for the title level and mix of attendees**
5. **Based on proven agenda recommendations from similar briefings**

### **Expected Output: Sample Agenda for HP**

```
═══════════════════════════════════════════════════════════════════════════════
EXECUTIVE BRIEFING CENTER - SAMPLE AGENDA
Company: HP | Industry: Health Care | Visit Focus: Hardware
Sales Plays: Revenue Transformation, Marketing and Sales Unification
Strategic Pillars: GIU - Retail, Apps - Customer Experience
═══════════════════════════════════════════════════════════════════════════════

EVENT: HP Executive Briefing
DATE: [To be scheduled]
LOCATION: Oracle Executive Briefing Center
FORMAT: Hybrid (Mix of In-Person and Remote attendees)

═══════════════════════════════════════════════════════════════════════════════
AGENDA OVERVIEW
═══════════════════════════════════════════════════════════════════════════════

This agenda is tailored for HP's Health Care industry focus, Hardware visit
focus, and includes sessions aligned with Revenue Transformation and Marketing
and Sales Unification sales plays. The agenda is designed for a mix of C-level
executives (Chief Architect, Chief Data Officer), technical leaders, and
business stakeholders.

═══════════════════════════════════════════════════════════════════════════════
DAY 1 - AGENDA
═══════════════════════════════════════════════════════════════════════════════

08:00 AM - 08:30 AM    Welcome & Registration
                       [Location: Executive Lobby]
                       - Coffee and networking
                       - Badge pickup
                       - Technology setup for remote participants

08:30 AM - 09:00 AM    Opening Session: Oracle Vision & Strategy
                       [Location: Main Briefing Room]
                       [Presenter: Oracle Executive Sponsor]
                       - Oracle's commitment to Health Care industry
                       - Overview of today's agenda
                       - Introduction of Oracle team

09:00 AM - 10:30 AM    Session 1: Revenue Transformation in Health Care
                       [Location: Main Briefing Room]
                       [Focus: Revenue Transformation Sales Play]
                       [Pillar: Apps - Customer Experience]
                       - Transforming revenue operations with Oracle Cloud
                       - Customer success stories in Health Care
                       - Q&A with Chief Data Officer and technical team
                       [Interactive: Live demo and use cases]

10:30 AM - 10:45 AM    Break
                       [Location: Executive Lounge]
                       - Refreshments
                       - Networking opportunity

10:45 AM - 12:00 PM    Session 2: Marketing and Sales Unification
                       [Location: Main Briefing Room]
                       [Focus: Marketing and Sales Unification Sales Play]
                       [Pillar: GIU - Retail, Apps - Customer Experience]
                       - Unified marketing and sales platforms
                       - Customer journey optimization
                       - Integration with existing systems
                       [Interactive: Hands-on workshop]

12:00 PM - 01:00 PM    Executive Lunch
                       [Location: Executive Dining Room]
                       - Networking lunch with Oracle leadership
                       - Discussion of strategic priorities
                       [Dietary: Accommodations available upon request]

01:00 PM - 02:30 PM    Session 3: Hardware Solutions & Infrastructure
                       [Location: Technology Showcase Room]
                       [Focus: Hardware Visit Focus]
                       - Oracle hardware portfolio for Health Care
                       - Infrastructure modernization strategies
                       - Performance and scalability demonstrations
                       [Technical deep-dive for Chief Architect and technical team]

02:30 PM - 02:45 PM    Break
                       [Location: Executive Lounge]

02:45 PM - 04:00 PM    Session 4: Customer Experience Excellence
                       [Location: Main Briefing Room]
                       [Pillar: Apps - Customer Experience]
                       - Building exceptional patient and customer experiences
                       - Digital transformation in Health Care
                       - Best practices and case studies
                       [Interactive: Panel discussion]

04:00 PM - 04:30 PM    Closing Session: Next Steps & Action Items
                       [Location: Main Briefing Room]
                       - Summary of key takeaways
                       - Proposed next steps
                       - Q&A with all attendees
                       - Feedback collection

04:30 PM - 05:30 PM    Networking Reception (Optional)
                       [Location: Executive Lounge]
                       - Cocktails and hors d'oeuvres
                       - Continued discussions
                       - Relationship building

═══════════════════════════════════════════════════════════════════════════════
AGENDA CUSTOMIZATION NOTES
═══════════════════════════════════════════════════════════════════════════════

Based on Similar Briefings:
- Similar meetings in Health Care industry typically include hands-on
  workshops for technical attendees
- C-level executives (Chief Architect, Chief Data Officer) benefit from
  strategic overview sessions in the morning
- Technical deep-dives scheduled in afternoon when executives have flexibility

Attendee Mix Considerations:
- Hybrid format accommodates both in-person (Brennan Hamilton) and remote
  (Stella Green, Sarah Silva) attendees
- Technical sessions tailored for Chief Architect and Chief Data Officer
- Business sessions appropriate for Program Manager and Senior Software Engineers

Previous HP Meetings:
- HP has had 10 previous briefings, most recently focused on Hardware and
  Customer Success Services
- This agenda builds on previous Revenue Transformation discussions
- Incorporates learnings from past HP engagements

═══════════════════════════════════════════════════════════════════════════════
RECOMMENDED PRESENTERS (Based on Similar Briefings)
═══════════════════════════════════════════════════════════════════════════════

- Oracle Health Care Industry Expert
- Revenue Transformation Solution Architect
- Marketing & Sales Unification Specialist
- Hardware Solutions Engineer
- Customer Experience Strategist

═══════════════════════════════════════════════════════════════════════════════
LOGISTICS & SPECIAL REQUIREMENTS
═══════════════════════════════════════════════════════════════════════════════

- Remote participation technology setup required
- Executive dining room reserved for lunch
- Technology showcase room for hardware demonstrations
- Dietary restrictions: [To be confirmed]
- Parking and security arrangements: [To be confirmed]

═══════════════════════════════════════════════════════════════════════════════
NEXT STEPS
═══════════════════════════════════════════════════════════════════════════════

1. EBC Manager to review and refine this agenda
2. Confirm presenter availability
3. Finalize logistics and special requirements
4. Send agenda to HP for review and approval
5. Schedule follow-up meeting to discuss customization needs

═══════════════════════════════════════════════════════════════════════════════
```

---

## Key Features of Expected Output

### ✅ **Tailored to Customer Profile**

- References HP's Health Care industry
- Acknowledges Global 500 account status
- Mentions LAD line of business

### ✅ **Aligned with Meeting Objectives**

- Incorporates "HP meeting objective" context
- Sessions designed to address stated objectives

### ✅ **Incorporates Sales Plays**

- **Revenue Transformation** → Dedicated session (Session 1)
- **Marketing and Sales Unification** → Dedicated session (Session 2)
- Both plays integrated throughout agenda

### ✅ **Reflects Strategic Pillars**

- **GIU - Retail** → Referenced in Session 2
- **Apps - Customer Experience** → Dedicated session (Session 4) and referenced throughout

### ✅ **Appropriate for Attendee Mix**

- C-level executives (Chief Architect, Chief Data Officer) → Strategic morning sessions
- Technical attendees → Afternoon deep-dive sessions
- Hybrid format → Accommodates both in-person and remote participants
- Mix of business and technical content

### ✅ **Based on Similar Briefings**

- References similar Health Care industry meetings
- Incorporates learnings from HP's 10 previous briefings
- Uses proven agenda patterns from similar companies

### ✅ **Visit Focus Integration**

- **Hardware** → Dedicated session (Session 3: Hardware Solutions & Infrastructure)

---

## Missing Data & Recommendations

### ❌ **EBD Content**

- **Status**: Not available in database
- **Impact**: Agenda cannot incorporate specific EBD details
- **Recommendation**:
  - Check if EBD content is in custom fields (`text_area_field_X`)
  - Integrate with external EBD document management system
  - Capture EBD details during request intake if not stored

### ❌ **Historical Agenda Items**

- **Status**: Limited data in `t_request_agenda.text_field_2`
- **Impact**: Cannot directly reference past agenda structures
- **Recommendation**:
  - Query other agenda-related fields
  - Build agenda pattern library from meeting descriptions
  - Use similar meeting contexts to infer agenda structures

### ⚠️ **Meeting Objectives**

- **Status**: Placeholder values ("HP meeting objective")
- **Impact**: Generic objectives limit personalization
- **Recommendation**:
  - Enhance objective capture during request intake
  - Link to detailed EBD if available
  - Use industry + visit focus + sales play to infer objectives

---

## Implementation Notes

1. **JSON Array Parsing**: Sales plays and pillars may be JSON arrays - implement parsing logic
2. **Similar Meeting Matching**: Use industry + visit focus + sales play + pillars to find similar briefings
3. **Agenda Template Library**: Build from historical patterns since structured agenda data is limited
4. **EBD Integration**: Verify EBD content location or implement capture mechanism
5. **Attendee Analysis**: Use C-level titles, decision maker flags, and technical indicators to tailor content depth
