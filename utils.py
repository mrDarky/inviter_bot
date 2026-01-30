"""
Utility functions for the bot
"""


def is_valid_file_id(file_id):
    """
    Validate if a file_id is valid for Telegram API.
    
    A valid file_id should:
    - Be a non-empty string after stripping whitespace
    - Not be None
    
    Args:
        file_id: File ID to validate (can be str, None, or other type)
        
    Returns:
        bool: True if file_id is valid, False otherwise
    """
    if file_id is None:
        return False
    
    if not isinstance(file_id, str):
        return False
    
    # Strip whitespace and check if non-empty
    return len(file_id.strip()) > 0


def normalize_media_type(media_type):
    """
    Normalize media type value to string format.
    Handles legacy numeric media type values:
    0 or '0' -> 'text'
    1 or '1' -> 'photo'
    2 or '2' -> 'video'
    3 or '3' -> 'document'
    4 or '4' -> 'animation'
    5 or '5' -> 'audio'
    6 or '6' -> 'voice'
    7 or '7' -> 'video_note'
    
    Args:
        media_type: Media type value (can be int, str, or None)
        
    Returns:
        str: Normalized media type string from the valid set:
             ['text', 'photo', 'video', 'document', 'animation', 'audio', 'voice', 'video_note']
             Returns 'text' for None or invalid values.
    """
    if media_type is None or media_type == '':
        return 'text'
    
    # Convert to string if it's a number
    media_type_str = str(media_type)
    
    # Map numeric values to media type strings
    numeric_mapping = {
        '0': 'text',
        '1': 'photo',
        '2': 'video',
        '3': 'document',
        '4': 'animation',
        '5': 'audio',
        '6': 'voice',
        '7': 'video_note'
    }
    
    # If it's a numeric value, convert it
    if media_type_str in numeric_mapping:
        return numeric_mapping[media_type_str]
    
    # Validate the media type string
    valid_media_types = ['text', 'photo', 'video', 'document', 'animation', 'audio', 'voice', 'video_note']
    
    if media_type_str in valid_media_types:
        return media_type_str
    
    # If invalid, return 'text' as default and let the caller log the warning
    return 'text'
