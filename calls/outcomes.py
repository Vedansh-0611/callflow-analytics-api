"""Rule-based outcome tags derived from a finished call and its events."""

SHORT_CALL_SECONDS = 15

END_REASON_TAGS = {
    "transferred": "transferred",
    "voicemail": "voicemail",
    "customer_hangup": "customer_hung_up",
    "error": "error",
}


def derive_outcome_tags(call, events):
    tags = []

    if call.duration_seconds < SHORT_CALL_SECONDS:
        tags.append("short_call")

    if call.end_reason in END_REASON_TAGS:
        tags.append(END_REASON_TAGS[call.end_reason])

    tool_events = [e for e in events if e.type == "tool.called"]
    if tool_events:
        tags.append("tool_used")
    if any(e.data.get("success") is False for e in tool_events):
        tags.append("tool_failed")
    if any(e.data.get("name") == "book_appointment" and e.data.get("success") for e in tool_events):
        tags.append("booking_made")

    if call.end_reason == "completed" and "short_call" not in tags:
        tags.append("resolved")

    return tags
