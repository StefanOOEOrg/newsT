#!/usr/bin/env python3
"""
TOON Format Integration Test
Tests the complete TOON implementation including:
- Input encoding (post data to TOON)
- Output prefilling (force Claude to use TOON)
- Response parsing (TOON and JSON fallback)
"""
import os
import sys
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from anthropic import Anthropic
from toon import encode as toon_encode, decode as toon_decode
from analysis_helpers import PromptBuilder, ResponseParser


class TestResults:
    """Track test results."""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.tests = []

    def add(self, name: str, passed: bool, details: str = ""):
        self.tests.append((name, passed, details))
        if passed:
            self.passed += 1
        else:
            self.failed += 1

    def print_summary(self):
        print("\n" + "=" * 70)
        print("TEST SUMMARY")
        print("=" * 70)
        for name, passed, details in self.tests:
            status = "✓ PASS" if passed else "✗ FAIL"
            print(f"{status}: {name}")
            if details and not passed:
                print(f"  → {details}")
        print("-" * 70)
        print(f"Total: {self.passed + self.failed} tests")
        print(f"Passed: {self.passed}")
        print(f"Failed: {self.failed}")
        print("=" * 70)
        return self.failed == 0


def test_toon_input_encoding(results: TestResults):
    """Test 1: TOON input encoding."""
    print("\n[TEST 1] TOON Input Encoding")
    print("-" * 70)

    post_data = {
        'title': 'Tesla announces AI expansion',
        'ticker': 'TSLA',
        'asset_name': 'Tesla',
        'content': 'Tesla is hiring 500 AI engineers for autonomous driving.'
    }

    # Encode to TOON
    toon_output = toon_encode(post_data)
    print(f"Encoded TOON:\n{toon_output}\n")

    # Verify TOON format
    has_title = 'title: Tesla announces AI expansion' in toon_output
    has_ticker = 'ticker: TSLA' in toon_output
    has_asset = 'asset_name: Tesla' in toon_output
    has_content = 'content: Tesla is hiring' in toon_output
    no_json_braces = '{' not in toon_output and '}' not in toon_output

    passed = all([has_title, has_ticker, has_asset, has_content, no_json_braces])
    results.add(
        "TOON Input Encoding",
        passed,
        "Missing expected TOON format elements" if not passed else ""
    )

    return passed


def test_toon_output_prefilling(results: TestResults):
    """Test 2: TOON output with prefilling."""
    print("\n[TEST 2] TOON Output with Prefilling")
    print("-" * 70)

    client = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

    prompt = """Analyze this post.

Post data (in TOON format):
title: Tesla stock surges
ticker: TSLA
asset_name: Tesla
content: Tesla announces strong earnings.

Provide analysis in TOON format:
- sentiment: positive/negative/neutral
- sentiment_score: -1.0 to 1.0
- category: Hiring/Growth/Problems/Product/Earnings/Other
- key_topics: array of topics
- summary: brief summary
- special_events: array or []

Return ONLY TOON format."""

    # Test WITHOUT prefilling (should return JSON)
    print("Testing WITHOUT prefilling...")
    message_no_prefill = client.messages.create(
        model='claude-3-5-haiku-20241022',
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}]
    )
    response_no_prefill = message_no_prefill.content[0].text
    is_json = response_no_prefill.strip().startswith('{')
    print(f"Response starts with: {response_no_prefill[:50]}")
    print(f"Is JSON: {is_json}")

    # Test WITH prefilling (should return TOON)
    print("\nTesting WITH prefilling...")
    message_with_prefill = client.messages.create(
        model='claude-3-5-haiku-20241022',
        max_tokens=256,
        messages=[
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": "sentiment:"}
        ]
    )
    response_with_prefill = "sentiment:" + message_with_prefill.content[0].text
    is_toon = not response_with_prefill.strip().startswith('{')
    has_toon_structure = 'sentiment:' in response_with_prefill and 'sentiment_score:' in response_with_prefill
    print(f"Response: {response_with_prefill[:100]}...")
    print(f"Is TOON: {is_toon}")
    print(f"Has TOON structure: {has_toon_structure}")

    passed = is_json and is_toon and has_toon_structure
    results.add(
        "TOON Output Prefilling",
        passed,
        "Prefilling did not enforce TOON format" if not passed else ""
    )

    return passed


def test_toon_parsing(results: TestResults):
    """Test 3: TOON response parsing."""
    print("\n[TEST 3] TOON Response Parsing")
    print("-" * 70)

    parser = ResponseParser()
    post = {'id': 1, 'asset_id': 2}

    # Test TOON format parsing
    toon_response = """sentiment: positive
sentiment_score: 0.7
category: Growth
key_topics[3]: hiring, expansion, growth
summary: Company announces expansion plans.
special_events[0]:"""

    print("Parsing TOON response...")
    toon_result = parser.parse_analysis_response(toon_response, post)
    toon_success = (
        toon_result is not None and
        toon_result.get('sentiment') == 'positive' and
        toon_result.get('sentiment_score') == 0.7 and
        toon_result.get('category') == 'Growth'
    )
    print(f"TOON parsing: {'SUCCESS' if toon_success else 'FAILED'}")

    results.add(
        "TOON Parsing",
        toon_success,
        "Failed to parse valid TOON response" if not toon_success else ""
    )

    return toon_success


def test_json_fallback(results: TestResults):
    """Test 4: JSON fallback parsing."""
    print("\n[TEST 4] JSON Fallback Parsing")
    print("-" * 70)

    parser = ResponseParser()
    post = {'id': 1, 'asset_id': 2}

    # Test JSON fallback
    json_response = """{
    "sentiment": "negative",
    "sentiment_score": -0.5,
    "category": "Problems",
    "key_topics": ["issues", "concerns"],
    "summary": "Company faces challenges.",
    "special_events": []
}"""

    print("Parsing JSON response (should trigger fallback warning)...")
    json_result = parser.parse_analysis_response(json_response, post)
    json_success = (
        json_result is not None and
        json_result.get('sentiment') == 'negative' and
        json_result.get('sentiment_score') == -0.5 and
        json_result.get('category') == 'Problems'
    )
    print(f"JSON fallback parsing: {'SUCCESS' if json_success else 'FAILED'}")

    results.add(
        "JSON Fallback",
        json_success,
        "Failed to parse JSON when TOON parsing fails" if not json_success else ""
    )

    return json_success


def test_prompt_builder(results: TestResults):
    """Test 5: Prompt builder with TOON input."""
    print("\n[TEST 5] Prompt Builder Integration")
    print("-" * 70)

    builder = PromptBuilder(os.getenv('DATABASE_URL'))

    post = {
        'id': 1,
        'title': 'Tesla expands AI team',
        'content': 'Tesla is hiring hundreds of AI engineers.',
        'asset_name': 'Tesla',
        'ticker': 'TSLA'
    }

    print("Building prompt with TOON input...")
    prompt = builder.build_analysis_prompt(post)

    # Verify prompt contains TOON input data
    has_toon_marker = 'Post data (in TOON format)' in prompt or 'in TOON format' in prompt
    has_ticker_line = 'ticker: TSLA' in prompt
    has_title_line = 'title: Tesla expands AI team' in prompt
    requests_toon_output = 'TOON format' in prompt

    print(f"Prompt length: {len(prompt)} chars")
    print(f"Has TOON marker: {has_toon_marker}")
    print(f"Has TOON structure: {has_ticker_line and has_title_line}")
    print(f"Requests TOON output: {requests_toon_output}")

    passed = all([has_toon_marker, has_ticker_line, has_title_line, requests_toon_output])
    results.add(
        "Prompt Builder TOON Integration",
        passed,
        "Prompt does not properly use TOON format" if not passed else ""
    )

    return passed


def test_end_to_end(results: TestResults):
    """Test 6: End-to-end TOON workflow."""
    print("\n[TEST 6] End-to-End TOON Workflow")
    print("-" * 70)

    # Build prompt with TOON input
    builder = PromptBuilder(os.getenv('DATABASE_URL'))
    post = {
        'id': 999,
        'asset_id': 1,
        'title': 'Tesla reports record earnings',
        'content': 'Tesla exceeded analyst expectations with strong Q4 results.',
        'asset_name': 'Tesla',
        'ticker': 'TSLA'
    }

    print("Building prompt...")
    prompt = builder.build_analysis_prompt(post)

    # Call Claude with prefilling
    print("Calling Claude API with prefilling...")
    client = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
    message = client.messages.create(
        model='claude-3-5-haiku-20241022',
        max_tokens=512,
        messages=[
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": "sentiment:"}
        ]
    )

    # Parse response
    response_text = "sentiment:" + message.content[0].text
    print(f"Response preview: {response_text[:150]}...")

    parser = ResponseParser()
    analysis = parser.parse_analysis_response(response_text, post)

    # Verify results
    success = (
        analysis is not None and
        'sentiment' in analysis and
        'sentiment_score' in analysis and
        'category' in analysis and
        'key_topics' in analysis and
        'summary' in analysis and
        'special_events' in analysis
    )

    if success:
        print(f"\nParsed analysis:")
        print(f"  Sentiment: {analysis['sentiment']} ({analysis['sentiment_score']})")
        print(f"  Category: {analysis['category']}")
        print(f"  Topics: {analysis['key_topics']}")

    results.add(
        "End-to-End TOON Workflow",
        success,
        "Complete workflow failed" if not success else ""
    )

    return success


def main():
    """Run all tests."""
    print("=" * 70)
    print("TOON FORMAT INTEGRATION TEST SUITE")
    print("=" * 70)
    print("\nTesting bidirectional TOON implementation:")
    print("- Input: Post data encoded in TOON format")
    print("- Output: Claude response forced to TOON via prefilling")
    print("- Parsing: TOON decoder with JSON fallback")

    results = TestResults()

    # Run tests
    try:
        test_toon_input_encoding(results)
        test_toon_output_prefilling(results)
        test_toon_parsing(results)
        test_json_fallback(results)
        test_prompt_builder(results)
        test_end_to_end(results)
    except Exception as e:
        print(f"\n✗ FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Print summary
    success = results.print_summary()

    return 0 if success else 1


if __name__ == '__main__':
    exit(main())
