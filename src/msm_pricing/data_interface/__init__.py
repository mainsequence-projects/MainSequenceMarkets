from .data_interface import DateInfo, MSDataInterface

# export a single, uniform instance
data_interface = MSDataInterface()

__all__ = ["DateInfo", "MSDataInterface", "data_interface"]
