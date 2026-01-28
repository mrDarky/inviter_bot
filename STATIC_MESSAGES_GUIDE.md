# Static Messages Enhancement

## Overview
This implementation adds enhanced functionality to static messages, allowing administrators to create rich messages with media attachments and interactive buttons.

## Features

### 1. Media Type Support
Static messages now support multiple media types:
- **Text Only** (default): Simple text messages
- **Photo + Text**: Image with optional caption
- **Video + Text**: Video with optional caption
- **Round Video (Video Note)**: Telegram's circular video format
- **GIF/Animation + Text**: Animated GIF with optional caption
- **Document + Text**: File attachment with optional caption
- **Audio + Text**: Audio file with optional caption
- **Voice + Text**: Voice message (note: voice messages don't support captions in Telegram, so text is sent separately)

### 2. Button Configuration
Add interactive URL buttons to messages using a simple format:
- **Single row**: `Button Text | https://url.com`
- **Multiple buttons per row**: `Button 1 | https://url1.com, Button 2 | https://url2.com`
- **Multiple rows**: One row per line in the configuration field

Example:
```
Home | https://example.com/home, About | https://example.com/about
Contact | https://example.com/contact
```

This creates two rows: first row has two buttons (Home, About), second row has one button (Contact).

### 3. Live HTML Preview
Real-time preview of HTML-formatted messages with proper sanitization:
- Supports Telegram HTML tags: `<b>`, `<i>`, `<u>`, `<s>`, `<code>`, `<pre>`, `<a>`, `<br>`
- XSS protection through HTML sanitization
- Split-screen editor with instant preview

### 4. Media Upload
Upload media files directly to Telegram:
- Files are uploaded to Telegram servers and assigned a file_id
- File IDs are stored in the database for reuse
- Requires `ADMIN_CHAT_ID` environment variable to be set

### 5. Send Test Message
Test static messages before they're sent to all users:
- Click the green "Send Test" button (with send icon) in the Actions column
- Enter a Telegram user ID (numeric) or username (with or without @)
- The bot sends the exact message configuration to the specified user
- Supports all media types and button configurations
- Validates user existence in database before sending
- Provides specific error messages if user is not found

**Note:** Users must have interacted with the bot before you can send them a test message. The user must exist in the database.

## Technical Details

### Database Schema Changes
Added three new columns to `static_messages` table:
- `media_type TEXT`: Type of media (text, photo, video, etc.)
- `media_file_id TEXT`: Telegram file ID for the media
- `buttons_config TEXT`: Button configuration string

### Migration
The database automatically migrates existing tables when the application starts.

### API Endpoints
- `POST /api/static-messages/add`: Create new static message
- `PUT /api/static-messages/{id}`: Update existing message
- `POST /api/static-messages/upload-media`: Upload media file and get file_id

### Security
- HTML sanitization prevents XSS attacks
- Only Telegram-supported HTML tags are allowed
- File uploads require authentication
- Admin chat ID validation

## Configuration

### Environment Variables
Add to `.env` file:
```env
ADMIN_CHAT_ID=your_telegram_user_id
```

To get your Telegram user ID:
1. Message @userinfobot on Telegram
2. Copy the "Id" number it returns
3. Add to your .env file

## Usage Example

### Creating a Static Message with Photo and Buttons

1. Go to Admin Panel → Static Messages
2. Click "Add Static Message"
3. Set Day Number (e.g., 0 for immediate, 1 for day 1)
4. Select Media Type: "Photo + Text"
5. Upload an image file
6. Enter Message Text: "Welcome to our community!"
7. Enter HTML Text: `<b>Welcome</b> to our <i>community</i>!`
8. Enter Button Configuration:
   ```
   Website | https://example.com
   Support | https://example.com/support
   ```
9. Preview the message in real-time
10. Click "Add Message"

### Testing a Static Message

After creating a static message, you can test it before it's sent to all users:

1. Find your message in the Static Messages table
2. Click the green "Send Test" button (with send icon) in the Actions column
3. In the popup, enter either:
   - A Telegram user ID (e.g., `12345678`)
   - A username with @ (e.g., `@johndoe`)
   - A username without @ (e.g., `johndoe`)
4. Click "Send Test"
5. The message will be sent to that user immediately
6. Check that the message appears correctly with media and buttons

**Note:** The user must have interacted with your bot before. If you get an error that the user is not found, make sure the user has started the bot or joined your channel.

### Testing the Implementation

Run the test files in /tmp:
```bash
python /tmp/test_db_migration.py
python /tmp/test_button_parsing.py
python /tmp/test_api_models.py
```

All tests should pass successfully.

## Limitations

1. **Video Notes and Voice Messages**: These media types don't support captions in Telegram API. The bot automatically sends the text as a separate message.

2. **File Size Limits**: Follow Telegram's file size limits:
   - Photos: 10 MB
   - Videos: 50 MB for bot API (2 GB for regular uploads)
   - Documents: 50 MB

3. **HTML Tags**: Only Telegram-supported HTML tags work. Complex HTML/CSS is not supported.

## Future Enhancements

Possible future improvements:
- Media library for reusing uploaded files
- Message templates
- Preview of media in admin panel
- Support for stickers and polls
- A/B testing for messages
- Analytics for button clicks

## Troubleshooting

### Media Upload Fails
- Ensure `ADMIN_CHAT_ID` is set in .env
- Verify bot token is valid
- Check file size limits
- Ensure you've started a conversation with the bot

### Buttons Not Showing
- Verify button configuration format
- Check URL format (must start with http:// or https://)
- Test with simple example first

### HTML Not Rendering
- Only use Telegram-supported tags
- Check for typos in HTML tags
- Use live preview to verify rendering

### Test Message Not Sending
- Verify the user has interacted with the bot (started it or joined your channel)
- Check that the user ID or username is correct
- Ensure the bot token is configured properly
- If using username, make sure it matches the username in the database (case-sensitive)
- Try using the numeric user ID instead of username for more reliable delivery
