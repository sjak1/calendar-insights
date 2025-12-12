"""
Comprehensive Database Query Testing Suite
Tests various query types and tracks success/failure rates
"""

import json
from datetime import datetime
from get_gdp import handle_query
from logging_config import get_logger

logger = get_logger(__name__)

# Test Query Categories
TEST_QUERIES = {
    "Operations & Meeting Queries": [
        "How many events does Nvidia have compared to Apple?",
        "What is the breakdown of events by region? Show me how many events are in EMEA, North America, LAD, and JAPAC.",
        "Which events are assigned to Robert Smith and what are the customer names and start dates?",
        "How many events are there per line of business? Show me the count for NACI, Marketing, CAGBU, and Glueck.",
        "List all events scheduled for November 2025 with their customer names, regions, and tech managers.",
        "Show me all events happening this month",
        "What events are happening today?",
        "How many events are scheduled for December 2025?",
        "List all events for the customer 'Ford Motor'",
        "Show me events sorted by start date",
        "What is the total number of events in the database?",
        "Show me the top 5 customers by number of events",
        "Which regions have the most events?",
        "List all briefing managers and their event counts",
    ],
    
    "Attendee Analysis Queries": [
        "Show me how many decision makers each company has. Which companies have the most decision makers in their events?",
        "Show me all attendees for Barclays events, including their names, whether they are decision makers, influencers, or technical, and if they are remote or in-person.",
        "What is the breakdown of attendees by remote versus in-person? Show me the total count for each.",
        "Find all events where there are no decision makers in the attendee list. Show the customer name and event ID.",
        "How many attendees are Internal versus External across all events?",
        "What is the total number of attendees across all events?",
        "Show me all decision makers attending events this month",
        "Which events have more than 10 attendees?",
        "List all remote attendees for November 2025 events",
        "Show me the breakdown of attendee types (Internal vs External)",
        "How many influencers are attending Apple events?",
        "Which companies have technical attendees?",
    ],
    
    "Revenue & Opportunity Queries": [
        "What is the total closed opportunity revenue across all events? Also show the average, minimum, and maximum.",
        "Show me all opportunities with probability of close greater than 75%. Include customer name and the probability percentage.",
        "What is the closed opportunity revenue for each company? Show me which companies have the highest revenue.",
        "How many opportunities have closed revenue between $300,000 and $500,000? Show the customer names and revenue amounts.",
        "What is the total open opportunity revenue?",
        "Show me opportunities closing in Q4 2025",
        "What is the average opportunity revenue per customer?",
        "List all opportunities with status 'Open'",
        "Which events have the highest initial opportunity revenue?",
        "Show me the total revenue by line of business",
    ],
    
    "Complex Multi-View Queries": [
        "Give me a complete analysis for Ford Motor: show all their events with dates, total attendees, number of decision makers, remote vs in-person count, and any associated revenue or opportunity data.",
        "Show me a summary of all events in November 2025 including attendee count, decision maker count, and total revenue",
        "Compare event metrics between EMEA and North America regions",
        "Give me a breakdown of events by region with attendee statistics and revenue data",
        "Show me which tech managers have the highest total opportunity revenue",
        "List events with high-value opportunities (>$500k) and their decision maker count",
    ],
    
    "Time-Based Queries": [
        "How many meetings are submitted this month?",
        "How many meetings were submitted last month compared to this month?",
        "Show me events starting in the next 7 days",
        "What events started in October 2025?",
        "List all events that happened in Q3 2025",
        "Show me upcoming events in December 2025",
    ],
    
    "Search & Filter Queries": [
        "Find all events related to IBM",
        "Check if IBM visit on Dec 14 has all presenters assigned",
        "Show me all events in the Technology sector",
        "Find events with 'Digital Transformation' in the visit focus",
        "List all Tier 1 accounts",
        "Show me events managed by specific briefing managers",
    ],
    
    "Aggregation & Statistics": [
        "What is the average number of attendees per event?",
        "Show me the distribution of events by form type",
        "What percentage of attendees are decision makers?",
        "How many events per month for 2025?",
        "What is the conversion rate of opportunities by region?",
        "Show me customer engagement metrics",
    ],
    
    "Comparison Queries": [
        "Compare attendee engagement between North America and EMEA",
        "Show me revenue comparison across different line of business categories",
        "Compare this month's event count with last month",
        "Which region has better opportunity close rates?",
        "Compare decision maker attendance across different regions",
    ]
}

def test_single_query(query: str, category: str) -> dict:
    """Test a single query and return results"""
    logger.info(f"\n{'='*80}")
    logger.info(f"Testing: {query}")
    logger.info(f"Category: {category}")
    logger.info(f"{'='*80}")
    
    try:
        start_time = datetime.now()
        result = handle_query(query, None)
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        # Check if result contains error indicators
        has_error = False
        error_message = None
        
        if result:
            result_lower = result.lower()
            if any(err in result_lower for err in ['error', 'failed', 'unable', 'could not', 'cannot']):
                has_error = True
                error_message = result[:200]
        
        success = not has_error and result and len(result) > 50
        
        logger.info(f"✓ Query completed in {duration:.2f}s - {'SUCCESS' if success else 'FAILED'}")
        if not success:
            logger.warning(f"Result preview: {result[:300]}")
        
        return {
            "query": query,
            "category": category,
            "success": success,
            "duration": duration,
            "result_length": len(result) if result else 0,
            "result_preview": result[:200] if result else "",
            "error_message": error_message
        }
        
    except Exception as e:
        logger.error(f"✗ Query failed with exception: {str(e)}")
        return {
            "query": query,
            "category": category,
            "success": False,
            "duration": 0,
            "result_length": 0,
            "result_preview": "",
            "error_message": str(e)
        }

def run_all_tests():
    """Run all test queries and generate report"""
    logger.info("="*80)
    logger.info("STARTING COMPREHENSIVE DATABASE QUERY TEST SUITE")
    logger.info("="*80)
    
    all_results = []
    category_stats = {}
    
    total_queries = sum(len(queries) for queries in TEST_QUERIES.values())
    current_query = 0
    
    for category, queries in TEST_QUERIES.items():
        logger.info(f"\n\n{'#'*80}")
        logger.info(f"CATEGORY: {category}")
        logger.info(f"{'#'*80}")
        
        category_results = []
        
        for query in queries:
            current_query += 1
            logger.info(f"\n[{current_query}/{total_queries}] Processing query...")
            
            result = test_single_query(query, category)
            category_results.append(result)
            all_results.append(result)
        
        # Calculate category statistics
        success_count = sum(1 for r in category_results if r['success'])
        total_count = len(category_results)
        success_rate = (success_count / total_count * 100) if total_count > 0 else 0
        
        category_stats[category] = {
            "total": total_count,
            "success": success_count,
            "failed": total_count - success_count,
            "success_rate": success_rate
        }
        
        logger.info(f"\n{category} Results: {success_count}/{total_count} succeeded ({success_rate:.1f}%)")
    
    # Generate comprehensive report
    generate_report(all_results, category_stats)
    
    return all_results, category_stats

def generate_report(all_results, category_stats):
    """Generate a comprehensive test report"""
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Overall statistics
    total_queries = len(all_results)
    successful_queries = sum(1 for r in all_results if r['success'])
    failed_queries = total_queries - successful_queries
    overall_success_rate = (successful_queries / total_queries * 100) if total_queries > 0 else 0
    
    report = f"""
{'='*80}
DATABASE QUERY TEST REPORT
{'='*80}
Generated: {timestamp}

OVERALL STATISTICS
{'='*80}
Total Queries Tested: {total_queries}
Successful Queries: {successful_queries}
Failed Queries: {failed_queries}
Success Rate: {overall_success_rate:.2f}%

CATEGORY BREAKDOWN
{'='*80}
"""
    
    for category, stats in category_stats.items():
        report += f"\n{category}:\n"
        report += f"  Total: {stats['total']}\n"
        report += f"  Success: {stats['success']}\n"
        report += f"  Failed: {stats['failed']}\n"
        report += f"  Success Rate: {stats['success_rate']:.1f}%\n"
    
    # Successful queries list
    report += f"\n\n{'='*80}\n"
    report += "WORKING QUERIES (READY TO USE)\n"
    report += f"{'='*80}\n\n"
    
    for result in all_results:
        if result['success']:
            report += f"✓ [{result['category']}]\n"
            report += f"  Query: {result['query']}\n"
            report += f"  Duration: {result['duration']:.2f}s\n\n"
    
    # Failed queries list
    report += f"\n{'='*80}\n"
    report += "FAILED QUERIES (NEED ATTENTION)\n"
    report += f"{'='*80}\n\n"
    
    for result in all_results:
        if not result['success']:
            report += f"✗ [{result['category']}]\n"
            report += f"  Query: {result['query']}\n"
            report += f"  Error: {result['error_message'] or 'Unknown error'}\n\n"
    
    # Working queries only (clean list)
    working_queries_list = "\n\n" + "="*80 + "\n"
    working_queries_list += "WORKING QUERIES - CLEAN LIST\n"
    working_queries_list += "="*80 + "\n\n"
    
    current_category = ""
    for result in all_results:
        if result['success']:
            if result['category'] != current_category:
                current_category = result['category']
                working_queries_list += f"\n## {current_category}\n\n"
            working_queries_list += f"- {result['query']}\n"
    
    report += working_queries_list
    
    # Save report to file
    report_filename = f"test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(report_filename, 'w') as f:
        f.write(report)
    
    logger.info(f"\n\n{'='*80}")
    logger.info(f"Report saved to: {report_filename}")
    logger.info(f"{'='*80}")
    
    # Print summary to console
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    print(f"Total Queries: {total_queries}")
    print(f"Successful: {successful_queries} ({overall_success_rate:.2f}%)")
    print(f"Failed: {failed_queries}")
    print(f"\nDetailed report saved to: {report_filename}")
    print("="*80 + "\n")

if __name__ == "__main__":
    print("\n" + "="*80)
    print("DATABASE QUERY TESTING SUITE")
    print("="*80)
    print("\nThis will test all database queries and generate a comprehensive report.")
    print("The test will take several minutes to complete...")
    print("\nStarting tests...\n")
    
    results, stats = run_all_tests()
    
    print("\n✓ All tests completed!")
    print(f"✓ Tested {len(results)} queries across {len(stats)} categories")

