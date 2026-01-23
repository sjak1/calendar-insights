# Test Prompts for Database Query System

These prompts are designed to test the `query_database` function against the Oracle views (VW_OPERATIONS_REPORT, VW_ATTENDEE_REPORT, VW_OPP_TRACKING_REPORT).

**Based on actual database data:**

- Companies: Test, Nvidia, Grand Hotels SLA, Apple, Alibaba, Ford Motor, Charles Schwab, AT&T, Coca-Cola, PepsiCo, Barclays, Starbucks, Roche, Qatar Airways
- Regions: EMEA, LAD, North America, JAPAC, Test
- Lines of Business: NACI, Marketing, CAGBU, Glueck, Lynch, NAA
- Tech Managers: Robert Smith, Technical Manager, Technical Manager1, Technical Manager2
- Dates: November 2025 to December 2026
- Revenue: Range from $125K to $956K, average $416K

## Operations & Meeting Queries

1. **Company Event Counts**
   "How many events does Nvidia have compared to Apple?"

2. **Regional Distribution**
   "What is the breakdown of events by region? Show me how many events are in EMEA, North America, LAD, and JAPAC."

3. **Tech Manager Assignment**
   "Which events are assigned to Robert Smith and what are the customer names and start dates?"

4. **Events by Line of Business**
   "How many events are there per line of business? Show me the count for NACI, Marketing, CAGBU, and Glueck."

5. **November 2025 Events**
   "List all events scheduled for November 2025 with their customer names, regions, and tech managers."

## Attendee Analysis Queries

6. **Decision Makers by Company**
   "Show me how many decision makers each company has. Which companies have the most decision makers in their events?"

7. **Barclays Attendee Details**
   "Show me all attendees for Barclays events, including their names, whether they are decision makers, influencers, or technical, and if they are remote or in-person."

8. **Remote vs In-Person Breakdown**
   "What is the breakdown of attendees by remote versus in-person? Show me the total count for each."

9. **Events Without Decision Makers**
   "Find all events where there are no decision makers in the attendee list. Show the customer name and event ID."

10. **Attendee Type Distribution**
    "How many attendees are Internal versus External across all events?"

## Revenue & Opportunity Queries

11. **Total Closed Revenue**
    "What is the total closed opportunity revenue across all events? Also show the average, minimum, and maximum."

12. **High Probability Opportunities**
    "Show me all opportunities with probability of close greater than 75%. Include customer name and the probability percentage."

13. **Revenue by Company**
    "What is the closed opportunity revenue for each company? Show me which companies have the highest revenue."

14. **Revenue Range Analysis**
    "How many opportunities have closed revenue between $300,000 and $500,000? Show the customer names and revenue amounts."

## Complex Multi-View Queries

15. **Complete Event Analysis for Specific Company**
    "Give me a complete analysis for Ford Motor: show all their events with dates, total attendees, number of decision makers, remote vs in-person count, and any associated revenue or opportunity data."
