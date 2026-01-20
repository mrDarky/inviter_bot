# Static Message Time-Based Scheduling

## Overview
This document describes the time-based scheduling feature for static messages in the inviter bot.

## Features

### 1. Time-Based Message Delivery
Static messages can now be scheduled with precise timing controls:

- **Day 0 Messages**: Sent based on the user's join time plus an optional offset
- **Day 1+ Messages**: Sent at a specific UTC time plus an optional offset
- **Multiple Messages**: Multiple messages can be scheduled for the same day at different times

### 2. Configuration Options

#### Send Time (for Day 1+)
- Format: HH:MM (24-hour format in UTC)
- Example: "12:05" means 12:05 PM UTC
- Default: 09:00 if not specified
- Only applicable for Day 1+ messages

#### Additional Minutes
- Adds an offset to the send time
- Can be used for both Day 0 and Day 1+ messages
- Examples: 5 (5 minutes), 15 (15 minutes), 30 (30 minutes)
- Default: 0 (no offset)

### 3. Sending Logic

#### For Day 0 (Immediate)
- Message is sent when: `current_time >= join_time + additional_minutes`
- Example: User joins at 10:00, additional_minutes=15 → message sent at 10:15 or later

#### For Day 1+ (Scheduled)
- Message is sent when: current time is within the 5-minute window starting from `target_date at send_time + additional_minutes`
- Example: User joined on Day 0, send_time="12:05", additional_minutes=10 → message sent on Day 1 at 12:15-12:20
- Sending window: 5 minutes (prevents missing the exact time)

### 4. Duplicate Prevention
- Each message-user combination is tracked in the `static_messages_sent` table
- Once a message is sent to a user, it will not be sent again
- This allows multiple messages per day without duplication

## Database Schema

### New Fields in `static_messages` Table
```sql
send_time TEXT            -- HH:MM format for Day 1+ messages
additional_minutes INTEGER -- Offset in minutes (default: 0)
```

### New Table: `static_messages_sent`
```sql
CREATE TABLE static_messages_sent (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    static_message_id INTEGER NOT NULL,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, static_message_id)
)
```

## Usage Examples

### Example 1: Day 0 Message with 15-Minute Delay
```
Day Number: 0
Send Time: (leave empty)
Additional Minutes: 15
```
→ User joins at 10:00 AM, message sent at 10:15 AM

### Example 2: Day 1 Message at Specific Time
```
Day Number: 1
Send Time: 12:05
Additional Minutes: 0
```
→ User joins on Day 0, message sent on Day 1 at 12:05 PM UTC

### Example 3: Day 1 Message with Offset
```
Day Number: 1
Send Time: 12:05
Additional Minutes: 30
```
→ User joins on Day 0, message sent on Day 1 at 12:35 PM UTC

### Example 4: Multiple Messages on Same Day
```
Message 1:
  Day Number: 1
  Send Time: 09:00
  Additional Minutes: 0

Message 2:
  Day Number: 1
  Send Time: 12:00
  Additional Minutes: 0

Message 3:
  Day Number: 1
  Send Time: 18:00
  Additional Minutes: 0
```
→ User receives 3 messages on Day 1 at 9:00 AM, 12:00 PM, and 6:00 PM UTC

## Scheduler Configuration

The scheduler now checks for messages to send every minute:
```python
scheduler.add_job(send_static_messages, 'interval', minutes=1)
```

This ensures messages are sent within 1 minute of their scheduled time (with a 5-minute sending window for Day 1+ messages).

## UI Changes

### Admin Panel - Static Messages Page

1. **Send Time Input** (for Day 1+ messages)
   - Visible only when Day Number > 0
   - Time picker in HH:MM format
   - Tooltip: "Time in UTC when to send (for Day 1+). Leave empty for 09:00 default."

2. **Additional Minutes Input**
   - Visible for all messages
   - Number input (min: 0)
   - Tooltip: "Offset in minutes to add to send time (e.g., 5, 15, 30)"

3. **Table Display**
   - New column: "Send Time"
   - Shows configured time or default ("From Join" for Day 0, "09:00" for Day 1+)
   - Shows additional minutes as badge (e.g., "+5m", "+15m")

## API Changes

### `StaticMessageRequest` Model
```python
class StaticMessageRequest(BaseModel):
    day_number: int
    text: str
    html_text: Optional[str] = None
    media_type: Optional[str] = 'text'
    media_file_id: Optional[str] = None
    buttons_config: Optional[str] = None
    send_time: Optional[str] = None          # NEW
    additional_minutes: Optional[int] = 0    # NEW
```

## Migration

The database automatically migrates existing tables when the application starts. Existing messages will have:
- `send_time`: NULL (defaults to 09:00 for Day 1+ messages)
- `additional_minutes`: 0 (no offset)

## Testing

Run the test script to verify the implementation:
```bash
python /tmp/test_static_message_scheduling.py
```

The test covers:
1. Database schema with new fields
2. Message sent tracking
3. Time calculation logic for Day 0
4. Time calculation logic for Day 1+

## Troubleshooting

### Messages Not Sending
1. Check scheduler is running (logs should show "Scheduler started")
2. Verify message is active (is_active = 1)
3. Check if message was already sent to the user (query static_messages_sent table)
4. Verify time calculations in logs

### Wrong Send Time
1. Ensure send_time is in UTC, not local time
2. Check additional_minutes is correctly set
3. For Day 1+, verify target date calculation: `join_date + days_since_join`

## Future Enhancements

Possible future improvements:
- Time zone support for individual users
- Custom sending window (currently fixed at 5 minutes)
- Retry logic for failed sends
- Dashboard to view scheduled messages per user
- Message queue visualization
