from dataclasses import dataclass


@dataclass(frozen=True)
class AccessRequest:
    user_id: str
    role: str
    resource_owner_id: str
