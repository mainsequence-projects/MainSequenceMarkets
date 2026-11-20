"""Helpers that more than one test module uses.

A test module never imports another test module: what two of them share lives here, so
importing a helper does not also run another test module's imports and module-level code.
"""
