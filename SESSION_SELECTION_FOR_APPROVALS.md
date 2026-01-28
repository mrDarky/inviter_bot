# Session Selection for Invite Request Approvals

## Overview

This feature adds the ability to select which session to use when approving invite requests. Previously, all approvals were done using the default bot token. Now, you can choose to approve using any active Pyrogram session or the default bot.

## How It Works

### User Interface

When you click either **"Approve Selected"** or **"Approve All"** buttons on the Invite Requests page:

1. A modal popup will appear
2. The modal displays a dropdown with available sessions:
   - **Bot (Default)** - Uses the configured bot token
   - **Active Pyrogram Sessions** - Lists all active user/bot sessions from Session Manager
3. Select your preferred session
4. Click **"Approve"** to proceed

### Use Cases

**Use Bot (Default):**
- Standard approvals
- When you want to approve as the bot account

**Use Pyrogram Session:**
- When you need to approve as a specific user account
- When the bot doesn't have proper permissions
- When you want approvals to appear from a different account

## Technical Details

### Backend Changes

**New API Endpoint:**
- `GET /api/sessions/list` - Returns list of active Pyrogram sessions

**Modified Endpoints:**
- `POST /api/invite-requests/approve` - Now accepts `session_name` parameter (optional)
- `POST /api/invite-requests/approve-all` - Now accepts `session_name` parameter (optional)

**Request Format:**
```json
{
  "request_ids": [1, 2, 3],  // For approve-selected
  "session_name": "my_session"  // Optional: null/omitted = use bot
}
```

### Session Handling

- If `session_name` is null or not provided: Uses default bot token via aiogram
- If `session_name` is provided: Uses specified Pyrogram session
- Both user and bot Pyrogram sessions are supported
- Proper resource cleanup with try-finally blocks
- Chat info caching to reduce redundant API calls

### Error Handling

- Validates session exists before attempting approval
- Properly logs all errors
- User-friendly error messages in the UI
- Automatic client cleanup on errors

## Security Considerations

- Only active sessions are shown in the dropdown
- Session selection requires authenticated access
- All approvals are logged with session information
- Resource cleanup prevents connection leaks

## Future Enhancements

Potential improvements could include:
- Remember last selected session per user
- Show session capabilities/permissions before selection
- Batch approval progress indicator
- Session health check before approval
