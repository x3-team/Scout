"""Compatibility review entry point; draft.2 diagnostics are now acceptance cases.

The historical request-revision evidence remains pinned at Scout 547a343.
Current script validates draft.3 fixtures; it never approves runtime or merge.
"""
from check_integration_contract import main

if __name__ == '__main__':
    main()
