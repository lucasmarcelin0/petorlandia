"""Utility to ensure DateTime columns always have timezone info."""

from datetime import datetime, timezone
from sqlalchemy import event
from sqlalchemy.orm import Mapper


def setup_datetime_timezone_conversion(db):
    """
    Register event listeners to ensure all datetime attributes from 
    DateTime(timezone=True) columns are loaded as UTC-aware datetimes.
    
    This is called after db initialization.
    """
    
    @event.listens_for(Mapper, "after_configured")
    def _after_mapped_class():
        """Called once all mappers are configured."""
        pass  # This is just to ensure the event is registered
    
    # Use the receive_map_class event to register per-class listeners
    from sqlalchemy import inspect as sqla_inspect
    
    @event.listens_for(db.session, "before_bulk_update")
    def receive_after_insert(update_context):
        """Normalize datetimes after bulk update."""
        pass
    
    # Better approach: intercept at the session level
    def _normalize_datetimes():
        """Register the event properly."""
        @event.listens_for(db.Model, "load", propagate=True)
        def receive_load(target, context):
            """Called when an instance is loaded from the database."""
            mapper = sqla_inspect(type(target))
            if mapper is None:
                return
            
            for column in mapper.columns:
                # Check if this is a datetime column
                col_type_str = str(column.type)
                if 'DATETIME' not in col_type_str.upper():
                    continue
                
                attr_name = column.key
                value = getattr(target, attr_name, None)
                
                # If naive, assume UTC
                if isinstance(value, datetime) and value.tzinfo is None:
                    setattr(target, attr_name, value.replace(tzinfo=timezone.utc))
    
    _normalize_datetimes()
