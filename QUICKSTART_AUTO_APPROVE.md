# Auto-Approve & Question/Answer System - Quick Start

## Overview

This feature adds a complete auto-approve and onboarding system to the Inviter Bot with:
- Three auto-approve modes (manual, immediate, after questions)
- Question/answer system with text and button responses
- Enhanced static messages with "viewed" buttons
- Automatic message progression
- Complete answer storage

## Quick Setup (3 Steps)

### 1. Configure Auto-Approve Mode

1. Open admin panel: `http://localhost:8000`
2. Go to **Settings**
3. Find "Auto-Approve Mode" dropdown
4. Select your preferred mode:
   - **Manual** (default) - Admins approve manually
   - **Immediate** - Auto-approve instantly
   - **After Questions** - Auto-approve after user completes questions
5. Click **Save Settings**

### 2. Add Questions (if using "After Questions" mode)

1. Go to **User Questions** in admin panel
2. Click **Add Question**
3. Fill in the form:
   - **Question Text**: "What is your email?"
   - **Question Type**: Text Input
   - **Order Number**: 0 (first question)
   - **Required**: Checked
4. Click **Add Question**
5. Repeat for more questions

### 3. Test It!

1. Create a test join request to your channel
2. If mode is "After Questions":
   - User receives first question
   - User answers question
   - Bot sends next question
   - After last question, user is auto-approved
3. If mode is "Immediate":
   - User is approved instantly
4. If mode is "Manual":
   - Admin approves from admin panel

## Question Types

### Text Input
User types their answer (e.g., name, email, feedback)

**Example:**
```
Question: "What is your full name?"
User types: "John Doe"
```

### Button Selection
User clicks one of the predefined options

**Example:**
```
Question: "How did you hear about us?"
Options: "Friend, Social Media, Search Engine, Other"
User clicks: "Social Media"
```

## Static Messages with Viewed Buttons

All static messages now automatically include a "Mark as Viewed" button:

1. Message is sent to user
2. User clicks "👁 Mark as Viewed"
3. Button changes to "✓ Viewed"
4. Next message (if any) is sent automatically

## Viewing User Answers

### Via Admin Panel API
```bash
curl http://localhost:8000/api/users/123456789/answers
```

### Via Database
```sql
SELECT * FROM user_answers WHERE user_id = 123456789;
```

## Common Use Cases

### Age Gate
```
Q1: "Are you 18 or older?" (buttons: Yes, No)
Q2: "Do you agree to terms?" (buttons: I Agree, I Disagree)
```

### User Survey
```
Q1: "What is your name?" (text)
Q2: "What is your email?" (text)
Q3: "How did you find us?" (buttons: Friend, Social Media, Other)
```

### Interest Matching
```
Q1: "What topics interest you?" (buttons: Tech, Sports, Music, Art)
Q2: "Experience level?" (buttons: Beginner, Intermediate, Expert)
```

## Troubleshooting

### Questions Not Showing
- Check Settings → Auto-Approve Mode is "After Questions"
- Verify questions are marked as Active
- Check bot is running

### Auto-Approve Not Working
- Verify mode is set correctly in Settings
- Check user has pending join request
- Review bot logs for errors

### Viewed Button Not Working
- Check next message exists
- Verify next message is Active
- Review bot logs

## API Reference

### Questions
- `POST /api/questions/add` - Create question
- `GET /api/questions/{id}` - Get question
- `PUT /api/questions/{id}` - Update question
- `DELETE /api/questions/{id}` - Delete question
- `POST /api/questions/{id}/toggle` - Toggle active status

### Answers
- `GET /api/users/{user_id}/answers` - Get user's answers

## Files & Documentation

- **AUTO_APPROVE_IMPLEMENTATION.md** - Complete technical guide
- **IMPLEMENTATION_SUMMARY_AUTO_APPROVE.md** - Executive summary
- **This file** - Quick start guide

## Security

- All inputs validated client and server side
- SQL injection protected (parameterized queries)
- XSS protected (template escaping)
- CodeQL scan: 0 vulnerabilities

## Support

For detailed documentation, see:
- `AUTO_APPROVE_IMPLEMENTATION.md` - Complete guide
- Admin panel logs for debugging
- Database tables for data inspection

---

**Status**: ✅ Production Ready
**Version**: 1.0
**Last Updated**: January 24, 2026
