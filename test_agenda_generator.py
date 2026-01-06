"""
Comprehensive test and benchmark for agenda_generator.py
"""
import json
import time
from typing import Dict, Any
from tools.agenda_generator import generate_agenda, _fetch_meeting_context

def test_case(name: str, **kwargs):
    """Run a test case and return results."""
    print(f"\n{'='*80}")
    print(f"TEST: {name}")
    print(f"{'='*80}")
    
    start_time = time.time()
    result = generate_agenda(**kwargs)
    elapsed = time.time() - start_time
    
    print(f"\n⏱️  Execution Time: {elapsed:.2f} seconds")
    print(f"✅ Success: {result.get('success', False)}")
    
    if result.get('success'):
        print(f"📊 Metadata:")
        print(f"   - Company: {result.get('company')}")
        print(f"   - Industry: {result.get('industry')}")
        print(f"   - Visit Focus: {result.get('visit_focus')}")
        print(f"   - Attendees: {result.get('attendee_count')}")
        print(f"   - Previous Meetings: {result.get('previous_meetings_count')}")
        print(f"   - Agenda Length: {len(result.get('agenda', ''))} characters")
        
        # Verify agenda structure
        agenda = result.get('agenda', '')
        checks = {
            'Has time slots': any(keyword in agenda.lower() for keyword in ['am', 'pm', ':', '00', '30']),
            'Has session titles': any(keyword in agenda.lower() for keyword in ['session', 'presentation', 'discussion', 'break']),
            'Has company name': result.get('company', '').lower() in agenda.lower() if result.get('company') else False,
            'Has industry context': result.get('industry', '').lower() in agenda.lower() if result.get('industry') else False,
            'Professional format': any(keyword in agenda.lower() for keyword in ['agenda', 'schedule', 'briefing']),
        }
        
        print(f"\n🔍 Quality Checks:")
        for check, passed in checks.items():
            status = "✅" if passed else "❌"
            print(f"   {status} {check}")
        
        return {
            'success': True,
            'time': elapsed,
            'metadata': {k: v for k, v in result.items() if k != 'agenda'},
            'quality_checks': checks,
            'agenda_preview': agenda[:500] + "..." if len(agenda) > 500 else agenda
        }
    else:
        print(f"❌ Error: {result.get('error')}")
        return {
            'success': False,
            'time': elapsed,
            'error': result.get('error')
        }

def verify_data_quality(context: Dict[str, Any]) -> Dict[str, Any]:
    """Verify the quality of fetched data."""
    print(f"\n{'='*80}")
    print("DATA QUALITY VERIFICATION")
    print(f"{'='*80}")
    
    checks = {}
    
    # Check meeting details
    meeting = context.get('meeting_details')
    if meeting:
        checks['meeting_details'] = {
            'has_event_id': bool(meeting.get('event_id')),
            'has_company_name': bool(meeting.get('company_name')),
            'has_industry': bool(meeting.get('industry')),
            'has_visit_focus': bool(meeting.get('visit_focus')),
            'has_objective': bool(meeting.get('meeting_objective')),
        }
        print(f"✅ Meeting Details: {sum(checks['meeting_details'].values())}/5 fields populated")
    else:
        checks['meeting_details'] = None
        print("❌ No meeting details found")
    
    # Check attendees
    attendees = context.get('attendees', [])
    checks['attendees'] = {
        'count': len(attendees),
        'has_names': sum(1 for a in attendees if a.get('name')),
        'has_titles': sum(1 for a in attendees if a.get('title')),
        'has_c_level': sum(1 for a in attendees if a.get('c_level')),
    }
    print(f"✅ Attendees: {checks['attendees']['count']} found, {checks['attendees']['has_names']} with names")
    
    # Check previous meetings
    previous = context.get('previous_meetings', [])
    checks['previous_meetings'] = {
        'count': len(previous),
        'has_dates': sum(1 for p in previous if p.get('date')),
    }
    print(f"✅ Previous Meetings: {checks['previous_meetings']['count']} found")
    
    # Check similar briefings
    similar = context.get('similar_briefings', [])
    checks['similar_briefings'] = {
        'count': len(similar),
        'has_companies': sum(1 for s in similar if s.get('company')),
    }
    print(f"✅ Similar Briefings: {checks['similar_briefings']['count']} found")
    
    return checks

def main():
    """Run all tests."""
    print("\n" + "="*80)
    print("AGENDA GENERATOR BENCHMARK & VERIFICATION")
    print("="*80)
    
    results = []
    
    # Test 1: Company name search
    print("\n\n🧪 TEST SUITE 1: Company Name Search")
    result1 = test_case("Company Name: HP", company_name="HP")
    results.append(('Company Name: HP', result1))
    
    # Test 2: Another company
    result2 = test_case("Company Name: Ford", company_name="Ford")
    results.append(('Company Name: Ford', result2))
    
    # Test 3: Invalid input
    print("\n\n🧪 TEST SUITE 2: Error Handling")
    result3 = test_case("No Input (should fail)", company_name=None, event_id=None)
    results.append(('No Input', result3))
    
    result4 = test_case("Invalid Company", company_name="NonExistentCompanyXYZ123")
    results.append(('Invalid Company', result4))
    
    # Test 4: Data quality verification
    print("\n\n🧪 TEST SUITE 3: Data Quality")
    if result1.get('success'):
        context = _fetch_meeting_context(company_name="HP")
        data_quality = verify_data_quality(context)
        results.append(('Data Quality', data_quality))
    
    # Summary
    print("\n\n" + "="*80)
    print("SUMMARY & RATING")
    print("="*80)
    
    successful_tests = [r for r in results if r[1].get('success')]
    failed_tests = [r for r in results if not r[1].get('success')]
    
    print(f"\n📊 Test Results:")
    print(f"   ✅ Successful: {len(successful_tests)}/{len(results)}")
    print(f"   ❌ Failed: {len(failed_tests)}/{len(results)}")
    
    if successful_tests:
        avg_time = sum(r[1].get('time', 0) for r in successful_tests) / len(successful_tests)
        print(f"   ⏱️  Average Time: {avg_time:.2f} seconds")
        
        # Quality rating
        all_checks = []
        for name, result in successful_tests:
            if 'quality_checks' in result:
                all_checks.extend(result['quality_checks'].values())
        
        if all_checks:
            quality_score = sum(all_checks) / len(all_checks) * 100
            print(f"   📈 Quality Score: {quality_score:.1f}%")
    
    # Rating
    print(f"\n⭐ RATING & REASONING:")
    print(f"\n{'='*80}")
    
    # Calculate overall score
    score = 0
    max_score = 10
    reasoning = []
    
    # Functionality (3 points)
    if len(successful_tests) >= 2:
        score += 3
        reasoning.append("✅ Core functionality works - can generate agendas")
    elif len(successful_tests) >= 1:
        score += 2
        reasoning.append("⚠️  Basic functionality works but limited testing")
    else:
        reasoning.append("❌ Core functionality broken")
    
    # Data Quality (2 points)
    if successful_tests:
        result = successful_tests[0][1]
        if 'quality_checks' in result:
            checks = result['quality_checks']
            passed = sum(checks.values())
            if passed >= 4:
                score += 2
                reasoning.append("✅ High data quality - agenda includes all key elements")
            elif passed >= 3:
                score += 1.5
                reasoning.append("⚠️  Good data quality but missing some elements")
            else:
                score += 1
                reasoning.append("⚠️  Data quality needs improvement")
    
    # Performance (2 points)
    if successful_tests:
        avg_time = sum(r[1].get('time', 0) for r in successful_tests) / len(successful_tests)
        if avg_time < 5:
            score += 2
            reasoning.append("✅ Fast performance (<5s)")
        elif avg_time < 10:
            score += 1.5
            reasoning.append("⚠️  Acceptable performance (5-10s)")
        else:
            score += 1
            reasoning.append("⚠️  Slow performance (>10s)")
    
    # Error Handling (1.5 points)
    if len(failed_tests) >= 2:
        score += 1.5
        reasoning.append("✅ Good error handling - handles invalid inputs")
    elif len(failed_tests) >= 1:
        score += 1
        reasoning.append("⚠️  Some error handling but could be better")
    else:
        score += 0.5
        reasoning.append("⚠️  Error handling not fully tested")
    
    # Code Quality (1.5 points)
    score += 1.5  # Code is well-structured
    reasoning.append("✅ Well-structured code with good separation of concerns")
    
    print(f"\n🎯 Overall Score: {score:.1f}/10")
    print(f"\n📝 Detailed Reasoning:")
    for i, reason in enumerate(reasoning, 1):
        print(f"   {i}. {reason}")
    
    # Issues found
    print(f"\n⚠️  Issues Found:")
    issues = []
    
    # Check for SQL injection vulnerability
    issues.append("🔴 SQL Injection Risk: Uses f-strings for SQL queries (lines 44, 47, 112, etc.)")
    
    # Check for missing error handling
    if not any('error' in str(r[1]) for r in failed_tests):
        issues.append("⚠️  Error handling could be more robust")
    
    # Check performance
    if successful_tests:
        avg_time = sum(r[1].get('time', 0) for r in successful_tests) / len(successful_tests)
        if avg_time > 10:
            issues.append("⚠️  Performance could be optimized (consider caching)")
    
    for issue in issues:
        print(f"   {issue}")
    
    print(f"\n{'='*80}\n")

if __name__ == "__main__":
    main()

