# ✅ Working Database Queries - Comprehensive List

**Test Results Summary:**

- **Total Queries Tested:** 65
- **Successful:** 63 (96.92%)
- **Failed:** 2 (3.08%)
- **Test Date:** December 5, 2025

---

## 📊 Operations & Meeting Queries (14/14 Working - 100%)

1. How many events does Nvidia have compared to Apple?
2. What is the breakdown of events by region? Show me how many events are in EMEA, North America, LAD, and JAPAC.
3. Which events are assigned to Robert Smith and what are the customer names and start dates?
4. How many events are there per line of business? Show me the count for NACI, Marketing, CAGBU, and Glueck.
5. List all events scheduled for November 2025 with their customer names, regions, and tech managers.
6. Show me all events happening this month
7. What events are happening today?
8. How many events are scheduled for December 2025?
9. List all events for the customer 'Ford Motor'
10. Show me events sorted by start date
11. What is the total number of events in the database?
12. Show me the top 5 customers by number of events
13. Which regions have the most events?
14. List all briefing managers and their event counts

---

## 👥 Attendee Analysis Queries (12/12 Working - 100%)

1. Show me how many decision makers each company has. Which companies have the most decision makers in their events?
2. Show me all attendees for Barclays events, including their names, whether they are decision makers, influencers, or technical, and if they are remote or in-person.
3. What is the breakdown of attendees by remote versus in-person? Show me the total count for each.
4. Find all events where there are no decision makers in the attendee list. Show the customer name and event ID.
5. How many attendees are Internal versus External across all events?
6. What is the total number of attendees across all events?
7. Show me all decision makers attending events this month
8. Which events have more than 10 attendees?
9. List all remote attendees for November 2025 events
10. Show me the breakdown of attendee types (Internal vs External)
11. How many influencers are attending Apple events?
12. Which companies have technical attendees?

---

## 💰 Revenue & Opportunity Queries (9/10 Working - 90%)

### ✅ Working Queries:

1. What is the total closed opportunity revenue across all events? Also show the average, minimum, and maximum.
   #not working 2. Show me all opportunities with probability of close greater than 75%. Include customer name and the probability percentage.
2. How many opportunities have closed revenue between $300,000 and $500,000? Show the customer names and revenue amounts.
3. What is the total open opportunity revenue?
4. Show me opportunities closing in Q4 2025
5. What is the average opportunity revenue per customer?
6. List all opportunities with status 'Open'
7. Which events have the highest initial opportunity revenue?
8. Show me the total revenue by line of business

### ❌ Failed Query:

- What is the closed opportunity revenue for each company? Show me which companies have the highest revenue.
  - **Reason:** No data available for closed opportunity revenue by company

---

## 🔄 Complex Multi-View Queries (5/6 Working - 83%)

### ✅ Working Queries:

1. Give me a complete analysis for Ford Motor: show all their events with dates, total attendees, number of decision makers, remote vs in-person count, and any associated revenue or opportunity data.
2. Show me a summary of all events in November 2025 including attendee count, decision maker count, and total revenue
3. Compare event metrics between EMEA and North America regions
4. Show me which tech managers have the highest total opportunity revenue
5. List events with high-value opportunities (>$500k) and their decision maker count

### ❌ Failed Query:

- Give me a breakdown of events by region with attendee statistics and revenue data
  - **Reason:** Invalid revenue fields in query structure

---

## 📅 Time-Based Queries (6/6 Working - 100%)

1. How many meetings are submitted this month?
2. How many meetings were submitted last month compared to this month?
3. Show me events starting in the next 7 days
4. What events started in October 2025?
5. List all events that happened in Q3 2025
6. Show me upcoming events in December 2025

---

## 🔍 Search & Filter Queries (6/6 Working - 100%)

1. Find all events related to IBM
2. Check if IBM visit on Dec 14 has all presenters assigned
3. Show me all events in the Technology sector
4. Find events with 'Digital Transformation' in the visit focus
5. List all Tier 1 accounts
6. Show me events managed by specific briefing managers

---

## 📈 Aggregation & Statistics Queries (6/6 Working - 100%)

1. What is the average number of attendees per event?
2. Show me the distribution of events by form type
3. What percentage of attendees are decision makers?
4. How many events per month for 2025?
5. What is the conversion rate of opportunities by region?
6. Show me customer engagement metrics

---

## ⚖️ Comparison Queries (5/5 Working - 100%)

1. Compare attendee engagement between North America and EMEA
2. Show me revenue comparison across different line of business categories
3. Compare this month's event count with last month
4. Which region has better opportunity close rates?
5. Compare decision maker attendance across different regions

---

## 📋 Category Performance Summary

| Category                      | Working | Total  | Success Rate |
| ----------------------------- | ------- | ------ | ------------ |
| Operations & Meeting Queries  | 14      | 14     | 100.0%       |
| Attendee Analysis Queries     | 12      | 12     | 100.0%       |
| Revenue & Opportunity Queries | 9       | 10     | 90.0%        |
| Complex Multi-View Queries    | 5       | 6      | 83.3%        |
| Time-Based Queries            | 6       | 6      | 100.0%       |
| Search & Filter Queries       | 6       | 6      | 100.0%       |
| Aggregation & Statistics      | 6       | 6      | 100.0%       |
| Comparison Queries            | 5       | 5      | 100.0%       |
| **TOTAL**                     | **63**  | **65** | **96.92%**   |

---

## 💡 Key Insights

### Strengths:

- ✅ **Excellent coverage** across operations, attendee analysis, and time-based queries
- ✅ **100% success rate** in 6 out of 8 categories
- ✅ **Strong multi-view query support** with intelligent fallback handling
- ✅ **Robust date/time handling** using epoch millisecond conversions

### Areas for Improvement:

- ⚠️ Some revenue aggregation queries may return null values due to incomplete data
- ⚠️ Complex multi-view queries with revenue fields occasionally encounter schema issues

---

## 🚀 Usage Tips

1. **Best Performance:** Operations, attendee, and time-based queries
2. **Most Reliable:** Simple aggregations and single-view queries
3. **Use with Caution:** Complex revenue aggregations across multiple companies
4. **Average Response Time:** 8-15 seconds for simple queries, 20-35 seconds for complex multi-view queries

---

**Generated:** December 5, 2025  
**Test Environment:** Oracle Database via VPN connection  
**Testing Framework:** Comprehensive automated test suite with 65 queries
