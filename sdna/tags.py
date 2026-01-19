"""
Tag extraction and matching utilities.

Simple orchestration via XML tags in agent output.
"""

import re
from typing import Dict, List, Any, Optional, Union


def extract_tags(output: str, tag_names: List[str]) -> Dict[str, Optional[str]]:
    """
    Extract XML-style tags from agent output.

    Args:
        output: Raw agent output text
        tag_names: List of tag names to extract (without brackets)

    Returns:
        Dict mapping tag names to their content (None if not found)

    Example:
        output = "Here's my work <deliverable>code here</deliverable> done"
        tags = extract_tags(output, ["deliverable", "error"])
        # {'deliverable': 'code here', 'error': None}
    """
    result = {}
    for tag in tag_names:
        pattern = rf"<{tag}>(.*?)</{tag}>"
        match = re.search(pattern, output, re.DOTALL | re.IGNORECASE)
        result[tag] = match.group(1).strip() if match else None
    return result


def match_tags(extracted: Dict[str, Optional[str]], pattern: Dict[str, Any]) -> bool:
    """
    Check if extracted tags match a pattern.

    Args:
        extracted: Dict from extract_tags()
        pattern: Dict of tag_name -> expected_value
                 Use ANY (or any truthy check) to match any non-None value
                 Use None to match missing tags
                 Use str for exact match (case-insensitive)

    Returns:
        True if all pattern conditions are met

    Example:
        tags = {'completion-promise': 'DONE', 'error': None}
        match_tags(tags, {'completion-promise': 'DONE'})  # True
        match_tags(tags, {'error': None})  # True
        match_tags(tags, {'completion-promise': ANY})  # True
    """
    for tag, expected in pattern.items():
        actual = extracted.get(tag)

        if expected is ANY:
            if actual is None:
                return False
        elif expected is None:
            if actual is not None:
                return False
        elif isinstance(expected, str):
            if actual is None or actual.lower() != expected.lower():
                return False
        else:
            # Callable or other check
            if not expected(actual):
                return False
    return True


class ANY:
    """Sentinel for matching any non-None value."""
    pass


# Convenience function for common patterns
def has_tag(extracted: Dict[str, Optional[str]], tag: str) -> bool:
    """Check if a tag exists and has content."""
    return extracted.get(tag) is not None


def tag_equals(extracted: Dict[str, Optional[str]], tag: str, value: str) -> bool:
    """Check if a tag equals a specific value (case-insensitive)."""
    actual = extracted.get(tag)
    return actual is not None and actual.lower() == value.lower()


def tag_contains(extracted: Dict[str, Optional[str]], tag: str, substring: str) -> bool:
    """Check if a tag contains a substring."""
    actual = extracted.get(tag)
    return actual is not None and substring.lower() in actual.lower()
