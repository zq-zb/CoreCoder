from access_policy import can_access
from models import AccessRequest


def authorize_resource(user_id: str, role: str, owner_id: str) -> bool:
    request = AccessRequest(user_id=user_id, role=role, resource_owner_id=owner_id)
    return can_access(request)
