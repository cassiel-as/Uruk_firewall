"""Active tools — operator-promoted, registered into auto-tool agent.

Each *_service.py file must expose:
  - SERVICE: instance of the service class
  - TOOL_NAME: str, lowercase, [a-z0-9_]
  - TOOL_METHOD: str, method name on SERVICE
  - TOOL_PARAMS_SCHEMA: dict, param names to type spec
"""
