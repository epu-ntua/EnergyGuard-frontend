from datetime import date

def get_time_since_joined(joined_date):
    """
    Calculate human-readable time since user joined.
    
    Args:
        joined_date: datetime object or date object
        
    Returns:
        str: Formatted string like "2 months ago", "1 year ago", "today"
    """
    # Convert to date if datetime
    if hasattr(joined_date, 'date'):
        joined_date = joined_date.date()
    
    today = date.today()
    days_diff = (today - joined_date).days
    
    if days_diff == 0:
        return "today"
    elif days_diff == 1:
        return "1 day ago"
    elif days_diff < 30:
        return f"{days_diff} days ago"
    elif days_diff < 365:
        months = days_diff // 30
        return f"{months} month{'s' if months > 1 else ''} ago"
    else:
        years = days_diff // 365
        return f"{years} year{'s' if years > 1 else ''} ago"