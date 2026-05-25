from .data_interface import DateInfo, MSInterface

# export a single, uniform instance
data_interface = MSInterface()

__all__ = ["DateInfo", "MSInterface", "data_interface"]
