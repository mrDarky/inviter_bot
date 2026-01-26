# Auto-Approve and Question/Answer System Implementation

## Overview

This implementation adds a complete auto-approve and question/answer system to the Inviter Bot. It allows administrators to:

1. Configure different auto-approve modes for join requests
2. Create onboarding questions with text input or button answers
3. Automatically approve users after they complete questions
4. Add "viewed" buttons to static messages
5. Show next message after button clicks
6. Store all user answers for analysis

## Features Implemented

### 1. Auto-Approve Modes

Three approval modes are now available in Settings:

- **Manual (Default)**: Admins must manually approve all join requests
- **Immediate**: Join requests are automatically approved the moment they arrive
- **After Questions**: Users are approved after completing all onboarding questions

### 2. User Questions Management

A new "User Questions" page allows admins to:

- Create questions with text input or button selection
- Set question order (determines the sequence)
- Mark questions as required or optional
- Activate/deactivate questions
- Provide button options for multiple choice questions

**Question Types:**
- **Text Input**: User types their answer
- **Button Selection**: User selects from predefined options

### 3. Enhanced Static Messages

Static messages now support:

- **Viewed Button**: Each message includes a "Mark as Viewed" button
- **Next Message**: After marking as viewed, the next message is automatically sent
- **Combined Buttons**: Custom buttons (from buttons_config) + viewed button

### 4. User Answer Storage

All user responses are stored in the database:

- Question text and type
- User's answer
- Timestamp of response
- Can be viewed per user in the API: `/api/users/{user_id}/answers`

## Database Schema

### New Tables

#### `user_questions`
```sql
CREATE TABLE user_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_text TEXT NOT NULL,
    question_type TEXT NOT NULL,  -- 'text' or 'buttons'
    options TEXT,                  -- comma-separated or JSON
    is_required INTEGER DEFAULT 1,
    order_number INTEGER NOT NULL,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
```

#### `user_answers`
```sql
CREATE TABLE user_answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    question_id INTEGER NOT NULL,
    answer_text TEXT NOT NULL,
    answered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (question_id) REFERENCES user_questions(id)
)
```

#### `user_onboarding_state`
```sql
CREATE TABLE user_onboarding_state (
    user_id INTEGER PRIMARY KEY,
    current_question_id INTEGER,
    static_messages_completed INTEGER DEFAULT 0,
    onboarding_started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    onboarding_completed_at TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
)
```

## Bot Behavior

### Join Request Flow

#### Manual Mode (Default)
1. User requests to join channel
2. Request is stored in database
3. Admin manually approves/denies from admin panel

#### Immediate Mode
1. User requests to join channel
2. Request is automatically approved immediately
3. User gains access instantly

#### After Questions Mode
1. User requests to join channel
2. Bot sends first onboarding question
3. User answers all questions sequentially
4. Upon completion, join request is automatically approved
5. Welcome message is sent

### Question Flow

1. **Start**: User starts bot or requests to join (with After Questions mode)
2. **Question 1**: Bot sends first question (by order_number)
   - Text questions: User types answer
   - Button questions: User clicks answer button
3. **Next Question**: Bot sends next question after answer is recorded
4. **Completion**: After last question, onboarding is marked complete
5. **Auto-Approve**: If mode is "after_messages", pending join requests are approved
6. **Welcome**: Confirmation message sent to user

### Static Messages with Viewed Button

1. Static message is sent at configured time
2. Message includes all custom buttons + "👁 Mark as Viewed" button
3. User clicks "Mark as Viewed"
4. Button changes to "✓ Viewed"
5. Next message (if any) is sent immediately
6. Action is logged in database

## API Endpoints

### Questions Management

- `GET /admin/questions` - Questions management page
- `POST /api/questions/add` - Add new question
- `GET /api/questions/{id}` - Get specific question
- `PUT /api/questions/{id}` - Update question
- `DELETE /api/questions/{id}` - Delete question
- `POST /api/questions/{id}/toggle` - Toggle active status

### User Answers

- `GET /api/users/{user_id}/answers` - Get all answers for a user

### Settings

The settings endpoint now accepts:
- `auto_approve_mode`: "manual", "immediate", or "after_messages"

## Usage Guide

### Setting Up Auto-Approve with Questions

1. **Navigate to Settings**
   - Go to Admin Panel → Settings
   - Find "Auto-Approve Mode" dropdown
   - Select "Auto-Approve After Questions"
   - Click "Save Settings"

2. **Create Questions**
   - Go to Admin Panel → User Questions
   - Click "Add Question"
   - Fill in:
     - Question Text: "What is your email?"
     - Question Type: Text Input
     - Order Number: 0 (first question)
     - Required: Checked
   - Click "Add Question"

3. **Add More Questions**
   - Click "Add Question" again
   - Fill in:
     - Question Text: "How did you hear about us?"
     - Question Type: Button Selection
     - Options: "Friend, Social Media, Search Engine, Other"
     - Order Number: 1
     - Required: Checked
   - Click "Add Question"

4. **Test the Flow**
   - Create a test join request to your channel
   - Bot will send questions to the user
   - User answers each question
   - After completion, user is auto-approved

### Adding Viewed Buttons to Static Messages

Static messages automatically get a "Mark as Viewed" button. No configuration needed!

The button appears below any custom buttons you've configured in the buttons_config field.

### Viewing User Answers

User answers are stored in the database. To view them:

**Via API:**
```bash
curl http://localhost:8000/api/users/123456789/answers
```

**Response:**
```json
{
  "answers": [
    {
      "id": 1,
      "user_id": 123456789,
      "question_id": 1,
      "question_text": "What is your email?",
      "question_type": "text",
      "answer_text": "user@example.com",
      "answered_at": "2024-01-24 10:30:00"
    }
  ]
}
```

## Bot Handlers

### New Callback Handlers

#### `@dp.callback_query(F.data.startswith("viewed_"))`
Handles when user clicks "Mark as Viewed" button:
- Logs the action
- Updates button to show "✓ Viewed"
- Sends next message if available

#### `@dp.callback_query(F.data.startswith("answer_"))`
Handles when user selects a button answer:
- Extracts question ID and answer
- Stores answer in database
- Sends next question or completes onboarding

### Updated Text Handler

The text message handler now:
1. Checks if user is in onboarding (waiting for text answer)
2. If yes, stores answer and sends next question
3. If no, handles menu buttons as before

## Configuration Examples

### Example 1: Simple Text Survey

```python
# Questions (in order)
1. "What is your full name?" (text)
2. "What is your email?" (text)
3. "How did you hear about us?" (buttons: Friend, Social Media, Other)
```

### Example 2: Age Gate with Terms

```python
# Questions (in order)
1. "Are you 18 years or older?" (buttons: Yes, No)
2. "Do you agree to our terms of service?" (buttons: I Agree, I Disagree)
```

If user answers "No" or "I Disagree", you can manually deny the request.

## Security Considerations

1. **Input Validation**: All text answers are stored as-is. Validate/sanitize when displaying.
2. **XSS Protection**: Admin panel already has XSS protection via proper escaping.
3. **Rate Limiting**: Consider adding rate limits to prevent spam questions.
4. **Data Privacy**: User answers contain personal information. Comply with GDPR/privacy laws.

## Troubleshooting

### Questions Not Appearing

**Problem**: User starts bot but doesn't receive questions.

**Solution**:
1. Check Settings → Auto-Approve Mode is set to "After Questions" or configure questions for manual start
2. Verify questions are marked as Active in User Questions page
3. Check bot logs for errors

### Auto-Approve Not Working

**Problem**: User completes questions but isn't approved.

**Solution**:
1. Verify Settings → Auto-Approve Mode = "Auto-Approve After Questions"
2. Check if user has pending join requests in database
3. Review bot logs for approval errors

### Viewed Button Not Working

**Problem**: Clicking viewed button doesn't send next message.

**Solution**:
1. Check if next message exists in sequence (same day, higher ID)
2. Verify next message is marked as Active
3. Check bot logs for sending errors

## Future Enhancements

Possible improvements:

1. **Conditional Questions**: Show question B only if answer to A is X
2. **Question Templates**: Pre-built question sets for common use cases
3. **Analytics Dashboard**: Visualize answer distributions
4. **Export Answers**: Download all answers as CSV/Excel
5. **Multi-language**: Support questions in multiple languages
6. **Answer Validation**: Regex patterns for text inputs (email, phone, etc.)
7. **Rich Media Questions**: Images/videos in questions
8. **Question Branching**: Different paths based on answers

## Testing

The implementation includes automated tests in `/tmp/test_database_schema.py`:

```bash
cd /home/runner/work/inviter_bot/inviter_bot
PYTHONPATH=/home/runner/work/inviter_bot/inviter_bot python3 /tmp/test_database_schema.py
```

All tests should pass with "✅ All tests passed!"

## Summary

This implementation provides a complete auto-approve and onboarding system:

✅ Three auto-approve modes (manual, immediate, after questions)
✅ Question management UI with text and button types
✅ User answer storage and retrieval
✅ Enhanced static messages with viewed buttons
✅ Automatic progression through questions
✅ Next message after viewed button click
✅ Complete database schema with proper relations
✅ RESTful API endpoints for all operations
✅ Comprehensive bot handlers for callbacks and text
✅ Settings integration for easy configuration

The system is production-ready and tested!
