# Session Manager Feature

## Overview
The Session Manager allows you to create and manage Pyrogram user sessions for loading join requests from Telegram channels. This is useful for restoring join requests when the bot is not working or for recovering historical data.

## Prerequisites
- Telegram API credentials (API ID and API Hash) from https://my.telegram.org
- Admin access to the bot's admin panel
- A Telegram user account with access to the channels you want to manage

## Features

### 1. Create New Session
Create a new Pyrogram session by authenticating with your Telegram account:

1. Click "Create New Session" button
2. Enter session details:
   - **Session Name**: A unique name for the session (e.g., "my_session")
   - **API ID**: Your Telegram API ID from my.telegram.org
   - **API Hash**: Your Telegram API Hash from my.telegram.org
   - **Phone Number**: Your phone number with country code (e.g., +1234567890)
3. Click "Send Phone" - a verification code will be sent to your Telegram app
4. Enter the verification code
5. If 2FA is enabled, enter your cloud password
6. Session created successfully!

### 2. Import Existing Session
Import a previously created Pyrogram session file:

1. Click "Import Session" button
2. Fill in the session details (same as API ID, API Hash, Phone Number)
3. Select the `.session` file from your computer
4. Click "Import"
5. The session will be verified and added to the database

### 3. Check Session Status
Verify if a session is still valid:

1. Click "Check Status" button on any session
2. The system will attempt to connect and retrieve user information
3. Status will be updated in the database

### 4. Load Join Requests
Load all join requests from a specific channel:

1. Click "Load Requests" button on any session
2. Enter the channel ID or username:
   - Username format: `@channelname`
   - ID format: `-1001234567890`
3. Click "Load Requests"
4. The system will:
   - Verify you have permission to view join requests
   - Load up to 1000 join requests from the channel
   - Add them to the invite requests database
5. View loaded requests in the "Invite Requests" page

### 5. Delete Session
Remove a session from the system:

1. Click "Delete" button on any session
2. Confirm the deletion
3. Session file and database entry will be removed

## Security Considerations

- **Session files are sensitive**: They contain authentication data for your Telegram account
- Session files are stored in `./data/sessions/` directory
- Session files are excluded from git (already in .gitignore)
- Only admins with valid login can access the Session Manager
- API credentials are stored encrypted in the database

## Limitations

- Maximum 1000 join requests can be loaded per operation (to prevent timeouts)
- FloodWait errors may occur if loading too frequently from Telegram
- You must have "Invite Users" permission in the channel to load join requests
- Sessions expire if not used for extended periods

## Troubleshooting

### "Session not found. Please start over."
- The authentication process timed out. Start the creation process again.

### "Invalid verification code"
- The code you entered is incorrect. Check your Telegram app and try again.

### "Verification code expired. Please start over."
- The code expired (typically after a few minutes). Start the creation process again.

### "Invalid 2FA password"
- Your cloud password is incorrect. Try again or reset it in Telegram settings.

### "Flood wait: please wait X seconds"
- Telegram rate limiting is in effect. Wait the specified time before trying again.

### "You don't have permission to view join requests"
- Your account doesn't have admin rights in the channel, or lacks "Invite Users" permission.

### "Session is invalid"
- The session has expired or been revoked. Delete it and create a new one.

## Usage Example

1. Create a session with your Telegram account
2. Navigate to Session Manager
3. Click "Load Requests" on your session
4. Enter `@yourchannel` or channel ID
5. Wait for loading to complete
6. Go to "Invite Requests" page
7. Approve or deny requests as needed

## Notes

- Loaded requests are marked as "pending" by default
- You can approve/deny requests individually or in bulk from the Invite Requests page
- The bot must still be configured with proper credentials to approve/deny requests
- This feature is for loading/recovery only - the main bot handles ongoing requests
