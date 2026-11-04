class WorkspaceError(Exception):
    """Base exception for user-facing workflow errors."""


class AuthenticationError(WorkspaceError):
    pass


class AuthorizationError(WorkspaceError):
    pass


class NotFoundError(WorkspaceError):
    pass


class ConflictError(WorkspaceError):
    pass


class ValidationError(WorkspaceError):
    pass


class IntegrationError(WorkspaceError):
    pass

